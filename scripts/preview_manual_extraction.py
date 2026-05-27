#!/usr/bin/env python3
"""Preview manual syllabus file extraction without parsing or persistence."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Satisfy main.py import-time check; this script does not call OpenAI.
os.environ.setdefault("OPENAI_API_KEY", "extraction-preview")

# Ensure repo root is on sys.path when run as scripts/preview_manual_extraction.py
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from main import extract_text_from_manual_upload  # noqa: E402
from utils import normalize_text  # noqa: E402

EXTRACTED_HEADER = "=== EXTRACTED TEXT ==="
NORMALIZED_HEADER = "=== NORMALIZED TEXT ==="


def build_output(extracted: str, *, normalized_only: bool) -> str:
    normalized = normalize_text(extracted)
    if normalized_only:
        return normalized
    parts = [EXTRACTED_HEADER, extracted, "", NORMALIZED_HEADER, normalized]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview text extracted from a manual syllabus file (.txt, .pdf, .docx).",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a local .txt, .pdf, or .docx file",
    )
    parser.add_argument(
        "--normalized-only",
        action="store_true",
        help="Print only normalized text (what main.parse would receive)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    args = parser.parse_args(argv)

    file_path = args.path
    if not file_path.is_file():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        return 1

    raw_bytes = file_path.read_bytes()
    try:
        extracted_text = extract_text_from_manual_upload(file_path.name, raw_bytes)
    except Exception as exc:
        print(f"Error: extraction failed: {exc}", file=sys.stderr)
        return 1

    extracted = extracted_text.strip()
    if not extracted:
        print("Error: extraction produced no text (empty after strip)", file=sys.stderr)
        return 1

    output = build_output(extracted, normalized_only=args.normalized_only)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        if not args.normalized_only:
            print(f"Wrote extraction preview to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
