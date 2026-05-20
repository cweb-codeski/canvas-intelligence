from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from db import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    canvas_course_id = Column(String, unique=True, index=True, nullable=False)
    course_code = Column(String, nullable=True)
    course_name = Column(String, nullable=True)
    term = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)

    # syllabus_body, page, file, assignment_feed, modules
    source_type = Column(String, nullable=False)
    # page title, filename, etc.
    source_name = Column(String, nullable=True)
    # Canvas page URL slug, file_id, assignment_id
    source_identifier = Column(String, nullable=True)
    content_hash = Column(String, nullable=False, index=True)
    normalized_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    snapshot_id = Column(Integer, ForeignKey("source_snapshots.id"), nullable=False, index=True)

    item_type = Column(String, nullable=False, index=True)  
    # exam, assignment, reading, lecture_topic

    subtype = Column(String, nullable=True)
    # midterm, final, quiz, homework, lab, discussion, chapter_reading, etc.

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)

    start_date = Column(String, nullable=True)
    due_date = Column(String, nullable=True)

    item_hash = Column(String, nullable=False, index=True)
    external_id = Column(String, nullable=True, index=True)
    # Canvas assignment id, module item id, examID, etc.

    confidence = Column(Float, nullable=True)
    status = Column(String, nullable=True)  
    # active, removed, updated

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ExamDetail(Base):
    __tablename__ = "exam_details"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id"), unique=True, nullable=False)
    exam_number = Column(String, nullable=True)
    exam_format = Column(String, nullable=True)

class AssignmentDetail(Base):
    __tablename__ = "assignment_details"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id"), unique=True, nullable=False)
    points_possible = Column(Float, nullable=True)
    submission_type = Column(String, nullable=True)

class ReadingDetail(Base):
    __tablename__ = "reading_details"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id"), unique=True, nullable=False)
    chapter = Column(String, nullable=True)
    pages = Column(String, nullable=True)
    authors = Column(String, nullable=True)