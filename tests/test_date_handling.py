from utils import (
    extract_term_year,
    has_relative_date_language,
    sanitize_extracted_item_dates,
)


def test_extract_term_year_from_fall_2026():
    assert extract_term_year("Fall 2026") == 2026


def test_month_day_with_term_normalizes_to_term_year():
    source = "Exam on September 12. Midterm on October 15."
    item = {
        "title": "Midterm",
        "description": "",
        "start_date": "2023-09-12",
        "due_date": None,
    }

    result = sanitize_extracted_item_dates(item, source, term="Fall 2026")

    assert result["start_date"] == "2026-09-12"


def test_month_day_without_term_clears_invented_year():
    source = "Exam on September 12. Final on December 10."
    item = {
        "title": "Midterm",
        "description": "",
        "start_date": "2023-09-12",
        "due_date": "2023-12-10",
    }

    result = sanitize_extracted_item_dates(item, source, term=None)

    assert result["start_date"] is None
    assert result["due_date"] is None


def test_relative_friday_without_context_clears_invented_date():
    source = "Submit the lab report by Friday."
    item = {
        "title": "Lab report",
        "description": "Due Friday",
        "start_date": None,
        "due_date": "2023-09-15",
    }

    result = sanitize_extracted_item_dates(item, source, term=None)

    assert result["due_date"] is None


def test_explicit_year_in_source_is_preserved():
    source = "The final exam is on December 10, 2025."
    item = {
        "title": "Final exam",
        "description": "",
        "start_date": "2025-12-10",
        "due_date": None,
    }

    result = sanitize_extracted_item_dates(item, source, term=None)

    assert result["start_date"] == "2025-12-10"


def test_has_relative_date_language_detects_friday():
    assert has_relative_date_language("Submit by Friday")
    assert not has_relative_date_language("Exam on September 12, 2026")
