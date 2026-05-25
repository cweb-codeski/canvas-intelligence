from pathlib import Path

from utils import hash_item, hash_text, normalize_text

_FIXTURE_DIR = Path(__file__).resolve().parent
_GOLDEN_TEXT_PATH = _FIXTURE_DIR / "golden_syllabus.txt"

COURSE_KEY = "golden-syllabus-101"
COURSE_TERM = "Spring 2026"

GOLDEN_PARSE_RESULT = {
    "items": [
        {
            "item_type": "assignment",
            "title": "Homework 1",
            "subtype": "homework",
            "start_date": None,
            "due_date": "2026-02-10",
            "description": None,
            "location": None,
            "external_id": None,
            "confidence": 0.95,
        },
        {
            "item_type": "exam",
            "title": "Midterm Exam",
            "subtype": "midterm",
            "start_date": "2026-03-15",
            "due_date": None,
            "description": None,
            "location": None,
            "external_id": None,
            "confidence": 0.92,
        },
        {
            "item_type": "reading",
            "title": "Chapter 3",
            "subtype": "chapter_reading",
            "start_date": None,
            "due_date": "2026-01-20",
            "description": None,
            "location": None,
            "external_id": None,
            "confidence": 0.88,
        },
        {
            "item_type": "assignment",
            "title": "Weekly quiz sessions",
            "subtype": "quiz",
            "start_date": None,
            "due_date": None,
            "description": "Weekly quiz sessions with no fixed due dates",
            "location": None,
            "external_id": None,
            "confidence": 0.7,
        },
    ],
    "metadata": {
        "course_id": COURSE_KEY,
        "source": "manual",
        "extraction_confidence": 0.887,
    },
}

FILTERED_ITEM_TITLE = "Weekly quiz sessions"

KEPT_ITEM_SPECS = [
    {
        "item_type": "assignment",
        "title": "Homework 1",
        "subtype": "homework",
        "start_date": None,
        "due_date": "2026-02-10",
        "confidence": 0.95,
    },
    {
        "item_type": "exam",
        "title": "Midterm Exam",
        "subtype": "midterm",
        "start_date": "2026-03-15",
        "due_date": None,
        "confidence": 0.92,
    },
    {
        "item_type": "reading",
        "title": "Chapter 3",
        "subtype": "chapter_reading",
        "start_date": None,
        "due_date": "2026-01-20",
        "confidence": 0.88,
    },
]


def load_golden_text() -> str:
    return _GOLDEN_TEXT_PATH.read_text(encoding="utf-8")


def golden_content_hash() -> str:
    return hash_text(normalize_text(load_golden_text()))


def expected_item_hash(spec: dict) -> str:
    return hash_item(
        item_type=spec["item_type"],
        title=spec["title"],
        subtype=spec.get("subtype") or "",
        start_date=spec.get("start_date") or "",
        due_date=spec.get("due_date") or "",
        external_id=spec.get("external_id") or "",
    )
