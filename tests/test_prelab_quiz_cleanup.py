import copy
import importlib.util
from pathlib import Path

from utils import (
    cleanup_standalone_undated_prelab_quizzes,
    is_standalone_undated_prelab_quiz_item,
    parse_lab_prelab_quiz_map,
)

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_BIO999_FLAT_PATH = _FIXTURE_DIR / "bio999_flattened_lab_schedule.txt"
_BIOL350_FIXTURE_PATH = _FIXTURE_DIR / "biol350_prelab_quiz_cleanup.py"
_spec = importlib.util.spec_from_file_location("biol350_prelab_quiz_cleanup", _BIOL350_FIXTURE_PATH)
biol350_fixture = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(biol350_fixture)


def _undated_prelab_quiz(title: str) -> dict:
    return {
        "title": title,
        "item_type": "exam",
        "subtype": "quiz",
        "start_date": None,
        "due_date": None,
        "description": "Pre-lab quiz for Lab 2.",
        "confidence": 0.95,
    }


def test_is_standalone_undated_prelab_quiz_matches_title_variants():
    assert is_standalone_undated_prelab_quiz_item(_undated_prelab_quiz("Pre-lab Quiz 1"))
    assert is_standalone_undated_prelab_quiz_item(_undated_prelab_quiz("Pre Lab Quiz 2"))
    assert is_standalone_undated_prelab_quiz_item(_undated_prelab_quiz("Prelab Quiz 3"))


def test_cleanup_removes_undated_prelab_quiz_item():
    items = [
        _undated_prelab_quiz("Pre-lab Quiz 1"),
        {
            "title": "Lab 2",
            "item_type": "lecture",
            "subtype": "lab",
            "start_date": "2026-01-26",
            "due_date": None,
            "description": "Brightfield microscopy.",
        },
    ]

    cleaned = cleanup_standalone_undated_prelab_quizzes(items, biol350_fixture.LAB_SCHEDULE_SOURCE)

    titles = [item["title"] for item in cleaned]
    assert "Pre-lab Quiz 1" not in titles
    assert "Lab 2" in titles


def test_cleanup_preserves_dated_prelab_quiz_item():
    dated_quiz = _undated_prelab_quiz("Pre-lab Quiz 4")
    dated_quiz["due_date"] = "2026-02-03"

    cleaned = cleanup_standalone_undated_prelab_quizzes(
        [dated_quiz],
        biol350_fixture.LAB_SCHEDULE_SOURCE,
    )

    assert len(cleaned) == 1
    assert cleaned[0]["title"] == "Pre-lab Quiz 4"
    assert cleaned[0]["due_date"] == "2026-02-03"


def test_cleanup_preserves_undated_prelab_quiz_with_due_language():
    due_language_quiz = _undated_prelab_quiz("Pre-lab Quiz 5")
    due_language_quiz["description"] = "Submit by Friday before Lab 6."

    cleaned = cleanup_standalone_undated_prelab_quizzes(
        [due_language_quiz],
        biol350_fixture.LAB_SCHEDULE_SOURCE,
    )

    assert len(cleaned) == 1
    assert cleaned[0]["title"] == "Pre-lab Quiz 5"


def test_cleanup_preserves_lab_and_practical_items():
    items = copy.deepcopy(biol350_fixture.PARSED_ITEMS_BEFORE_CLEANUP)

    cleaned = cleanup_standalone_undated_prelab_quizzes(items, biol350_fixture.LAB_SCHEDULE_SOURCE)

    titles = {item["title"] for item in cleaned}
    assert "Lab 1" in titles
    assert "Lab 2" in titles
    assert "Lab 3" in titles
    assert "Lab 13" in titles
    assert "Lab 19" in titles
    assert "Lab 20" in titles
    assert "Lab 27" in titles
    assert "Lab Practical 1" in titles
    assert "Lab Practical 2" in titles


def test_biol350_style_cleanup_has_zero_standalone_undated_prelab_quizzes():
    items = copy.deepcopy(biol350_fixture.PARSED_ITEMS_BEFORE_CLEANUP)

    cleaned = cleanup_standalone_undated_prelab_quizzes(items, biol350_fixture.LAB_SCHEDULE_SOURCE)

    standalone_undated = [item for item in cleaned if is_standalone_undated_prelab_quiz_item(item)]
    assert standalone_undated == []


def test_cleanup_enriches_parent_lab_descriptions_with_source_quiz_numbers():
    items = copy.deepcopy(biol350_fixture.PARSED_ITEMS_BEFORE_CLEANUP)

    cleaned = cleanup_standalone_undated_prelab_quizzes(items, biol350_fixture.LAB_SCHEDULE_SOURCE)

    lab_by_title = {item["title"]: item for item in cleaned}

    assert "Pre-lab quiz: none" in lab_by_title["Lab 1"]["description"]
    assert "Pre-lab quiz #: 1" in lab_by_title["Lab 2"]["description"]
    assert "Pre-lab quiz #: 2" in lab_by_title["Lab 3"]["description"]
    assert "Pre-lab quiz #: 10" in lab_by_title["Lab 13"]["description"]
    assert "pre-lab quiz" not in lab_by_title["Lab 19"]["description"].lower()
    assert "Pre-lab quiz #: 16" in lab_by_title["Lab 20"]["description"]


def test_parse_lab_prelab_quiz_map_reads_flattened_schedule_fixture():
    source = _BIO999_FLAT_PATH.read_text(encoding="utf-8")

    quiz_map = parse_lab_prelab_quiz_map(source)

    assert quiz_map[1] == "none"
    assert quiz_map[2] == "1"
    assert quiz_map[13] == "10"
    assert quiz_map[20] == "16"
    assert 19 not in quiz_map
    assert 27 not in quiz_map
