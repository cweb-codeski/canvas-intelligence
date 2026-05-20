import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from main import (
    ingest_syllabus_text,
    notion_config_for_response,
    notion_sync_for_unchanged_syllabus,
    sync_items_to_notion,
)
from models import Course

PARSE_RESULT = {
    "items": [
        {
            "item_type": "assignment",
            "title": "HW 1",
            "subtype": "homework",
            "confidence": 0.95,
        }
    ],
    "metadata": {"course_id": "notion-test", "source": "manual"},
}


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_sync_items_to_notion_aggregates_results():
    items = [
        {"title": "HW 1", "item_hash": "a"},
        {"title": "HW 2", "item_hash": "b"},
    ]
    course_name = "CS 101"

    with patch("main.create_notion_item") as mock_create:
        mock_create.side_effect = [
            {"status": "created", "title": "HW 1"},
            {"status": "skipped", "title": "HW 2", "reason": "duplicate"},
        ]

        result = sync_items_to_notion(items, course_name)

    assert result["attempted"] is True
    assert result["created"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert len(result["results"]) == 2
    assert mock_create.call_count == 2
    mock_create.assert_any_call(items[0], course_name)
    mock_create.assert_any_call(items[1], course_name)


def test_notion_sync_for_unchanged_syllabus_skips_when_assignment_feed_unchanged():
    assignment_result = {
        "changed": False,
        "items": [{"title": "HW 1", "item_hash": "a"}],
    }

    with patch("main.create_notion_item") as mock_create:
        result = notion_sync_for_unchanged_syllabus(assignment_result, "CS 101")

    assert result["attempted"] is False
    assert "syllabus unchanged" in result["reason"]
    mock_create.assert_not_called()


def test_notion_sync_for_unchanged_syllabus_syncs_when_assignment_feed_changed():
    assignment_items = [
        {"title": "New HW", "item_hash": "new-hash", "item_type": "assignment"},
    ]
    assignment_result = {
        "changed": True,
        "items": assignment_items,
    }

    with patch("main.create_notion_item") as mock_create:
        mock_create.return_value = {"status": "created", "title": "New HW"}

        result = notion_sync_for_unchanged_syllabus(assignment_result, "CS 101")

    assert result["attempted"] is True
    assert result["created"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    mock_create.assert_called_once_with(assignment_items[0], "CS 101")


def test_notion_config_for_response_when_sync_disabled():
    with patch("main.check_notion_config") as mock_check:
        result = notion_config_for_response(False)

    assert result == {
        "status": "not_checked",
        "reason": "sync_to_notion disabled",
    }
    mock_check.assert_not_called()


def test_notion_config_for_response_when_sync_enabled():
    expected = {"status": "ok", "missing_properties": []}

    with patch("main.check_notion_config", return_value=expected) as mock_check:
        result = notion_config_for_response(True)

    assert result == expected
    mock_check.assert_called_once()


@patch("main.parse", return_value=PARSE_RESULT)
def test_ingest_syllabus_text_sync_disabled_skips_notion_config_check(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="notion-skip-check", course_name="Notion Test")
    db.add(course)
    db.commit()
    db.refresh(course)

    with patch("main.check_notion_config") as mock_check:
        result = ingest_syllabus_text(
            db=db,
            course=course,
            course_id="notion-skip-check",
            course_name="Notion Test",
            final_text="Syllabus with homework due Friday\n",
            source_type="manual_text",
            source_name="manual_paste",
            source_identifier="notion-skip-check",
            sync_to_notion=False,
            parse_source="manual",
        )

    mock_check.assert_not_called()
    assert result["notion_config"]["status"] == "not_checked"
    assert result["notion_config"]["reason"] == "sync_to_notion disabled"
    assert result["notion_sync"]["attempted"] is False


@patch("main.parse", return_value=PARSE_RESULT)
def test_ingest_syllabus_text_sync_enabled_checks_notion_config(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="notion-do-check", course_name="Notion Test")
    db.add(course)
    db.commit()
    db.refresh(course)

    expected_config = {"status": "ok", "missing_properties": []}

    with patch("main.check_notion_config", return_value=expected_config) as mock_check:
        result = ingest_syllabus_text(
            db=db,
            course=course,
            course_id="notion-do-check",
            course_name="Notion Test",
            final_text="Syllabus with exam on September 12\n",
            source_type="manual_text",
            source_name="manual_paste",
            source_identifier="notion-do-check",
            sync_to_notion=True,
            parse_source="manual",
        )

    mock_check.assert_called_once()
    assert result["notion_config"] == expected_config


@patch("main.parse", return_value=PARSE_RESULT)
def test_ingest_unchanged_syllabus_sync_disabled_skips_notion_config_check(mock_parse):
    db = _make_session()
    course = Course(canvas_course_id="notion-unchanged", course_name="Notion Test")
    db.add(course)
    db.commit()
    db.refresh(course)

    syllabus_text = "Unchanged syllabus content for notion config test\n"

    ingest_syllabus_text(
        db=db,
        course=course,
        course_id="notion-unchanged",
        course_name="Notion Test",
        final_text=syllabus_text,
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier="notion-unchanged",
        sync_to_notion=True,
        parse_source="manual",
    )

    with patch("main.check_notion_config") as mock_check:
        result = ingest_syllabus_text(
            db=db,
            course=course,
            course_id="notion-unchanged",
            course_name="Notion Test",
            final_text=syllabus_text,
            source_type="manual_text",
            source_name="manual_paste",
            source_identifier="notion-unchanged",
            sync_to_notion=False,
            parse_source="manual",
        )

    mock_check.assert_not_called()
    assert result["notion_config"]["status"] == "not_checked"
    assert result["sources"]["syllabus_changed"] is False
