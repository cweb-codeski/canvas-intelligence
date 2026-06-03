"""Deterministic lab-schedule pipeline diagnostics (fictional fixtures only).

These tests separate extraction/normalization/preprocess/filter/cache behavior from
live OpenAI parse completeness. They do not assert correct production semantics for
multi-date lab rows.

Semantic note (documented, not fixed here):
  Patterns like WTh 1/21,22, M T 1/26,27, or MT 2/2-3 usually denote alternate
  section meeting dates for the same lab week, not start_date/due_date ranges.
  Mapping the second token to due_date is misleading; schema/prompt changes are
  intentionally out of scope for this diagnostic module.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from ingestion import should_keep_item
from main import ingest_syllabus_text
from models import Course, Item
from utils import (
    LAB_SCHEDULE_ROW_HEAD_RE,
    normalize_text,
    preprocess_lab_schedule_rows,
    sanitize_extracted_item_dates,
)

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "bio999_flattened_lab_schedule.txt"

# Fictional date tokens present in the fixture (not real course dates).
_DATE_TOKENS = (
    "WTh 1/21,22",
    "M T 1/26,27",
    "W TH 1/28-29",
    "MT 2/2-3",
    "W TH 4/29/30",
)

# Minimum dated Lab N row heads expected in the flattened fixture paragraph.
_MIN_LAB_ROW_HEADS = 8


def _load_flattened_fixture() -> str:
    return _FIXTURE_PATH.read_text(encoding="utf-8")


def _count_lab_row_heads(text: str) -> int:
    return len(LAB_SCHEDULE_ROW_HEAD_RE.findall(text))


def _count_newline_prefixed_lab_rows(text: str) -> int:
    return sum(1 for line in text.split("\n") if line.strip().startswith("Lab "))


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _lab_lecture_item(
    *,
    title: str,
    start_date: str,
    due_date: str | None = None,
) -> dict:
    return {
        "item_type": "lecture",
        "subtype": "lab",
        "title": title,
        "description": "Fictional lab week",
        "location": None,
        "start_date": start_date,
        "due_date": due_date,
        "external_id": None,
        "confidence": 0.9,
    }


def _lab_practical_item() -> dict:
    return {
        "item_type": "exam",
        "subtype": "lab_practical",
        "title": "Lab 13 — LAB PRACTICAL 1",
        "description": "Timed skills check",
        "location": None,
        "start_date": "2026-03-04",
        "due_date": "2026-03-05",
        "external_id": None,
        "confidence": 0.92,
    }


def _parse_result_many_labs():
    """Simulates a parse that returns several lab rows (model behavior mocked out)."""
    items = [
        _lab_lecture_item(title="Lab 1", start_date="2026-01-21", due_date="2026-01-22"),
        _lab_lecture_item(title="Lab 2", start_date="2026-01-26", due_date="2026-01-27"),
        _lab_lecture_item(title="Lab 3", start_date="2026-01-28", due_date="2026-01-29"),
        _lab_practical_item(),
    ]
    return {
        "items": items,
        "metadata": {
            "course_id": "bio999-flat-cache",
            "source": "manual",
            "extraction_confidence": 0.9,
        },
    }


@pytest.fixture
def flattened_raw() -> str:
    return _load_flattened_fixture()


def test_normalize_preserves_lab_row_heads_and_date_tokens(flattened_raw):
    """normalize_text must not drop dated lab row heads before parse/preprocess."""
    normalized = normalize_text(flattened_raw)

    assert "Lab Schedule BIO999L Spring 2026" in normalized
    assert _count_lab_row_heads(normalized) >= _MIN_LAB_ROW_HEADS
    for token in _DATE_TOKENS:
        assert token in normalized


def test_preprocess_increases_lab_row_line_separation(flattened_raw):
    """preprocess should split adjacent flattened Lab N rows for parse prompts."""
    normalized = normalize_text(flattened_raw)
    preprocessed = preprocess_lab_schedule_rows(normalized)

    assert _count_lab_row_heads(preprocessed) == _count_lab_row_heads(normalized)
    assert _count_newline_prefixed_lab_rows(preprocessed) >= _count_newline_prefixed_lab_rows(
        normalized
    )
    assert "\nLab 6 MT 2/9-10" in preprocessed
    assert "\nLab 7 W TH 2/11-12" in preprocessed
    assert "Lab 6 MT 2/9-10 5 Exercise Epsilon: gram stain practice Lab 7" not in preprocessed
    assert "\nLab 20 MT 4/6-7" in preprocessed
    assert "\nLab 21 W TH 4/8-9" in preprocessed


def test_preprocess_splits_page_break_style_lab_thirteen(flattened_raw):
    """Page-break-like '12     Lab 14' should still allow a boundary before Lab 14."""
    normalized = normalize_text(flattened_raw)
    preprocessed = preprocess_lab_schedule_rows(normalized)

    assert "12     Lab 14 MT 3/9-10" in preprocessed or "\nLab 14 MT 3/9-10" in preprocessed


def test_preprocess_idempotent_on_flattened_fixture(flattened_raw):
    normalized = normalize_text(flattened_raw)
    once = preprocess_lab_schedule_rows(normalized)
    twice = preprocess_lab_schedule_rows(once)
    assert once == twice


def test_should_keep_item_retains_lab_lecture_and_practical_rows():
    """Filter layer should not drop valid lab lecture/exam rows returned by parse."""
    lecture = _lab_lecture_item(
        title="Lab 4",
        start_date="2026-02-02",
        due_date="2026-02-03",
    )
    practical = _lab_practical_item()

    assert should_keep_item(lecture) is True
    assert should_keep_item(practical) is True


def test_sanitize_preserves_term_year_for_numeric_section_dates(flattened_raw):
    """Sanitize may adjust years but should not clear M/D tokens present in source.

    Second date in a row (e.g. 1/21,22) is an alternate section meeting day, not a due
    date; this test only checks sanitizer does not strip known tokens from source.
    """
    normalized = normalize_text(flattened_raw)
    item = _lab_lecture_item(
        title="Lab 1",
        start_date="2026-01-21",
        due_date="2026-01-22",
    )
    result = sanitize_extracted_item_dates(
        copy.deepcopy(item),
        normalized,
        term="Spring 2026",
    )

    assert result["start_date"] == "2026-01-21"
    assert result["due_date"] == "2026-01-22"


@patch("main.parse", return_value=_parse_result_many_labs())
def test_unchanged_flattened_ingest_replays_cache_without_second_parse(mock_parse):
    """Unchanged source text must skip parse (syllabus_changed=false, one parse call)."""
    db = _make_session()
    course = Course(
        canvas_course_id="bio999-flat-cache",
        course_name="Bio999 Flat Cache",
        term="Spring 2026",
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    text = _load_flattened_fixture()
    first = ingest_syllabus_text(
        db=db,
        course=course,
        course_id="bio999-flat-cache",
        course_name="Bio999 Flat Cache",
        final_text=text,
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier="bio999-flat-cache",
        sync_to_notion=False,
        parse_source="manual",
    )
    second = ingest_syllabus_text(
        db=db,
        course=course,
        course_id="bio999-flat-cache",
        course_name="Bio999 Flat Cache",
        final_text=text,
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier="bio999-flat-cache",
        sync_to_notion=False,
        parse_source="manual",
    )

    assert first["changed"] is True
    assert first["sources"]["syllabus_changed"] is True
    assert len(first["items"]) == 4

    assert second["changed"] is False
    assert second["sources"]["syllabus_changed"] is False
    assert second["snapshot_id"] == first["snapshot_id"]
    assert len(second["items"]) == 4
    mock_parse.assert_called_once()

    db_items = db.query(Item).filter_by(snapshot_id=first["snapshot_id"]).all()
    assert len(db_items) == 4
