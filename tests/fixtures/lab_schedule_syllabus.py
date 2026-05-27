from pathlib import Path

from utils import hash_item, hash_text, normalize_text

_FIXTURE_DIR = Path(__file__).resolve().parent
_TEXT_PATH = _FIXTURE_DIR / "lab_schedule_syllabus.txt"

COURSE_KEY = "lab-schedule-999l"
COURSE_TERM = "Spring 2026"

LAB_SCHEDULE_PARSE_RESULT = {
    "items": [
        {
            "item_type": "lecture",
            "title": "Lab 1",
            "subtype": "lab",
            "start_date": "2026-02-10",
            "due_date": "2026-02-11",
            "description": "Orientation and safety briefing",
            "location": None,
            "external_id": None,
            "confidence": 0.9,
        },
        {
            "item_type": "lecture",
            "title": "Lab 2",
            "subtype": "lab",
            "start_date": "2026-02-17",
            "due_date": "2026-02-18",
            "description": "Exercise 1: Pipetting basics",
            "location": None,
            "external_id": None,
            "confidence": 0.9,
        },
        {
            "item_type": "lecture",
            "title": "Lab 3",
            "subtype": "lab",
            "start_date": "2026-02-19",
            "due_date": "2026-02-20",
            "description": "Exercise 2: Gram stain 3A: Colony morphology notes",
            "location": None,
            "external_id": None,
            "confidence": 0.88,
        },
        {
            "item_type": "exam",
            "title": "Lab 13 — LAB PRACTICAL 1",
            "subtype": "lab_practical",
            "start_date": "2026-04-01",
            "due_date": "2026-04-02",
            "description": "LAB PRACTICAL 1",
            "location": None,
            "external_id": None,
            "confidence": 0.92,
        },
        {
            "item_type": "exam",
            "title": "Lab 27 — Lab Practical 2",
            "subtype": "lab_practical",
            "start_date": "2026-05-06",
            "due_date": "2026-05-07",
            "description": "Lab Practical 2 review stations",
            "location": None,
            "external_id": None,
            "confidence": 0.91,
        },
    ],
    "metadata": {
        "course_id": COURSE_KEY,
        "source": "manual",
        "extraction_confidence": 0.902,
    },
}

KEPT_ITEM_SPECS = [
    {
        "item_type": "lecture",
        "title": "Lab 1",
        "subtype": "lab",
        "start_date": "2026-02-10",
        "due_date": "2026-02-11",
        "confidence": 0.9,
    },
    {
        "item_type": "lecture",
        "title": "Lab 2",
        "subtype": "lab",
        "start_date": "2026-02-17",
        "due_date": "2026-02-18",
        "confidence": 0.9,
    },
    {
        "item_type": "lecture",
        "title": "Lab 3",
        "subtype": "lab",
        "start_date": "2026-02-19",
        "due_date": "2026-02-20",
        "confidence": 0.88,
    },
    {
        "item_type": "exam",
        "title": "Lab 13 — LAB PRACTICAL 1",
        "subtype": "lab_practical",
        "start_date": "2026-04-01",
        "due_date": "2026-04-02",
        "confidence": 0.92,
    },
    {
        "item_type": "exam",
        "title": "Lab 27 — Lab Practical 2",
        "subtype": "lab_practical",
        "start_date": "2026-05-06",
        "due_date": "2026-05-07",
        "confidence": 0.91,
    },
]


def load_lab_schedule_text() -> str:
    return _TEXT_PATH.read_text(encoding="utf-8")


def lab_schedule_content_hash() -> str:
    return hash_text(normalize_text(load_lab_schedule_text()))


def expected_item_hash(spec: dict) -> str:
    return hash_item(
        item_type=spec["item_type"],
        title=spec["title"],
        subtype=spec.get("subtype") or "",
        start_date=spec.get("start_date") or "",
        due_date=spec.get("due_date") or "",
        external_id=spec.get("external_id") or "",
    )
