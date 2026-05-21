import os

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from main import (
    build_assignment_feed_text,
    clean_canvas_datetime_to_date,
    infer_assignment_subtype,
    normalize_canvas_assignment,
)
from utils import hash_item

# --- clean_canvas_datetime_to_date ---


def test_clean_canvas_datetime_valid_iso_zulu():
    assert clean_canvas_datetime_to_date("2026-04-12T23:59:00Z") == "2026-04-12"


def test_clean_canvas_datetime_valid_iso_with_offset():
    assert clean_canvas_datetime_to_date("2026-01-05T08:00:00-05:00") == "2026-01-05"


def test_clean_canvas_datetime_missing_or_empty():
    assert clean_canvas_datetime_to_date(None) is None
    assert clean_canvas_datetime_to_date("") is None


def test_clean_canvas_datetime_invalid():
    assert clean_canvas_datetime_to_date("not-a-date") is None
    assert clean_canvas_datetime_to_date("2026") is None
    assert clean_canvas_datetime_to_date(12345) is None


# --- infer_assignment_subtype ---


def test_infer_subtype_quiz_from_title():
    assert infer_assignment_subtype("Quiz 3: Arrays") == "quiz"


def test_infer_subtype_discussion_from_title():
    assert infer_assignment_subtype("Week 2 Discussion") == "discussion"


def test_infer_subtype_project_from_title():
    assert infer_assignment_subtype("Final Project Proposal") == "project"


def test_infer_subtype_paper_from_title():
    assert infer_assignment_subtype("Research Paper Draft") == "paper"


def test_infer_subtype_lab_from_title():
    assert infer_assignment_subtype("Lab 4: Sorting") == "lab"


def test_infer_subtype_homework_from_title():
    assert infer_assignment_subtype("Homework 2") == "homework"
    assert infer_assignment_subtype("HW 5") == "homework"


def test_infer_subtype_discussion_from_submission_types():
    assert infer_assignment_subtype("Weekly post", ["discussion_topic"]) == "discussion"


def test_infer_subtype_quiz_from_submission_types():
    assert infer_assignment_subtype("Module check", ["online_quiz"]) == "quiz"


def test_infer_subtype_default_assignment():
    assert infer_assignment_subtype("Problem Set 1") == "assignment"
    assert infer_assignment_subtype(None) == "assignment"


# --- normalize_canvas_assignment ---


def _minimal_assignment(**overrides):
    base = {
        "id": 42,
        "name": "Homework 1",
        "due_at": "2026-03-15T23:59:00Z",
        "points_possible": 10.0,
        "submission_types": ["online_upload"],
        "description": "<p>Submit your work</p>",
    }
    base.update(overrides)
    return base


def test_normalize_canvas_assignment_output_shape_and_fields():
    assignment = _minimal_assignment()
    result = normalize_canvas_assignment(assignment)

    assert set(result.keys()) == {
        "title",
        "item_type",
        "subtype",
        "start_date",
        "due_date",
        "description",
        "location",
        "external_id",
        "confidence",
        "details",
        "item_hash",
    }
    assert result["title"] == "Homework 1"
    assert result["item_type"] == "assignment"
    assert result["subtype"] == "homework"
    assert result["start_date"] is None
    assert result["due_date"] == "2026-03-15"
    assert result["description"] == "Submit your work"
    assert result["location"] is None
    assert result["external_id"] == "42"
    assert result["confidence"] == 0.98
    assert result["details"] == {
        "points_possible": 10.0,
        "submission_type": "online_upload",
    }


def test_normalize_canvas_assignment_item_hash():
    assignment = _minimal_assignment()
    result = normalize_canvas_assignment(assignment)

    expected_hash = hash_item(
        item_type="assignment",
        title="Homework 1",
        subtype="homework",
        start_date="",
        due_date="2026-03-15",
        external_id="42",
    )
    assert result["item_hash"] == expected_hash


def test_normalize_canvas_assignment_missing_due_at():
    assignment = _minimal_assignment(due_at=None)
    result = normalize_canvas_assignment(assignment)

    assert result["due_date"] is None
    assert normalize_canvas_assignment(_minimal_assignment(due_at="invalid"))["due_date"] is None


def test_normalize_canvas_assignment_untitled_and_no_id():
    result = normalize_canvas_assignment({"name": "   ", "submission_types": []})

    assert result["title"] == "Untitled Assignment"
    assert result["external_id"] is None
    assert result["subtype"] == "assignment"


def test_normalize_canvas_assignment_quiz_subtype():
    assignment = _minimal_assignment(name="Quiz 1", submission_types=["online_quiz"])
    result = normalize_canvas_assignment(assignment)

    assert result["subtype"] == "quiz"


# --- build_assignment_feed_text ---


def test_build_assignment_feed_text_single_assignment():
    assignments = [
        {
            "id": 7,
            "name": "Lab 2",
            "due_at": "2026-02-01T12:00:00Z",
            "points_possible": 25,
            "submission_types": ["online_upload", "online_text_entry"],
        }
    ]

    text = build_assignment_feed_text(assignments)

    assert text == (
        "id=7 | name=Lab 2 | due_date=2026-02-01 | points_possible=25 | "
        "submission_types=online_upload,online_text_entry"
    )


def test_build_assignment_feed_text_two_assignments_and_missing_due():
    assignments = [
        {
            "id": 1,
            "name": "Reading Quiz",
            "due_at": "2026-05-10T23:59:59Z",
            "points_possible": 5,
            "submission_types": ["online_quiz"],
        },
        {
            "id": 2,
            "name": "Untitled Assignment",
            "due_at": None,
            "points_possible": None,
            "submission_types": [],
        },
    ]

    text = build_assignment_feed_text(assignments)
    lines = text.split("\n")

    assert len(lines) == 2
    assert lines[0] == (
        "id=1 | name=Reading Quiz | due_date=2026-05-10 | points_possible=5 | "
        "submission_types=online_quiz"
    )
    assert lines[1] == (
        "id=2 | name=Untitled Assignment | due_date=null | points_possible=None | submission_types="
    )
