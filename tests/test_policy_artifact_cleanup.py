"""Tests for conservative suppression of undated grading-policy/SLO artifacts.

Fixture items below are MATH252-style but fictional — not real syllabus text.
"""

import json
from unittest.mock import MagicMock, patch

from main import ParseRequest, parse
from utils import (
    cleanup_undated_policy_artifact_items,
    is_undated_policy_artifact_item,
)


def _item(
    title: str,
    *,
    item_type: str = "assignment",
    subtype: str = "quiz",
    start_date: str | None = None,
    due_date: str | None = None,
    description: str = "",
    location: str | None = None,
    confidence: float = 0.7,
) -> dict:
    return {
        "title": title,
        "item_type": item_type,
        "subtype": subtype,
        "start_date": start_date,
        "due_date": due_date,
        "description": description,
        "location": location,
        "confidence": confidence,
    }


# Minimal MATH252-style parse output: 3 policy artifacts among real items.
MATH252_STYLE_ITEMS = [
    _item(
        "Pop Quiz I",
        description="Pop quiz referenced in grading policy; no specific date provided.",
        location="Course grading policy",
    ),
    _item(
        "Pop Quiz II",
        description="Pop quiz referenced in grading policy; no specific date provided.",
        location="Course grading policy",
    ),
    _item(
        "Reading Assignment (of Supplemental materials)",
        item_type="reading",
        subtype="supplemental_reading",
        description="Supplemental reading assignment tied to Outcome 4 assessment strategy.",
    ),
    _item(
        "Mid Term 1",
        item_type="exam",
        subtype="midterm",
        start_date="2023-09-22",
        description="Scheduled midterm exam.",
        confidence=0.99,
    ),
    _item(
        "Quiz III",
        item_type="exam",
        subtype="quiz",
        start_date="2023-11-20",
        description="Online quiz listed in grading policies and schedule.",
        confidence=0.98,
    ),
    _item(
        "Final Exam",
        item_type="exam",
        subtype="final",
        start_date="2023-12-13",
        description="Final exam scheduled for 8:00-10:00.",
        confidence=0.99,
    ),
]


def test_undated_pop_quizzes_from_grading_breakdown_are_removed():
    cleaned = cleanup_undated_policy_artifact_items(MATH252_STYLE_ITEMS)

    titles = [item["title"] for item in cleaned]
    assert "Pop Quiz I" not in titles
    assert "Pop Quiz II" not in titles


def test_undated_assessment_strategy_reading_is_removed():
    cleaned = cleanup_undated_policy_artifact_items(MATH252_STYLE_ITEMS)

    titles = [item["title"] for item in cleaned]
    assert "Reading Assignment (of Supplemental materials)" not in titles


def test_dated_items_are_always_preserved():
    cleaned = cleanup_undated_policy_artifact_items(MATH252_STYLE_ITEMS)

    titles = [item["title"] for item in cleaned]
    assert "Mid Term 1" in titles
    assert "Quiz III" in titles
    assert "Final Exam" in titles


def test_dated_quiz_mentioning_grading_policy_is_preserved():
    quiz = _item(
        "Quiz III",
        item_type="exam",
        start_date="2023-11-20",
        description="Online quiz listed in grading policies and schedule.",
    )
    assert not is_undated_policy_artifact_item(quiz)


def test_undated_quiz_with_due_language_is_preserved():
    quiz = _item(
        "Weekly Quiz",
        description="Quiz from the grading policy section, due Friday at 11:59 PM.",
    )
    assert not is_undated_policy_artifact_item(quiz)
    assert cleanup_undated_policy_artifact_items([quiz]) == [quiz]


def test_undated_module_project_milestones_are_preserved():
    modules = [
        _item(
            f"Module {n}",
            subtype="module_project",
            description=f"Module {n} project: write and revise a major deliverable.",
            location="Canvas",
            confidence=0.95,
        )
        for n in (1, 2, 3)
    ]

    cleaned = cleanup_undated_policy_artifact_items(modules)

    assert cleaned == modules


def test_undated_cadence_description_is_not_suppressed():
    homework = _item(
        "Weekly Homework",
        subtype="homework",
        description="Homework is posted Wednesday and due Friday at 11:59 PM via WebAssign.",
    )

    cleaned = cleanup_undated_policy_artifact_items([homework])

    assert cleaned == [homework]


def test_undated_midterm_and_final_subtypes_are_never_suppressed():
    items = [
        _item(
            "Midterm Exam",
            item_type="exam",
            subtype="midterm",
            description="Midterm listed in the grading breakdown.",
        ),
        _item(
            "Final Exam",
            item_type="exam",
            subtype="final",
            description="Final exam worth 30% per the grading policy.",
        ),
    ]

    cleaned = cleanup_undated_policy_artifact_items(items)

    assert cleaned == items


def test_plain_quiz_or_reading_titles_alone_are_not_suppressed():
    items = [
        _item("Quiz 2", description="Quiz covering chapter 3."),
        _item(
            "Chapter 5 Reading",
            item_type="reading",
            subtype="textbook_chapter",
            description="Read chapter 5 before the next class meeting.",
        ),
    ]

    cleaned = cleanup_undated_policy_artifact_items(items)

    assert cleaned == items


def test_undated_supplemental_reading_without_policy_context_is_preserved():
    reading = _item(
        "Supplemental Reading for Chapter 16",
        item_type="reading",
        subtype="supplemental_reading",
        description="Read the supplemental materials for Chapter 16 before class.",
    )

    cleaned = cleanup_undated_policy_artifact_items([reading])

    assert cleaned == [reading]


@patch("main.client.chat.completions.create")
def test_parse_applies_policy_artifact_cleanup(mock_create):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {
            "items": [
                {
                    "title": "Pop Quiz I",
                    "item_type": "assignment",
                    "subtype": "quiz",
                    "start_date": None,
                    "due_date": None,
                    "description": "Pop quiz referenced in grading policy.",
                    "confidence": 0.6,
                },
                {
                    "title": "Mid Term 1",
                    "item_type": "exam",
                    "subtype": "midterm",
                    "start_date": "2023-09-22",
                    "due_date": None,
                    "description": "Scheduled midterm exam.",
                    "confidence": 0.99,
                },
            ]
        }
    )
    mock_create.return_value = mock_response

    result = parse(
        ParseRequest(
            course_id="math999-test",
            source="manual",
            text="Grading: Pop Quizzes I & II (2.5% each). Mid Term 1 (Sep 22, 2023).",
            term="Fall 2023",
        )
    )

    titles = [item["title"] for item in result["items"]]
    assert "Pop Quiz I" not in titles
    assert "Mid Term 1" in titles
