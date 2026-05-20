import os
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from main import REQUEST_TIMEOUT_SECONDS, fetch_course_modules


def _mock_response(*, status_code=200, json_data=None, link_header=None, text="error"):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = text
    response.headers = {"Link": link_header} if link_header else {}
    return response


def test_fetch_course_modules_single_page_no_next_link():
    modules = [{"id": 1, "name": "Week 1", "items": []}]

    with patch("main.requests.get") as mock_get:
        mock_get.return_value = _mock_response(json_data=modules)

        result = fetch_course_modules("101")

    assert result == modules
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS


def test_fetch_course_modules_follows_next_link_across_pages():
    page_one = [{"id": 1, "name": "Week 1", "items": []}]
    page_two = [{"id": 2, "name": "Week 2", "items": []}]
    next_url = (
        "https://example.instructure.com/api/v1/courses/101/modules"
        "?include[]=items&per_page=100&page=2"
    )

    with patch("main.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(
                json_data=page_one,
                link_header=f'<{next_url}>; rel="current", <{next_url}>; rel="next"',
            ),
            _mock_response(json_data=page_two),
        ]

        result = fetch_course_modules("101")

    assert result == page_one + page_two
    assert mock_get.call_count == 2

    first_call, second_call = mock_get.call_args_list
    assert first_call[0][0].endswith("/courses/101/modules?include[]=items&per_page=100")
    assert second_call[0][0] == next_url
    assert first_call[1]["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert second_call[1]["timeout"] == REQUEST_TIMEOUT_SECONDS


def test_fetch_course_modules_raises_on_non_list_json():
    with patch("main.requests.get") as mock_get:
        mock_get.return_value = _mock_response(json_data={"error": "not a list"})

        with pytest.raises(HTTPException) as exc_info:
            fetch_course_modules("101")

    assert exc_info.value.status_code == 500
    assert "unexpected data format" in exc_info.value.detail


def test_fetch_course_modules_raises_on_non_list_json_on_later_page():
    page_one = [{"id": 1, "name": "Week 1", "items": []}]
    next_url = (
        "https://example.instructure.com/api/v1/courses/101/modules"
        "?include[]=items&per_page=100&page=2"
    )

    with patch("main.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(
                json_data=page_one,
                link_header=f'<{next_url}>; rel="next"',
            ),
            _mock_response(json_data={"items": []}),
        ]

        with pytest.raises(HTTPException) as exc_info:
            fetch_course_modules("101")

    assert exc_info.value.status_code == 500
    assert "unexpected data format" in exc_info.value.detail


def test_fetch_course_modules_preserves_http_error_behavior():
    with patch("main.requests.get") as mock_get:
        mock_get.return_value = _mock_response(status_code=403, text="Forbidden")

        with pytest.raises(HTTPException) as exc_info:
            fetch_course_modules("101")

    assert exc_info.value.status_code == 403
    assert "Canvas Modules API error" in exc_info.value.detail
    assert "Forbidden" in exc_info.value.detail
