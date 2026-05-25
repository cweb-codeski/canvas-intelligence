import importlib.util
import os
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from main import ingest_syllabus_text
from models import Course, Item, SourceSnapshot
from utils import normalize_text

_GOLDEN_MODULE_PATH = Path(__file__).resolve().parent / "fixtures" / "golden_syllabus.py"
_spec = importlib.util.spec_from_file_location("golden_syllabus_fixture", _GOLDEN_MODULE_PATH)
golden = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(golden)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _ingest_golden(db, course, *, sync_to_notion: bool = False):
    return ingest_syllabus_text(
        db=db,
        course=course,
        course_id=golden.COURSE_KEY,
        course_name="Golden Syllabus Course",
        final_text=golden.load_golden_text(),
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier=golden.COURSE_KEY,
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
                "item_hash": golden.expected_item_hash(spec),
                "confidence": spec["confidence"],
                "status": "active",
            }
            for spec in golden.KEPT_ITEM_SPECS
        ],
        key=lambda row: row["title"],
    )


@patch("main.parse", return_value=golden.GOLDEN_PARSE_RESULT)
def test_golden_syllabus_first_ingest_persists_expected_items(mock_parse):
    db = _make_session()
    course = Course(
        canvas_course_id=golden.COURSE_KEY,
        course_name="Golden Syllabus Course",
        term=golden.COURSE_TERM,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    result = _ingest_golden(db, course)

    assert result["changed"] is True
    assert result["sources"]["syllabus_changed"] is True
    assert result["notion_config"] == {
        "status": "not_checked",
        "reason": "sync_to_notion disabled",
    }
    assert result["notion_sync"] == {
        "attempted": False,
        "reason": "sync_to_notion disabled",
    }

    snapshot = db.query(SourceSnapshot).filter_by(id=result["snapshot_id"]).one()
    assert snapshot.source_type == "manual_text"
    assert snapshot.source_name == "manual_paste"
    assert snapshot.source_identifier == golden.COURSE_KEY
    assert snapshot.content_hash == golden.golden_content_hash()

    db_items = db.query(Item).filter_by(snapshot_id=snapshot.id).all()
    assert len(db_items) == 3
    assert _sorted_item_dicts(db_items) == _expected_sorted_item_dicts()

    response_items = sorted(result["items"], key=lambda row: row["title"])
    assert len(response_items) == 3
    assert all(golden.FILTERED_ITEM_TITLE != row["title"] for row in response_items)
    for row, spec in zip(
        response_items,
        sorted(golden.KEPT_ITEM_SPECS, key=lambda s: s["title"]),
        strict=True,
    ):
        assert row["title"] == spec["title"]
        assert row["item_type"] == spec["item_type"]
        assert row["item_hash"] == golden.expected_item_hash(spec)

    mock_parse.assert_called_once()
    req = mock_parse.call_args[0][0]
    assert req.course_id == golden.COURSE_KEY
    assert req.source == "manual"
    assert req.text == normalize_text(golden.load_golden_text())
    assert req.term == golden.COURSE_TERM


@patch("main.parse", return_value=golden.GOLDEN_PARSE_RESULT)
def test_golden_syllabus_filters_bucket_assignment(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id=golden.COURSE_KEY, course_name="Golden Syllabus Course")
    db.add(course)
    db.commit()
    db.refresh(course)

    result = _ingest_golden(db, course)

    titles = {item["title"] for item in result["items"]}
    assert golden.FILTERED_ITEM_TITLE not in titles
    assert len(result["items"]) == len(golden.KEPT_ITEM_SPECS)
    assert len(golden.GOLDEN_PARSE_RESULT["items"]) == 4
    mock_parse.assert_called_once()


@patch("main.parse", return_value=golden.GOLDEN_PARSE_RESULT)
def test_golden_syllabus_route_matches_pipeline(mock_parse, client):
    course_key = f"golden-route-{uuid.uuid4().hex}"

    response = client.post(
        "/manual/syllabus",
        json={
            "course_key": course_key,
            "course_name": "Golden Route Course",
            "term": golden.COURSE_TERM,
            "text": golden.load_golden_text(),
            "sync_to_notion": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = {item["title"] for item in body["items"]}
    assert titles == {spec["title"] for spec in golden.KEPT_ITEM_SPECS}
    assert golden.FILTERED_ITEM_TITLE not in titles
    mock_parse.assert_called_once()
