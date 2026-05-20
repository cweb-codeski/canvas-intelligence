import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from main import ingest_syllabus_text
from models import Course, Item, SourceSnapshot


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _parse_result():
    return {
        "items": [
            {
                "item_type": "assignment",
                "title": "Homework 1",
                "subtype": "homework",
                "confidence": 0.95,
            }
        ],
        "metadata": {
            "course_id": "manual-101",
            "source": "manual",
            "extraction_confidence": 0.95,
        },
    }


def _ingest(db, course, text, *, course_key="manual-101"):
    return ingest_syllabus_text(
        db=db,
        course=course,
        course_id=course_key,
        course_name="Manual Course",
        final_text=text,
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier=course_key,
        sync_to_notion=False,
        parse_source="manual",
    )


@patch("main.parse", return_value=_parse_result())
def test_first_manual_ingest_creates_snapshot_and_items(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="manual-101", course_name="Manual Course")
    db.add(course)
    db.commit()
    db.refresh(course)

    result = _ingest(db, course, "Homework 1 due Friday\n")

    assert result["changed"] is True
    assert result["sources"]["syllabus_changed"] is True

    snapshot = db.query(SourceSnapshot).filter_by(id=result["snapshot_id"]).one()
    assert snapshot.source_type == "manual_text"
    assert snapshot.source_name == "manual_paste"
    assert snapshot.source_identifier == "manual-101"

    items = db.query(Item).filter_by(snapshot_id=snapshot.id).all()
    assert len(items) == 1
    assert items[0].title == "Homework 1"
    mock_parse.assert_called_once()


@patch("main.parse", return_value=_parse_result())
def test_repeated_identical_manual_ingest_returns_unchanged(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="manual-101", course_name="Manual Course")
    db.add(course)
    db.commit()
    db.refresh(course)

    text = "Homework 1 due Friday\n"
    first = _ingest(db, course, text)
    second = _ingest(db, course, text)

    assert first["changed"] is True
    assert second["changed"] is False
    assert second["sources"]["syllabus_changed"] is False
    assert second["snapshot_id"] == first["snapshot_id"]
    assert db.query(SourceSnapshot).count() == 1
    mock_parse.assert_called_once()


@patch("main.parse", return_value=_parse_result())
def test_changed_manual_text_creates_new_snapshot(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="manual-101", course_name="Manual Course")
    db.add(course)
    db.commit()
    db.refresh(course)

    first = _ingest(db, course, "Homework 1 due Friday\n")
    second = _ingest(db, course, "Homework 2 due Monday\n")

    assert first["changed"] is True
    assert second["changed"] is True
    assert second["snapshot_id"] != first["snapshot_id"]
    assert db.query(SourceSnapshot).count() == 2
    assert mock_parse.call_count == 2
