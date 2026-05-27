import hashlib
import re
from typing import Optional

ISO_DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})$")

MONTH_NAME_PATTERNS = {
    1: r"\bjanuary\b|\bjan\.?\b",
    2: r"\bfebruary\b|\bfeb\.?\b",
    3: r"\bmarch\b|\bmar\.?\b",
    4: r"\bapril\b|\bapr\.?\b",
    5: r"\bmay\b",
    6: r"\bjune\b|\bjun\.?\b",
    7: r"\bjuly\b|\bjul\.?\b",
    8: r"\baugust\b|\baug\.?\b",
    9: r"\bseptember\b|\bsept?\.?\b",
    10: r"\boctober\b|\boct\.?\b",
    11: r"\bnovember\b|\bnov\.?\b",
    12: r"\bdecember\b|\bdec\.?\b",
}

RELATIVE_DATE_PATTERNS = [
    r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)\b",
    r"\bthis\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:tomorrow|today)\b",
]

WEEKDAY_ONLY_RE = re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")

LAB_SCHEDULE_ANCHOR_RE = re.compile(r"\blab\s+schedule\b", re.IGNORECASE)

# Day tokens common in flattened lab schedule tables (not bare weekdays in prose).
_LAB_SCHEDULE_DAY_TOKENS = r"(?:WTh|W\s+TH|M\s+T|MT)"
_LAB_SCHEDULE_DATE_TOKEN = r"\d{1,2}/\d{1,2}(?:,\d{1,2}|-\d{1,2}|/\d{1,2})?"
_LAB_SCHEDULE_ROW_HEAD = (
    rf"\bLab\s+\d{{1,2}}\s+"
    rf"(?:{_LAB_SCHEDULE_DAY_TOKENS}\s+{_LAB_SCHEDULE_DATE_TOKEN}|{_LAB_SCHEDULE_DATE_TOKEN})"
)
LAB_SCHEDULE_ROW_HEAD_RE = re.compile(_LAB_SCHEDULE_ROW_HEAD)
LAB_SCHEDULE_ROW_BOUNDARY_RE = re.compile(
    rf"(?<=[^\n])\s+(?={_LAB_SCHEDULE_ROW_HEAD})",
)


def preprocess_lab_schedule_rows(text: str) -> str:
    """Insert newlines before flattened lab schedule rows for parse prompts only.

    Does not mutate stored syllabus text. Conservative: requires a Lab Schedule
    anchor and at least two dated Lab N rows in that region.
    """
    if not text:
        return text

    anchor_match = LAB_SCHEDULE_ANCHOR_RE.search(text)
    if not anchor_match:
        return text

    prefix = text[: anchor_match.start()]
    region = text[anchor_match.start() :]

    if len(LAB_SCHEDULE_ROW_HEAD_RE.findall(region)) < 2:
        return text

    processed_region = LAB_SCHEDULE_ROW_BOUNDARY_RE.sub("\n", region)
    return prefix + processed_region


def normalize_text(text: str) -> str:
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n")

    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in text.split("\n")]

    # Collapse excessive blank lines
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(value: str) -> str:
    if not value:
        return ""
    return value.strip().lower()


def extract_term_year(term: Optional[str]) -> Optional[int]:
    if not term:
        return None
    match = re.search(r"\b(20\d{2})\b", term)
    return int(match.group(1)) if match else None


def year_explicit_in_source(year: int, source_text: str) -> bool:
    return str(year) in (source_text or "")


def month_day_present_in_source(month: int, day: int, source_text: str) -> bool:
    if not source_text:
        return False

    text = source_text.lower()
    month_pattern = MONTH_NAME_PATTERNS.get(month)
    if not month_pattern or not re.search(month_pattern, text):
        return False

    day_pattern = rf"(?<!\d){day}(?!\d)"
    return re.search(day_pattern, text) is not None


def numeric_month_day_present_in_source(month: int, day: int, source_text: str) -> bool:
    """Match conservative M/D-style schedule tokens (not bare integers or labels like 3A)."""
    if not source_text or month < 1 or month > 12 or day < 1 or day > 31:
        return False

    patterns = [
        rf"(?<!\d){month}/{day}(?:,\d{{1,2}}|-\d{{1,2}}|/\d{{1,2}})?(?!\d)",
        rf"(?<!\d){month}/\d{{1,2}},{day}(?!\d)",
        rf"(?<!\d){month}/\d{{1,2}}-{day}(?!\d)",
        rf"(?<!\d){month}/\d{{1,2}}/{day}(?!\d)",
    ]
    return any(re.search(pattern, source_text) for pattern in patterns)


def calendar_day_present_in_source(month: int, day: int, source_text: str) -> bool:
    if month_day_present_in_source(month, day, source_text):
        return True
    return numeric_month_day_present_in_source(month, day, source_text)


def has_relative_date_language(*texts: str) -> bool:
    combined = " ".join(t for t in texts if t).lower()
    if not combined:
        return False

    if any(re.search(pattern, combined) for pattern in RELATIVE_DATE_PATTERNS):
        return True

    if WEEKDAY_ONLY_RE.search(combined):
        has_month = any(re.search(pattern, combined) for pattern in MONTH_NAME_PATTERNS.values())
        has_year = re.search(r"\b20\d{2}\b", combined) is not None
        if not has_month and not has_year:
            return True

    return False


def sanitize_extracted_item_dates(
    item: dict,
    source_text: str,
    term: Optional[str] = None,
) -> dict:
    term_year = extract_term_year(term)
    item_text = " ".join(
        [
            item.get("title") or "",
            item.get("description") or "",
        ]
    )

    for field in ("start_date", "due_date"):
        value = item.get(field)
        if not value:
            continue

        match = ISO_DATE_RE.match(value)
        if not match:
            item[field] = None
            continue

        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))

        if has_relative_date_language(source_text, item_text):
            if not calendar_day_present_in_source(month, day, source_text):
                item[field] = None
                continue

        if year_explicit_in_source(year, source_text):
            continue

        if term_year and calendar_day_present_in_source(month, day, source_text):
            item[field] = f"{term_year:04d}-{month:02d}-{day:02d}"
            continue

        item[field] = None

    return item


def hash_item(
    item_type: str,
    title: str,
    subtype: str = "",
    start_date: str = "",
    due_date: str = "",
    external_id: str = "",
) -> str:
    components = [
        normalize(item_type),
        normalize(title),
        normalize(subtype),
        normalize(start_date),
        normalize(due_date),
        normalize(external_id),
    ]

    combined = "|".join(components)

    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
