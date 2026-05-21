import importlib
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

CANVAS_CONFIG_DETAIL = (
    "Canvas is not configured. Set CANVAS_BASE_URL and CANVAS_ACCESS_TOKEN to use Canvas endpoints."
)

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


def _reload_main_without_canvas(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ENABLE_NOTION_SYNC", "false")
    monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
    monkeypatch.delenv("CANVAS_ACCESS_TOKEN", raising=False)
    import main

    return importlib.reload(main)


def test_main_imports_without_canvas_env(monkeypatch):
    main = _reload_main_without_canvas(monkeypatch)
    assert main.app is not None


def test_canvas_ingest_returns_503_without_config(monkeypatch):
    main = _reload_main_without_canvas(monkeypatch)
    client = TestClient(main.app)

    response = client.post("/canvas/ingest/123")

    assert response.status_code == 503
    assert response.json()["detail"] == CANVAS_CONFIG_DETAIL


def test_fetch_course_pages_raises_503_without_config(monkeypatch):
    main = _reload_main_without_canvas(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        main.fetch_course_pages("123")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == CANVAS_CONFIG_DETAIL


def test_manual_syllabus_works_without_canvas_env(monkeypatch):
    main = _reload_main_without_canvas(monkeypatch)
    client = TestClient(main.app)
    course_key = f"manual-no-canvas-{uuid.uuid4().hex}"

    with patch.object(main, "parse", return_value=PARSE_RESULT):
        response = client.post(
            "/manual/syllabus",
            json={
                "course_key": course_key,
                "course_name": "Manual Course",
                "text": "Homework 1 due Friday\n",
                "sync_to_notion": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert "changed" in body
    assert "snapshot_id" in body
