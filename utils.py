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


STANDALONE_PRELAB_QUIZ_TITLE_RE = re.compile(
    r"^pre-?\s*lab\s+quiz\s+\d+\b",
    re.IGNORECASE,
)

PRELAB_QUIZ_DUE_LANGUAGE_RE = re.compile(
    r"\b(?:"
    r"due|deadline|submit(?:ted|tal)?|submission|due\s+date|"
    r"open(?:s|ing)?(?:\s+(?:on|date))?|closes?|available\s+until|"
    r"complete\s+by|must\s+be\s+(?:completed|submitted)"
    r")\b",
    re.IGNORECASE,
)

PRELAB_QUIZ_METADATA_RE = re.compile(r"\bpre-?\s*lab\s+quiz\b", re.IGNORECASE)

NO_PRELAB_QUIZ_ROW_RE = re.compile(
    r"^no\s+(?:pre-?\s*lab|prep)\s+quiz\b",
    re.IGNORECASE,
)
LAB_PRACTICAL_ROW_START_RE = re.compile(r"^lab\s+practical\b", re.IGNORECASE)


def is_standalone_undated_prelab_quiz_item(item: dict) -> bool:
    title = (item.get("title") or "").strip()
    if not STANDALONE_PRELAB_QUIZ_TITLE_RE.match(title):
        return False

    if item.get("start_date") or item.get("due_date"):
        return False

    item_text = f"{item.get('title') or ''} {item.get('description') or ''}"
    if PRELAB_QUIZ_DUE_LANGUAGE_RE.search(item_text):
        return False

    return True


def _extract_prelab_quiz_from_row_tail(tail: str) -> Optional[str]:
    if not tail:
        return None

    normalized_tail = re.sub(r"\s+", " ", tail.strip())
    if not normalized_tail:
        return None

    if NO_PRELAB_QUIZ_ROW_RE.match(normalized_tail):
        return "none"

    if LAB_PRACTICAL_ROW_START_RE.match(normalized_tail):
        return None

    quiz_before_lab_practical = re.match(
        r"^(\d{1,2})\s+lab\s+practical\b",
        normalized_tail,
        re.IGNORECASE,
    )
    if quiz_before_lab_practical:
        return quiz_before_lab_practical.group(1)

    quiz_before_experiment = re.match(
        r"^(\d{1,2})\s+(\d{1,2}):",
        normalized_tail,
    )
    if quiz_before_experiment:
        return quiz_before_experiment.group(1)

    quiz_before_alphanumeric_experiment = re.match(
        r"^(\d{1,2})\s+\d{1,2}[A-Za-z]:",
        normalized_tail,
    )
    if quiz_before_alphanumeric_experiment:
        return quiz_before_alphanumeric_experiment.group(1)

    quiz_before_topic_number = re.match(
        r"^(\d{1,2})\s+(\d{1,2})\s+(?!continued\b)",
        normalized_tail,
        re.IGNORECASE,
    )
    if quiz_before_topic_number:
        return quiz_before_topic_number.group(1)

    quiz_before_continued_experiment = re.match(
        r"^(\d{1,2})\s+(\d{1,2})\s+continued\b",
        normalized_tail,
        re.IGNORECASE,
    )
    if quiz_before_continued_experiment:
        return quiz_before_continued_experiment.group(1)

    if re.match(r"^\d{1,2}\s+continued\b", normalized_tail, re.IGNORECASE):
        return None

    quiz_before_text_topic = re.match(
        r"^(\d{1,2})\s+(?!continued\b)(?:topic\b|[A-Za-z])",
        normalized_tail,
        re.IGNORECASE,
    )
    if quiz_before_text_topic:
        return quiz_before_text_topic.group(1)

    return None


def parse_lab_prelab_quiz_map(source_text: str) -> dict[int, str]:
    if not source_text:
        return {}

    if not LAB_SCHEDULE_ANCHOR_RE.search(source_text):
        return {}

    schedule_text = preprocess_lab_schedule_rows(source_text)
    anchor_match = LAB_SCHEDULE_ANCHOR_RE.search(schedule_text)
    if not anchor_match:
        return {}

    region = schedule_text[anchor_match.start() :]
    heads = list(LAB_SCHEDULE_ROW_HEAD_RE.finditer(region))
    if len(heads) < 2:
        return {}

    quiz_map: dict[int, str] = {}
    for index, match in enumerate(heads):
        lab_number_match = re.search(r"Lab\s+(\d{1,2})\b", match.group(), re.IGNORECASE)
        if not lab_number_match:
            continue

        lab_number = int(lab_number_match.group(1))
        tail_start = match.end()
        tail_end = heads[index + 1].start() if index + 1 < len(heads) else len(region)
        tail = region[tail_start:tail_end]
        quiz_value = _extract_prelab_quiz_from_row_tail(tail)
        if quiz_value is not None:
            quiz_map[lab_number] = quiz_value

    return quiz_map


def _prelab_quiz_metadata_phrase(quiz_value: str) -> str:
    if quiz_value == "none":
        return "Pre-lab quiz: none"
    return f"Pre-lab quiz #: {quiz_value}"


def enrich_lab_items_with_prelab_quiz_metadata(
    items: list[dict],
    quiz_map: dict[int, str],
) -> list[dict]:
    if not quiz_map:
        return items

    enriched_items: list[dict] = []
    for item in items:
        if (item.get("item_type") or "").lower() != "lecture":
            enriched_items.append(item)
            continue
        if (item.get("subtype") or "").lower() != "lab":
            enriched_items.append(item)
            continue

        title = (item.get("title") or "").strip()
        title_match = re.match(r"^Lab\s+(\d{1,2})\b", title, re.IGNORECASE)
        if not title_match:
            enriched_items.append(item)
            continue

        lab_number = int(title_match.group(1))
        quiz_value = quiz_map.get(lab_number)
        if quiz_value is None:
            enriched_items.append(item)
            continue

        description = item.get("description") or ""
        if PRELAB_QUIZ_METADATA_RE.search(description):
            enriched_items.append(item)
            continue

        metadata_phrase = _prelab_quiz_metadata_phrase(quiz_value)
        updated_item = dict(item)
        if description:
            updated_item["description"] = f"{description.rstrip('.')}. {metadata_phrase}."
        else:
            updated_item["description"] = f"{metadata_phrase}."
        enriched_items.append(updated_item)

    return enriched_items


def cleanup_standalone_undated_prelab_quizzes(
    items: list[dict],
    source_text: str,
) -> list[dict]:
    quiz_map = parse_lab_prelab_quiz_map(source_text)
    kept_items = [item for item in items if not is_standalone_undated_prelab_quiz_item(item)]
    return enrich_lab_items_with_prelab_quiz_metadata(kept_items, quiz_map)


# Shared due/deadline/submission anchor language (same pattern as pre-lab quiz cleanup).
DUE_ANCHOR_LANGUAGE_RE = PRELAB_QUIZ_DUE_LANGUAGE_RE

# Pop quizzes are unannounced by definition; an undated one with no due anchor is
# a grading-breakdown label, not a plannable event.
POP_QUIZ_TITLE_RE = re.compile(r"^pop\s+quiz\b", re.IGNORECASE)

# Phrases that strongly indicate a grading-policy / SLO / assessment-strategy
# artifact rather than a scheduled course event. Deliberately narrow: bare words
# like "quiz" or "reading" must never trigger suppression on their own.
POLICY_ARTIFACT_CONTEXT_RE = re.compile(
    r"(?:"
    r"\bgrading\s+(?:policy|policies|breakdown|weights?|scale)\b"
    r"|\bgrade\s+breakdown\b"
    r"|\bassessment\s+strateg(?:y|ies)\b"
    r"|\b(?:student\s+)?learning\s+outcomes?\b"
    r"|\bSLOs?\b"
    r"|\boutcomes?\s+\d+\b"
    r")",
    re.IGNORECASE,
)

# Subtypes that represent real assessments students must plan for even when the
# syllabus only mentions them in grading text without a date.
_NEVER_SUPPRESS_SUBTYPES = {"midterm", "final"}


def is_undated_policy_artifact_item(item: dict) -> bool:
    """True only for undated grading-policy/SLO/assessment-strategy artifacts.

    Conservative by design: never matches items with a start_date or due_date,
    items with due/deadline/submission language, or midterm/final subtypes.
    """
    if item.get("start_date") or item.get("due_date"):
        return False

    if (item.get("subtype") or "").strip().lower() in _NEVER_SUPPRESS_SUBTYPES:
        return False

    item_text = " ".join(
        part for part in (item.get("title"), item.get("description"), item.get("location")) if part
    )
    if DUE_ANCHOR_LANGUAGE_RE.search(item_text):
        return False

    if POP_QUIZ_TITLE_RE.match((item.get("title") or "").strip()):
        return True

    return POLICY_ARTIFACT_CONTEXT_RE.search(item_text) is not None


def cleanup_undated_policy_artifact_items(items: list[dict]) -> list[dict]:
    return [item for item in items if not is_undated_policy_artifact_item(item)]


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
