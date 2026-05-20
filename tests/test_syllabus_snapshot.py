import os
from datetime import datetime, timedelta

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CANVAS_BASE_URL", "https://example.instructure.com")
os.environ.setdefault("CANVAS_ACCESS_TOKEN", "test-canvas-token")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from models import Course, SourceSnapshot
from main import SYLLABUS_SNAPSHOT_SOURCE_TYPES, get_latest_syllabus_snapshot


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _add_snapshot(db, course, *, source_type, content_hash, created_at):
    snapshot = SourceSnapshot(
        course_id=course.id,
        source_type=source_type,
        source_name=source_type,
        source_identifier="test",
        content_hash=content_hash,
        normalized_text="text",
        created_at=created_at,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def test_syllabus_snapshot_types_exclude_assignment_feed():
    assert "assignment_feed" not in SYLLABUS_SNAPSHOT_SOURCE_TYPES
    assert set(SYLLABUS_SNAPSHOT_SOURCE_TYPES) == {
        "syllabus_body",
        "page",
        "file",
        "modules",
    }


def test_get_latest_syllabus_snapshot_ignores_newer_assignment_feed():
    db = _make_session()
    course = Course(canvas_course_id="101", course_name="Test Course")
    db.add(course)
    db.commit()
    db.refresh(course)

    base_time = datetime(2026, 1, 1, 12, 0, 0)
    syllabus_snapshot = _add_snapshot(
        db,
        course,
        source_type="syllabus_body",
        content_hash="syllabus-hash-aaa",
        created_at=base_time,
    )
    _add_snapshot(
        db,
        course,
        source_type="assignment_feed",
        content_hash="assignment-feed-hash-bbb",
        created_at=base_time + timedelta(hours=1),
    )

    latest = get_latest_syllabus_snapshot(db, course.id)

    assert latest is not None
    assert latest.id == syllabus_snapshot.id
    assert latest.source_type == "syllabus_body"
    assert latest.content_hash == "syllabus-hash-aaa"


def test_get_latest_syllabus_snapshot_returns_newest_syllabus_like_type():
    db = _make_session()
    course = Course(canvas_course_id="102", course_name="Test Course 2")
    db.add(course)
    db.commit()
    db.refresh(course)

    base_time = datetime(2026, 2, 1, 12, 0, 0)
    _add_snapshot(
        db,
        course,
        source_type="page",
        content_hash="page-hash",
        created_at=base_time,
    )
    modules_snapshot = _add_snapshot(
        db,
        course,
        source_type="modules",
        content_hash="modules-hash",
        created_at=base_time + timedelta(hours=2),
    )

    latest = get_latest_syllabus_snapshot(db, course.id)

    assert latest is not None
    assert latest.id == modules_snapshot.id
    assert latest.source_type == "modules"


def test_get_latest_syllabus_snapshot_none_when_only_assignment_feed_exists():
    db = _make_session()
    course = Course(canvas_course_id="103", course_name="Test Course 3")
    db.add(course)
    db.commit()
    db.refresh(course)

    _add_snapshot(
        db,
        course,
        source_type="assignment_feed",
        content_hash="assignment-only-hash",
        created_at=datetime(2026, 3, 1, 12, 0, 0),
    )

    assert get_latest_syllabus_snapshot(db, course.id) is None
