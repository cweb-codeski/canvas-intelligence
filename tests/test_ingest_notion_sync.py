import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from main import notion_sync_for_unchanged_syllabus, sync_items_to_notion


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
