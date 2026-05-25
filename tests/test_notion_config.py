import importlib
import uuid
from unittest.mock import patch

from conftest import isolated_app_db
from fastapi.testclient import TestClient

MISSING_CREDENTIALS_REASON = "NOTION_API_KEY or NOTION_DATABASE_ID is not set"

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
        "course_id": "manual-101",
        "source": "manual",
        "extraction_confidence": 0.95,
    },
}


def _reload_main_without_notion(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_NOTION_SYNC", "true")
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    import notion

    importlib.reload(notion)
    import main

    return importlib.reload(main)


def test_main_imports_without_notion_env(monkeypatch):
    main = _reload_main_without_notion(monkeypatch)
    assert main.app is not None


def test_notion_status_returns_error_without_credentials(monkeypatch):
    main = _reload_main_without_notion(monkeypatch)

    with patch("notion.requests.get") as mock_get, patch("notion.requests.post") as mock_post:
        client = TestClient(main.app)
        response = client.get("/notion/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["reason"] == MISSING_CREDENTIALS_REASON
    mock_get.assert_not_called()
    mock_post.assert_not_called()


def test_manual_syllabus_sync_enabled_reports_notion_config_error(monkeypatch, tmp_path):
    main = _reload_main_without_notion(monkeypatch)
    course_key = f"manual-no-notion-{uuid.uuid4().hex}"

    with isolated_app_db(main.app, tmp_path):
        with patch.object(main, "parse", return_value=PARSE_RESULT):
            with (
                patch("notion.requests.get") as mock_get,
                patch("notion.requests.post") as mock_post,
            ):
                client = TestClient(main.app)
                response = client.post(
                    "/manual/syllabus",
                    json={
                        "course_key": course_key,
                        "course_name": "Manual Course",
                        "text": "Homework 1 due Friday\n",
                        "sync_to_notion": True,
                    },
                )

    assert response.status_code == 200
    body = response.json()
    assert body["notion_config"]["status"] == "error"
    assert body["notion_config"]["reason"] == MISSING_CREDENTIALS_REASON
    assert body["notion_sync"]["attempted"] is True
    assert body["notion_sync"]["failed"] >= 1
    assert body["notion_sync"]["created"] == 0
    for result in body["notion_sync"]["results"]:
        assert result["status"] == "failed"
        assert result["reason"] == MISSING_CREDENTIALS_REASON
    mock_get.assert_not_called()
    mock_post.assert_not_called()


def test_create_notion_item_failed_without_credentials(monkeypatch):
    _reload_main_without_notion(monkeypatch)
    import notion

    item = {"title": "Homework 1", "item_hash": "abc123"}

    with patch("notion.requests.get") as mock_get, patch("notion.requests.post") as mock_post:
        result = notion.create_notion_item(item, "Manual Course")

    assert result["status"] == "failed"
    assert result["reason"] == MISSING_CREDENTIALS_REASON
    mock_get.assert_not_called()
    mock_post.assert_not_called()
