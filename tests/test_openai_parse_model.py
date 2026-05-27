import json
from unittest.mock import MagicMock, patch

import main
from main import ParseRequest


def _mock_parse_response(*, items: list[dict]) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({"items": items})
    return mock_response


def _base_item() -> dict:
    # Include explicit ISO dates to avoid date sanitization turning them into `None`.
    return {
        "item_type": "assignment",
        "title": "Homework 1",
        "confidence": 0.9,
        "start_date": "2026-02-10",
        "due_date": "2026-02-20",
    }


def _make_request() -> ParseRequest:
    # Include an explicit year in the source text so date sanitization keeps our ISO dates.
    return ParseRequest(
        course_id="test-course-1",
        source="manual",
        text="Spring 2026 syllabus text",
        term="Spring 2026",
    )


@patch("main.client.chat.completions.create")
def test_default_model_used_when_env_absent(mock_create, monkeypatch):
    monkeypatch.delenv("OPENAI_PARSE_MODEL", raising=False)

    mock_create.return_value = _mock_parse_response(items=[_base_item()])

    req = _make_request()
    result = main.parse(req)

    assert mock_create.call_args.kwargs["model"] == main.DEFAULT_OPENAI_PARSE_MODEL
    assert result["metadata"]["parse_model"] == main.DEFAULT_OPENAI_PARSE_MODEL


@patch("main.client.chat.completions.create")
def test_env_override_used_when_env_is_set(mock_create, monkeypatch):
    monkeypatch.setenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")

    mock_create.return_value = _mock_parse_response(items=[_base_item()])

    req = _make_request()
    result = main.parse(req)

    assert mock_create.call_args.kwargs["model"] == "gpt-4.1-mini"
    assert result["metadata"]["parse_model"] == "gpt-4.1-mini"


@patch("main.client.chat.completions.create")
def test_blank_whitespace_env_falls_back_to_default(mock_create, monkeypatch):
    monkeypatch.setenv("OPENAI_PARSE_MODEL", "   \n\t  ")

    mock_create.return_value = _mock_parse_response(items=[_base_item()])

    req = _make_request()
    result = main.parse(req)

    assert mock_create.call_args.kwargs["model"] == main.DEFAULT_OPENAI_PARSE_MODEL
    assert result["metadata"]["parse_model"] == main.DEFAULT_OPENAI_PARSE_MODEL


@patch("main.client.chat.completions.create")
def test_empty_string_env_falls_back_to_default(mock_create, monkeypatch):
    monkeypatch.setenv("OPENAI_PARSE_MODEL", "")

    mock_create.return_value = _mock_parse_response(items=[_base_item()])

    req = _make_request()
    result = main.parse(req)

    assert mock_create.call_args.kwargs["model"] == main.DEFAULT_OPENAI_PARSE_MODEL
    assert result["metadata"]["parse_model"] == main.DEFAULT_OPENAI_PARSE_MODEL


@patch("main.client.chat.completions.create")
def test_response_metadata_includes_parse_model_used(mock_create, monkeypatch):
    monkeypatch.setenv("OPENAI_PARSE_MODEL", "custom-parse-model")

    mock_create.return_value = _mock_parse_response(items=[_base_item()])

    req = _make_request()
    result = main.parse(req)

    assert result["metadata"]["parse_model"] == "custom-parse-model"
