import copy
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from main import ingest_syllabus_text
from models import Course, Item
from utils import normalize_text, sanitize_extracted_item_dates

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "lab_schedule_syllabus.py"
_spec = importlib.util.spec_from_file_location("lab_schedule_fixture", _FIXTURE_PATH)
lab_schedule = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(lab_schedule)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _ingest_lab_schedule(db, course, *, sync_to_notion: bool = False):
    return ingest_syllabus_text(
        db=db,
        course=course,
        course_id=lab_schedule.COURSE_KEY,
        course_name="Lab Schedule Course",
        final_text=lab_schedule.load_lab_schedule_text(),
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier=lab_schedule.COURSE_KEY,
        sync_to_notion=sync_to_notion,
        parse_source="manual",
    )


def _sorted_item_dicts(items):
    return sorted(
        [
            {
                "title": item.title,
                "item_type": item.item_type,
                "subtype": item.subtype,
                "start_date": item.start_date,
                "due_date": item.due_date,
                "item_hash": item.item_hash,
                "confidence": item.confidence,
                "status": item.status,
            }
            for item in items
        ],
        key=lambda row: row["title"],
    )


def _expected_sorted_item_dicts():
    return sorted(
        [
            {
                "title": spec["title"],
                "item_type": spec["item_type"],
                "subtype": spec["subtype"],
                "start_date": spec["start_date"],
                "due_date": spec["due_date"],
                "item_hash": lab_schedule.expected_item_hash(spec),
                "confidence": spec["confidence"],
                "status": "active",
            }
            for spec in lab_schedule.KEPT_ITEM_SPECS
        ],
        key=lambda row: row["title"],
    )


def _parse_lab_schedule_with_sanitize(req):
    """Simulate parse post-processing: wrong years cleared/normalized via sanitizer."""
    result = copy.deepcopy(lab_schedule.LAB_SCHEDULE_PARSE_RESULT)
    source = normalize_text(req.text or "")
    for item in result["items"]:
        for field in ("start_date", "due_date"):
            value = item.get(field)
            if value and value.startswith("2026-"):
                item[field] = value.replace("2026", "2023", 1)
        sanitize_extracted_item_dates(item, source, term=req.term)
    return result


@patch("main.parse", side_effect=_parse_lab_schedule_with_sanitize)
def test_lab_schedule_ingest_persists_labs_and_practicals(mock_parse):
    db = _make_session()
    course = Course(
        canvas_course_id=lab_schedule.COURSE_KEY,
        course_name="Lab Schedule Course",
        term=lab_schedule.COURSE_TERM,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    result = _ingest_lab_schedule(db, course)

    assert result["changed"] is True
    assert len(result["items"]) == len(lab_schedule.KEPT_ITEM_SPECS)

    db_items = db.query(Item).filter_by(snapshot_id=result["snapshot_id"]).all()
    assert len(db_items) == len(lab_schedule.KEPT_ITEM_SPECS)
    assert _sorted_item_dicts(db_items) == _expected_sorted_item_dicts()

    for item in db_items:
        assert item.item_hash
        if item.item_type == "lecture":
            assert item.subtype == "lab"
            assert item.start_date is not None
        if item.item_type == "exam":
            assert item.subtype and "practical" in item.subtype

    mock_parse.assert_called_once()
