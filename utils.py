import hashlib
import re


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


def hash_item(
    item_type: str,
    title: str,
    subtype: str = "",
    start_date: str = "",
    due_date: str = "",
    external_id: str = ""
) -> str:
    components = [
        normalize(item_type),
        normalize(title),
        normalize(subtype),
        normalize(start_date),
        normalize(due_date),
        normalize(external_id)
    ]

    combined = "|".join(components)

    return hashlib.sha256(combined.encode("utf-8")).hexdigest()