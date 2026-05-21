import io
import os
import uuid
from unittest.mock import patch

from docx import Document

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from fastapi.testclient import TestClient

from main import SYLLABUS_SNAPSHOT_SOURCE_TYPES, app, extract_text_from_manual_upload

client = TestClient(app)


def _unique_course_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _syllabus_bytes(label: str) -> bytes:
    return f"Homework 1 due Friday - {label}\n".encode()


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
        "course_id": "manual-file-101",
        "source": "manual",
        "extraction_confidence": 0.95,
    },
}


def _upload_txt(content: bytes, *, course_key="manual-file-101", filename="syllabus.txt"):
    return client.post(
        "/manual/syllabus/file",
        data={
            "course_key": course_key,
            "sync_to_notion": "false",
        },
        files={"file": (filename, content, "text/plain")},
    )


def _minimal_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buffer)
    return buffer.getvalue()


def test_manual_file_in_syllabus_snapshot_source_types():
    assert "manual_file" in SYLLABUS_SNAPSHOT_SOURCE_TYPES
    assert "assignment_feed" not in SYLLABUS_SNAPSHOT_SOURCE_TYPES


@patch("main.parse", return_value=PARSE_RESULT)
def test_txt_upload_first_ingest_creates_snapshot_and_items(mock_parse):
    course_key = _unique_course_key("manual-file-first")
    response = _upload_txt(_syllabus_bytes(course_key), course_key=course_key)

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["sources"]["syllabus_changed"] is True
    mock_parse.assert_called_once()


@patch("main.parse", return_value=PARSE_RESULT)
def test_repeated_identical_txt_upload_returns_unchanged(mock_parse):
    course_key = _unique_course_key("manual-file-repeat")
    content = _syllabus_bytes(course_key)
    first = _upload_txt(content, course_key=course_key)
    second = _upload_txt(content, course_key=course_key)

    assert first.status_code == 200
    assert first.json()["changed"] is True
    assert second.status_code == 200
    assert second.json()["changed"] is False
    assert second.json()["sources"]["syllabus_changed"] is False
    assert second.json()["snapshot_id"] == first.json()["snapshot_id"]
    mock_parse.assert_called_once()


def test_unsupported_file_type_returns_400():
    response = _upload_txt(b"data", filename="notes.csv")

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_whitespace_only_txt_returns_400():
    response = _upload_txt(b"   \n\t  ")

    assert response.status_code == 400
    assert response.json()["detail"] == "No syllabus text provided"


def test_extract_text_from_docx_bytes_via_upload_helper():
    docx_bytes = _minimal_docx_bytes("Syllabus paragraph from docx")
    text = extract_text_from_manual_upload("course.docx", docx_bytes)

    assert "Syllabus paragraph from docx" in text


@patch("main.extract_text_from_pdf_bytes", return_value="PDF syllabus text")
def test_pdf_upload_uses_pdf_extractor(mock_pdf_extract):
    course_key = _unique_course_key("manual-file-pdf")
    with patch("main.parse", return_value=PARSE_RESULT):
        response = client.post(
            "/manual/syllabus/file",
            data={"course_key": course_key, "sync_to_notion": "false"},
            files={"file": ("syllabus.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

    assert response.status_code == 200
    mock_pdf_extract.assert_called_once()
