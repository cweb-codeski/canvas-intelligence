import hashlib

from utils import hash_item, hash_text, normalize, normalize_text


def test_normalize_text_empty():
    assert normalize_text("") == ""


def test_normalize_text_crlf_to_lf():
    assert normalize_text("line one\r\nline two") == "line one\nline two"


def test_normalize_text_strips_trailing_whitespace_per_line():
    assert normalize_text("hello   \nworld  ") == "hello\nworld"


def test_normalize_text_collapses_excessive_blank_lines():
    assert normalize_text("a\n\n\n\nb") == "a\n\nb"


def test_normalize_text_strips_outer_whitespace():
    assert normalize_text("  hi  ") == "hi"


def test_hash_text_empty():
    expected = hashlib.sha256(b"").hexdigest()
    assert hash_text("") == expected


def test_hash_text_deterministic():
    text = "stable input"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert hash_text(text) == expected
    assert hash_text(text) == hash_text(text)


def test_hash_text_differs_for_different_inputs():
    assert hash_text("alpha") != hash_text("beta")


def test_normalize_empty():
    assert normalize("") == ""


def test_normalize_strip_and_lower():
    assert normalize("  Hello World  ") == "hello world"


def test_hash_item_empty_optional_fields():
    combined = "assignment|hw 1||||"
    expected = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    assert hash_item("Assignment", "HW 1") == expected


def test_hash_item_all_fields():
    combined = "reading|chapter 1|textbook|2026-01-01|2026-01-15|canvas-42"
    expected = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    assert hash_item(
        "Reading",
        "Chapter 1",
        subtype="Textbook",
        start_date="2026-01-01",
        due_date="2026-01-15",
        external_id="canvas-42",
    ) == expected


def test_hash_item_case_insensitive_components():
    assert hash_item("Assignment", "Title") == hash_item("assignment", "title")


def test_hash_item_whitespace_insensitive_components():
    assert hash_item("  Assignment  ", "  Title  ") == hash_item("assignment", "title")


def test_hash_item_differs_when_external_id_differs():
    base = hash_item("assignment", "hw 1")
    other = hash_item("assignment", "hw 1", external_id="99")
    assert base != other
