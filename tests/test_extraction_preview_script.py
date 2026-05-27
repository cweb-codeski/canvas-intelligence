import io
import subprocess
import sys
from pathlib import Path

from docx import Document

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "preview_manual_extraction.py"


def _run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _minimal_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buffer)
    return buffer.getvalue()


def test_txt_preview_includes_extracted_and_normalized(tmp_path: Path):
    syllabus = tmp_path / "preview.txt"
    syllabus.write_text("Homework 1 due Friday\n", encoding="utf-8")

    result = _run_script(str(syllabus))

    assert result.returncode == 0, result.stderr
    assert "=== EXTRACTED TEXT ===" in result.stdout
    assert "=== NORMALIZED TEXT ===" in result.stdout
    assert "Homework 1 due Friday" in result.stdout


def test_normalized_only_omits_extracted_section(tmp_path: Path):
    syllabus = tmp_path / "preview.txt"
    syllabus.write_text("Lab session on Tuesday\n", encoding="utf-8")

    result = _run_script(str(syllabus), "--normalized-only")

    assert result.returncode == 0, result.stderr
    assert "=== EXTRACTED TEXT ===" not in result.stdout
    assert "Lab session on Tuesday" in result.stdout


def test_output_flag_writes_file(tmp_path: Path):
    syllabus = tmp_path / "preview.txt"
    syllabus.write_text("Reading chapter 3\n", encoding="utf-8")
    out_file = tmp_path / "extracted.preview.txt"

    result = _run_script(str(syllabus), "--output", str(out_file))

    assert result.returncode == 0, result.stderr
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "=== EXTRACTED TEXT ===" in content
    assert "Reading chapter 3" in content


def test_docx_preview_exits_zero(tmp_path: Path):
    docx_path = tmp_path / "preview.docx"
    docx_path.write_bytes(_minimal_docx_bytes("Syllabus paragraph from docx"))

    result = _run_script(str(docx_path))

    assert result.returncode == 0, result.stderr
    assert "Syllabus paragraph from docx" in result.stdout
