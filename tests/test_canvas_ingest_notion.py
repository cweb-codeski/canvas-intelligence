import os
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "true")

from conftest import isolated_app_db
from fastapi.testclient import TestClient

import main as main_module
from main import app

SYLLABUS_HTML = "<p>" + ("Course syllabus content for canvas ingest testing. " * 30) + "</p>"

PARSE_RESULT = {
    "items": [
        {
            "item_type": "assignment",
            "title": "Homework 1",
            "subtype": "homework",
            "confidence": 0.95,
        }
    ],
    "metadata": {
        "course_id": "123",
        "source": "canvas",
        "extraction_confidence": 0.95,
    },
}

INGEST_STUB_RESPONSE = {
    "course_id": "123",
    "changed": True,
    "snapshot_id": 1,
    "items": [],
    "notion_sync": {"attempted": False},
    "notion_config": {"status": "not_checked"},
}


@contextmanager
def _canvas_fetch_patches():
    with (
        patch.object(main_module, "fetch_course_name", return_value="Canvas Course"),
        patch.object(main_module, "fetch_canvas_assignments", return_value=[]),
        patch.object(main_module, "fetch_syllabus", return_value=SYLLABUS_HTML),
        patch.object(main_module, "fetch_course_pages", return_value=[]),
        patch.object(main_module, "find_syllabus_file_in_modules", return_value=None),
    ):
        yield


def test_canvas_ingest_passes_sync_to_notion_false(tmp_path):
    with isolated_app_db(app, tmp_path):
        with _canvas_fetch_patches():
            with patch.object(
                main_module,
                "ingest_syllabus_text",
                return_value=INGEST_STUB_RESPONSE,
            ) as mock_ingest:
                client = TestClient(app)
                response = client.post("/canvas/ingest/123?sync_to_notion=false")

    assert response.status_code == 200
    mock_ingest.assert_called_once()
    assert mock_ingest.call_args.kwargs["sync_to_notion"] is False


def test_canvas_ingest_defaults_sync_to_notion_true(tmp_path):
    with isolated_app_db(app, tmp_path):
        with _canvas_fetch_patches():
            with patch.object(
                main_module,
                "ingest_syllabus_text",
                return_value=INGEST_STUB_RESPONSE,
            ) as mock_ingest:
                client = TestClient(app)
                response = client.post("/canvas/ingest/123")

    assert response.status_code == 200
    mock_ingest.assert_called_once()
    assert mock_ingest.call_args.kwargs["sync_to_notion"] is True


def test_canvas_ingest_sync_disabled_skips_notion_config(tmp_path):
    with isolated_app_db(app, tmp_path):
        with _canvas_fetch_patches():
            with patch.object(main_module, "parse", return_value=PARSE_RESULT):
                with patch("main.check_notion_config") as mock_check:
                    client = TestClient(app)
                    response = client.post("/canvas/ingest/123?sync_to_notion=false")

    assert response.status_code == 200
    body = response.json()
    assert body["notion_config"]["status"] == "not_checked"
    assert body["notion_config"]["reason"] == "sync_to_notion disabled"
    assert body["notion_sync"]["attempted"] is False
    assert body["notion_sync"]["reason"] == "sync_to_notion disabled"
    mock_check.assert_not_called()
