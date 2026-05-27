import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from main import ParseRequest, parse
from utils import preprocess_lab_schedule_rows

# Fictional course excerpts only — not real syllabus text.

MERGED_LAB_SIX_SEVEN = (
    "Lab Schedule BIO999L Spring 2026 Day/Date Topics "
    "Lab 6 MT 3/9-10 5 Gram stain practice and colony counting "
    "Lab 7 W TH 3/11-12 6 UV exposure and mutagenesis module"
)

LAB_TWENTY_MULTI_TOPIC = (
    "Lab Schedule BIO999L Spring 2026 "
    "Lab 20 MT 4/6-7 16 16: Detection of cultures 17: Enrichment step "
    "18: Isolation drill Lab 21 W TH 4/8-9 17 Follow-up cultures"
)

NO_ANCHOR_TEXT = (
    "Wear your lab coat to class. Submit the lab report by Friday. BIOL 999L meets in room 420."
)

SINGLE_CASUAL_LAB = (
    "Course policies and grading. Lab 3 in the manual covers safety. Office hours are Tuesdays."
)

GOLDEN_STYLE_PROSE = (
    "Homework 1 due 2026-02-10\nMidterm Exam March 15\n"
    "Reading: Chapter 3 for January 20\n"
    "Weekly quiz sessions will occur throughout the term."
)


def test_splits_merged_lab_six_and_seven_rows():
    result = preprocess_lab_schedule_rows(MERGED_LAB_SIX_SEVEN)

    assert "\nLab 6 MT 3/9-10" in result
    assert "\nLab 7 W TH 3/11-12" in result
    assert "Lab 6 MT 3/9-10 5 Gram stain" in result
    assert "Lab 7 W TH 3/11-12 6 UV exposure" in result
    assert "Lab 6 MT 3/9-10 5 Gram stain practice and colony counting Lab 7" not in result


def test_lab_twenty_multi_topic_stays_on_one_row():
    result = preprocess_lab_schedule_rows(LAB_TWENTY_MULTI_TOPIC)

    lab_twenty_lines = [line for line in result.split("\n") if line.strip().startswith("Lab 20")]
    assert len(lab_twenty_lines) == 1
    lab_twenty_line = lab_twenty_lines[0]
    assert "16: Detection" in lab_twenty_line
    assert "17: Enrichment" in lab_twenty_line
    assert "18: Isolation" in lab_twenty_line
    assert "\n16:" not in result
    assert "\n17:" not in result
    assert "\n18:" not in result
    assert "\nLab 21" in result


def test_no_op_without_lab_schedule_anchor():
    for text in (NO_ANCHOR_TEXT, GOLDEN_STYLE_PROSE):
        assert preprocess_lab_schedule_rows(text) == text


def test_no_op_with_only_one_casual_lab_mention():
    assert preprocess_lab_schedule_rows(SINGLE_CASUAL_LAB) == SINGLE_CASUAL_LAB


def test_idempotent_on_merged_schedule():
    once = preprocess_lab_schedule_rows(MERGED_LAB_SIX_SEVEN)
    twice = preprocess_lab_schedule_rows(once)
    assert once == twice


def test_idempotent_on_already_split_fixture_style():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "lab_schedule_syllabus.txt"
    text = fixture_path.read_text(encoding="utf-8")
    once = preprocess_lab_schedule_rows(text)
    twice = preprocess_lab_schedule_rows(once)
    assert once == twice


@pytest.fixture
def minimal_parse_item():
    return {
        "item_type": "lecture",
        "subtype": "lab",
        "title": "Lab 6",
        "description": "",
        "location": None,
        "start_date": "2026-03-09",
        "due_date": "2026-03-10",
        "external_id": None,
        "confidence": 0.9,
        "details": {},
    }


@patch("main.sanitize_extracted_item_dates", side_effect=lambda item, *_a, **_k: item)
@patch("main.client.chat.completions.create")
def test_parse_uses_preprocessed_prompt_and_original_for_sanitize(
    mock_create,
    _mock_sanitize,
    minimal_parse_item,
):
    original = f"Intro paragraph.\n\n{MERGED_LAB_SIX_SEVEN}"

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({"items": [minimal_parse_item]})
    mock_create.return_value = mock_response

    req = ParseRequest(
        course_id="wire-test",
        source="manual",
        text=original,
        term="Spring 2026",
    )
    parse(req)

    prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "\nLab 6 MT 3/9-10" in prompt
    assert "\nLab 7 W TH 3/11-12" in prompt
    assert "Lab 6 MT 3/9-10 5 Gram stain practice and colony counting Lab 7" not in prompt
    assert original in prompt or "Intro paragraph." in prompt

    _mock_sanitize.assert_called_once()
    sanitize_args = _mock_sanitize.call_args
    assert sanitize_args[0][1] == original
