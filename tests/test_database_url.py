import os
import subprocess
import sys
from pathlib import Path

import db

DEFAULT_DATABASE_URL = "sqlite:///./app.db"
_PYTEST_IMPORT_DB_NAME = "canvas-parser-pytest.db"


def test_pytest_uses_non_default_database_url():
    assert db.DATABASE_URL != DEFAULT_DATABASE_URL
    assert _PYTEST_IMPORT_DB_NAME in db.DATABASE_URL


def test_fresh_import_honors_database_url(tmp_path: Path):
    db_file = tmp_path / "fresh_import.db"
    database_url = f"sqlite:///{db_file.as_posix()}"
    project_root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    env["DATABASE_URL"] = database_url
    env.setdefault("OPENAI_API_KEY", "test-openai-key")
    env.setdefault("ENABLE_NOTION_SYNC", "false")

    code = """
import main
from sqlalchemy import inspect
from db import engine

tables = inspect(engine).get_table_names()
assert "courses" in tables, tables
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert db_file.exists()
    assert not (tmp_path / "app.db").exists()
