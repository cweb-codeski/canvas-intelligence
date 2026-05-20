import io
import json
import os
import re
from typing import List, Optional, Tuple

import requests
from docx import Document
from fastapi import Depends, FastAPI, HTTPException
from jsonschema import ValidationError, validate
from openai import OpenAI
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy.orm import Session

from db import Base, engine, get_db
from models import AssignmentDetail, Course, Item, SourceSnapshot
from notion import check_notion_config, create_notion_item
from utils import hash_item, hash_text, normalize_text

Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.get("/notion/status")
def notion_status():
    return check_notion_config()

# ----- Environment Validation -----
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY environment variable not set")
canvas_base_url = os.environ.get("CANVAS_BASE_URL")
canvas_token = os.environ.get("CANVAS_ACCESS_TOKEN")

if not canvas_base_url or not canvas_token:
    raise RuntimeError("Canvas environment variables not set")

REQUEST_TIMEOUT_SECONDS = 10

client = OpenAI(api_key=api_key)

# ----- Request Model -----
class ParseRequest(BaseModel):
    course_id: str
    source: str
    text: Optional[str] = None


class ManualSyllabusRequest(BaseModel):
    course_key: str
    course_name: Optional[str] = None
    term: Optional[str] = None
    text: str
    sync_to_notion: Optional[bool] = True

# ----- JSON Schema -----
ITEM_SCHEMA = {
    "type": "object",
    "required": ["items", "metadata"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item_type", "title", "confidence"],
                "properties": {
                    "item_type": {
                        "type": "string",
                        "enum": ["exam", "assignment", "reading", "lecture"]
                    },
                    "subtype": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "start_date": {
                        "type": ["string", "null"],
                        "pattern": r"^\d{4}-\d{2}-\d{2}$"
                    },
                    "due_date": {
                        "type": ["string", "null"],
                        "pattern": r"^\d{4}-\d{2}-\d{2}$"
                    },
                    "external_id": {"type": ["string", "null"]},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "details": {
                        "type": ["object", "null"]
                    }
                }
            }
        },
        "metadata": {
            "type": "object",
            "required": ["course_id", "source", "extraction_confidence"],
            "properties": {
                "course_id": {"type": "string"},
                "source": {"type": "string"},
                "extraction_confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0
                }
            }
        }
    }
}

def get_or_create_course(db: Session, canvas_course_id: str, course_name: str) -> Course:
    course = (
        db.query(Course)
        .filter(Course.canvas_course_id == canvas_course_id)
        .first()
    )

    if course:
        if not course.course_name and course_name:
            course.course_name = course_name
            db.commit()
            db.refresh(course)
        return course

    course = Course(
        canvas_course_id=canvas_course_id,
        course_name=course_name
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course

def fetch_course_name(course_id: str):

    url = f"{canvas_base_url}/api/v1/courses/{course_id}"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code != 200:
        return course_id

    data = response.json()

    return data.get("course_code") or data.get("name") or course_id

def fetch_syllabus(course_id: str) -> str:
    url = f"{canvas_base_url}/api/v1/courses/{course_id}?include[]=syllabus_body"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Canvas API error: {response.text}"
        )

    data = response.json()

    syllabus = data.get("syllabus_body")

    if not syllabus:
        raise HTTPException(
            status_code=404,
            detail="No syllabus found for this course"
        )

    return syllabus

def fetch_paginated_course_pages(url: str, headers: dict, course_id: str) -> list:
    results = []

    while url:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code != 200:
            # If pages are disabled for this course, return empty list instead of failing
            if "disabled" in response.text.lower():
                print(f"[INFO] Pages disabled for course {course_id}. Skipping page lookup.")
                return []
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Canvas Pages API error: {response.text}"
            )

        data = response.json()

        if not isinstance(data, list):
            raise HTTPException(
                status_code=500,
                detail="Canvas Pages API returned unexpected data format"
            )

        results.extend(data)
        url = get_next_link(response)

    return results


def fetch_course_pages(course_id: str):
    url = f"{canvas_base_url}/api/v1/courses/{course_id}/pages"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    return fetch_paginated_course_pages(url, headers, course_id)

def get_next_link(response) -> Optional[str]:
    link_header = response.headers.get("Link")
    if not link_header:
        return None

    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">")
        if start != -1 and end != -1 and end > start:
            return section[start + 1:end]

    return None


def fetch_paginated_canvas_list(url: str, headers: dict) -> list:
    results = []

    while url:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Canvas Assignments API error: {response.text}"
            )

        data = response.json()

        if not isinstance(data, list):
            raise HTTPException(
                status_code=500,
                detail="Canvas Assignments API returned unexpected data format"
            )

        results.extend(data)
        url = get_next_link(response)

    return results


def fetch_canvas_assignments(course_id: str) -> list:
    url = f"{canvas_base_url}/api/v1/courses/{course_id}/assignments"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    return fetch_paginated_canvas_list(url, headers)

def fetch_page_body(course_id: str, page_url: str) -> str:
    url = f"{canvas_base_url}/api/v1/courses/{course_id}/pages/{page_url}"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Canvas Page Fetch Error: {response.text}"
        )

    data = response.json()

    body = data.get("body")

    if not body:
        raise HTTPException(
            status_code=404,
            detail="Page body not found"
        )

    return body

# ----- Added Helpers: HTML stripping + syllabus file parsing -----
def should_keep_item(parsed_item: dict) -> bool:
    item_type = (parsed_item.get("item_type") or "").lower()
    title = (parsed_item.get("title") or "").lower()
    description = (parsed_item.get("description") or "").lower()

    start_date = parsed_item.get("start_date")
    due_date = parsed_item.get("due_date")

    if item_type != "assignment":
        return True

    if start_date or due_date:
        return True

    text = f"{title} {description}"

    project_indicators = [
        "project",
        "paper",
        "literature review",
        "final project",
        "term paper"
    ]

    if any(indicator in text for indicator in project_indicators):
        return True

    bucket_indicators = [
        "weekly",
        "sessions",
        "quizzes",
        "write-ups",
        "writeups",
        "there will be",
        "will be organized",
        "2-",
        "several",
        "multiple"
    ]

    if any(indicator in text for indicator in bucket_indicators):
        return False

    return True

def strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<(script|style).*?>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_file_id_from_html(html: str) -> Optional[str]:
    """
    Tries to find a Canvas file id from common syllabus attachment links.
    Examples seen in Canvas HTML include /courses/<id>/files/<file_id> or /files/<file_id>/download
    """
    if not html:
        return None

    patterns = [
        r"/courses/\d+/files/(\d+)",
        r"/files/(\d+)/download",
        r"/files/(\d+)\?"
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            return m.group(1)
    return None

def fetch_file_metadata(file_id: str) -> dict:
    url = f"{canvas_base_url}/api/v1/files/{file_id}"
    headers = {"Authorization": f"Bearer {canvas_token}"}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Canvas File API error: {resp.text}",
        )
    return resp.json()

def download_file(file_url: str) -> bytes:
    headers = {"Authorization": f"Bearer {canvas_token}"}
    resp = requests.get(file_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Canvas File download error: {resp.text}",
        )
    return resp.content

def fetch_paginated_course_modules(url: str, headers: dict) -> list:
    results = []

    while url:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Canvas Modules API error: {response.text}"
            )

        data = response.json()

        if not isinstance(data, list):
            raise HTTPException(
                status_code=500,
                detail="Canvas Modules API returned unexpected data format"
            )

        results.extend(data)
        url = get_next_link(response)

    return results


def fetch_course_modules(course_id: str) -> list:
    url = f"{canvas_base_url}/api/v1/courses/{course_id}/modules?include[]=items&per_page=100"

    headers = {
        "Authorization": f"Bearer {canvas_token}"
    }

    return fetch_paginated_course_modules(url, headers)


def find_syllabus_file_in_modules(course_id: str) -> Optional[dict]:
    """
    Look through module items and try to find a syllabus-like file.
    Returns a dict with file_id, title, and module_name if found.
    """
    modules = fetch_course_modules(course_id)

    file_candidates = []

    for module in modules:
        module_name = module.get("name") or ""
        items = module.get("items") or []

        for item in items:
            item_type = (item.get("type") or "").lower()
            title = item.get("title") or ""

            if item_type != "file":
                continue

            score = 0
            lower_title = title.lower()
            lower_module = module_name.lower()

            if "syllabus" in lower_title:
                score += 10
            if "syllabus" in lower_module:
                score += 4
            if lower_title.endswith(".pdf"):
                score += 3
            if lower_title.endswith(".docx"):
                score += 2

            # Canvas module file items usually expose content_id for the underlying file
            file_id = item.get("content_id")
            if not file_id:
                continue

            file_candidates.append({
                "file_id": str(file_id),
                "title": title,
                "module_name": module_name,
                "score": score
            })

    if not file_candidates:
        return None

    file_candidates.sort(key=lambda x: x["score"], reverse=True)

    best = file_candidates[0]
    if best["score"] <= 0:
        return None

    print(
        f"[INFO] Found module syllabus candidate: "
        f"{best['title']} (module: {best['module_name']}, file_id: {best['file_id']})"
    )

    return best


def extract_text_from_pdf_bytes(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts: List[str] = []

    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        text = text.strip()
        if text:
            parts.append(text)

    return "\n\n".join(parts).strip()


def fetch_and_extract_canvas_file(file_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Downloads a Canvas file and extracts text if supported.
    Returns (text, source_name)
    """
    meta = fetch_file_metadata(file_id)
    filename = (meta.get("filename") or "").strip()
    lower_filename = filename.lower()
    mime = (meta.get("content-type") or "").lower()
    download_url = meta.get("url")

    if not download_url:
        return None, filename or None

    raw_bytes = download_file(download_url)

    if lower_filename.endswith(".docx") or "officedocument.wordprocessingml.document" in mime:
        return extract_text_from_docx_bytes(raw_bytes), filename

    if lower_filename.endswith(".pdf") or "pdf" in mime:
        return extract_text_from_pdf_bytes(raw_bytes), filename

    return None, filename or None

def extract_text_from_docx_bytes(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts: List[str] = []
    for p in doc.paragraphs:
        if p.text and p.text.strip():
            parts.append(p.text.strip())
    return "\n".join(parts).strip()

def complete_missing_exam_dates(course_id: str, exams: list) -> list:
    """
    If some exams have date == None, fetch schedule-like pages from Canvas and
    ask the LLM to fill ONLY missing dates when explicitly present.
    Returns the updated exams list (in-place updates).
    """

    # Only proceed if there's something missing
    missing = [e for e in exams if e.get("date") is None and e.get("examID")]
    if not missing:
        return exams

    # Fetch pages and pick schedule-like ones
    pages = fetch_course_pages(course_id)

    keywords = [
        "lecture schedule",
        "course schedule",
        "schedule",
        "calendar",
        "important dates",
        "timeline",
        "weekly"
    ]

    candidates = []
    for p in pages:
        title = (p.get("title") or "").lower()
        if any(k in title for k in keywords):
            candidates.append(p)

    # If nothing obvious, do nothing
    if not candidates:
        print(f"[INFO] No schedule-like pages found for course {course_id}.")
        return exams

    # Prefer more specific titles first
    def score(page: dict) -> int:
        t = (page.get("title") or "").lower()
        for i, k in enumerate(keywords):
            if k in t:
                return i
        return 999

    candidates.sort(key=score)

    # Pull up to 3 page bodies to control cost
    schedule_texts = []
    for page in candidates[:3]:
        try:
            body_html = fetch_page_body(course_id, page.get("url"))
            schedule_texts.append(strip_html(body_html))
        except HTTPException:
            continue

    combined_schedule_text = "\n\n".join([t for t in schedule_texts if t and t.strip()])
    if len(combined_schedule_text) < 200:
        print(f"[INFO] Schedule pages too small/unavailable for course {course_id}.")
        return exams

    # Build a targeted prompt: fill missing dates only
    # We pass the existing exams so the model doesn't invent new ones.
    prompt = f"""
You are given an existing list of exams (already extracted) and additional schedule text.

Task:
- Fill in missing exam dates ONLY when the schedule text explicitly provides a date for that exam.
- Do NOT invent dates.
- Do NOT change any fields except date.
- Only return updates for exams whose date is currently null.

Return ONLY valid JSON with this exact shape:
{{
  "updates": [
    {{
      "examID": "string",
      "date": "YYYY-MM-DD or null",
      "confidence": 0.0 to 1.0
    }}
  ]
}}

Existing exams JSON:
{json.dumps(exams, ensure_ascii=False)}

Schedule text:
{combined_schedule_text}
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        print(f"[WARN] OpenAI date-completion call failed for course {course_id}: {e}")
        return exams

    raw = resp.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] Date-completion returned invalid JSON for course {course_id}.")
        return exams

    updates = data.get("updates", [])
    if not isinstance(updates, list):
        return exams

    # Build quick lookup for merge
    by_exam_id = {e.get("examID"): e for e in exams if e.get("examID")}

    # Merge rule: only fill if currently None and confidence >= 0.7 and date matches YYYY-MM-DD
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    applied = 0
    for u in updates:
        if not isinstance(u, dict):
            continue
        exam_id = u.get("examID")
        new_date = u.get("date")
        conf = u.get("confidence", 0)

        if exam_id not in by_exam_id:
            continue

        target = by_exam_id[exam_id]

        if target.get("date") is not None:
            continue

        if not isinstance(conf, (int, float)) or conf < 0.7:
            continue

        if isinstance(new_date, str) and date_re.match(new_date):
            target["date"] = new_date
            applied += 1

    print(f"[INFO] Date-completion applied {applied} updates for course {course_id}.")
    return exams

def extract_page_slug_from_html(html: str) -> Optional[str]:
    """
    Looks for Canvas internal page links like /courses/<id>/pages/<slug>
    Returns the slug if found.
    """
    if not html:
        return None

    match = re.search(r"/courses/\d+/pages/([^\"'>]+)", html)
    if match:
        return match.group(1)

    return None

def clean_canvas_datetime_to_date(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None

    # Canvas typically returns ISO timestamps like 2026-04-12T23:59:00Z
    if len(value) >= 10:
        candidate = value[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
            return candidate

    return None


def infer_assignment_subtype(title: Optional[str], submission_types: Optional[list] = None) -> str:
    text = (title or "").strip().lower()
    submission_types = submission_types or []

    if "quiz" in text:
        return "quiz"
    if "discussion" in text:
        return "discussion"
    if "project" in text:
        return "project"
    if "paper" in text:
        return "paper"
    if "lab report" in text:
        return "lab_report"
    if "lab writeup" in text or "lab write-up" in text:
        return "lab_writeup"
    if "lab" in text:
        return "lab"
    if "worksheet" in text:
        return "worksheet"
    if "homework" in text or re.search(r"\bhw\b", text):
        return "homework"
    if "reflection" in text:
        return "reflection"

    if "discussion_topic" in submission_types:
        return "discussion"
    if "online_quiz" in submission_types:
        return "quiz"

    return "assignment"


def normalize_canvas_assignment(assignment: dict) -> dict:
    title = (assignment.get("name") or "").strip() or "Untitled Assignment"
    description_html = assignment.get("description") or ""
    description = strip_html(description_html) if description_html else None

    due_date = clean_canvas_datetime_to_date(assignment.get("due_at"))
    submission_types = assignment.get("submission_types") or []

    subtype = infer_assignment_subtype(title, submission_types)

    normalized = {
        "title": title,
        "item_type": "assignment",
        "subtype": subtype,
        "start_date": None,
        "due_date": due_date,
        "description": description,
        "location": None,
        "external_id": str(assignment.get("id")) if assignment.get("id") is not None else None,
        "confidence": 0.98,
        "details": {
            "points_possible": assignment.get("points_possible"),
            "submission_type": ", ".join(submission_types) if submission_types else None
        }
    }

    normalized["item_hash"] = hash_item(
        item_type=normalized["item_type"],
        title=normalized["title"],
        subtype=normalized["subtype"],
        start_date=normalized["start_date"],
        due_date=normalized["due_date"],
        external_id=normalized["external_id"]
    )

    return normalized


def build_assignment_feed_text(assignments: list) -> str:
    lines = []

    for assignment in assignments:
        name = assignment.get("name") or "Untitled Assignment"
        due_date = clean_canvas_datetime_to_date(assignment.get("due_at")) or "null"
        points_possible = assignment.get("points_possible")
        submission_types = assignment.get("submission_types") or []

        line = (
            f"id={assignment.get('id')} | "
            f"name={name} | "
            f"due_date={due_date} | "
            f"points_possible={points_possible} | "
            f"submission_types={','.join(submission_types)}"
        )
        lines.append(line)

    return "\n".join(lines)


SYLLABUS_SNAPSHOT_SOURCE_TYPES = (
    "syllabus_body",
    "page",
    "file",
    "modules",
    "manual_text",
)


def get_latest_syllabus_snapshot(db: Session, course_id: int):
    return (
        db.query(SourceSnapshot)
        .filter(
            SourceSnapshot.course_id == course_id,
            SourceSnapshot.source_type.in_(SYLLABUS_SNAPSHOT_SOURCE_TYPES),
        )
        .order_by(SourceSnapshot.created_at.desc())
        .first()
    )


def sync_items_to_notion(items: list, course_name: str) -> dict:
    notion_results = {
        "attempted": True,
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
    }

    for item in items:
        sync_result = create_notion_item(item, course_name)
        notion_results["results"].append(sync_result)

        status = sync_result.get("status")
        if status == "created":
            notion_results["created"] += 1
        elif status == "skipped":
            notion_results["skipped"] += 1
        else:
            notion_results["failed"] += 1

    return notion_results


def notion_sync_for_unchanged_syllabus(assignment_result: dict, course_name: str) -> dict:
    if assignment_result.get("changed", False):
        return sync_items_to_notion(assignment_result.get("items", []), course_name)

    return {
        "attempted": False,
        "reason": "syllabus unchanged; assignment feed handled separately",
    }


def _item_response_payload_from_db(item: Item) -> dict:
    return {
        "title": item.title,
        "item_type": item.item_type,
        "subtype": item.subtype,
        "start_date": item.start_date,
        "due_date": item.due_date,
        "description": item.description,
        "location": item.location,
        "external_id": item.external_id,
        "confidence": item.confidence,
        "item_hash": item.item_hash,
    }


def _item_response_payload_from_parsed(parsed_item: dict, item_hash_value: str) -> dict:
    return {
        "title": parsed_item.get("title"),
        "item_type": parsed_item.get("item_type"),
        "subtype": parsed_item.get("subtype"),
        "start_date": parsed_item.get("start_date"),
        "due_date": parsed_item.get("due_date"),
        "description": parsed_item.get("description"),
        "location": parsed_item.get("location"),
        "external_id": parsed_item.get("external_id"),
        "confidence": parsed_item.get("confidence"),
        "item_hash": item_hash_value,
    }


def ingest_syllabus_text(
    db: Session,
    course: Course,
    *,
    course_id: str,
    course_name: str,
    final_text: str,
    source_type: str,
    source_name: str,
    source_identifier: str,
    assignment_result: Optional[dict] = None,
    sync_to_notion: bool = True,
    parse_source: str = "canvas",
) -> dict:
    if assignment_result is None:
        assignment_result = {
            "changed": False,
            "items": [],
            "snapshot_id": None,
        }

    normalized = normalize_text(final_text)
    content_hash = hash_text(normalized)

    latest_snapshot = get_latest_syllabus_snapshot(db, course.id)

    if latest_snapshot and latest_snapshot.content_hash == content_hash:
        cached_items = (
            db.query(Item)
            .filter(Item.snapshot_id == latest_snapshot.id)
            .all()
        )

        response_items = [_item_response_payload_from_db(item) for item in cached_items]
        all_response_items = response_items + assignment_result.get("items", [])

        if sync_to_notion:
            notion_sync = notion_sync_for_unchanged_syllabus(assignment_result, course_name)
        else:
            notion_sync = {
                "attempted": False,
                "reason": "sync_to_notion disabled",
            }

        return {
            "course_id": course_id,
            "changed": assignment_result.get("changed", False),
            "snapshot_id": latest_snapshot.id,
            "assignment_snapshot_id": assignment_result.get("snapshot_id"),
            "items": all_response_items,
            "sources": {
                "syllabus_changed": False,
                "assignment_feed_changed": assignment_result.get("changed", False),
            },
            "notion_sync": notion_sync,
            "notion_config": check_notion_config(),
        }

    req = ParseRequest(
        course_id=course_id,
        source=parse_source,
        text=normalized,
    )

    result = parse(req)
    parsed_items = result.get("items", [])
    parsed_items = [item for item in parsed_items if should_keep_item(item)]

    new_snapshot = SourceSnapshot(
        course_id=course.id,
        source_type=source_type,
        source_name=source_name,
        source_identifier=source_identifier,
        content_hash=content_hash,
        normalized_text=normalized,
    )

    db.add(new_snapshot)
    db.commit()
    db.refresh(new_snapshot)

    response_items = []

    for parsed_item in parsed_items:
        item_hash_value = hash_item(
            item_type=parsed_item.get("item_type"),
            title=parsed_item.get("title"),
            subtype=parsed_item.get("subtype"),
            start_date=parsed_item.get("start_date"),
            due_date=parsed_item.get("due_date"),
            external_id=parsed_item.get("external_id"),
        )

        item = Item(
            course_id=course.id,
            snapshot_id=new_snapshot.id,
            item_type=parsed_item.get("item_type"),
            subtype=parsed_item.get("subtype"),
            title=parsed_item.get("title"),
            description=parsed_item.get("description"),
            location=parsed_item.get("location"),
            start_date=parsed_item.get("start_date"),
            due_date=parsed_item.get("due_date"),
            external_id=parsed_item.get("external_id"),
            item_hash=item_hash_value,
            confidence=parsed_item.get("confidence"),
            status="active",
        )

        db.add(item)
        response_items.append(
            _item_response_payload_from_parsed(parsed_item, item_hash_value)
        )

    db.commit()

    all_response_items = response_items + assignment_result.get("items", [])

    if sync_to_notion:
        notion_sync = sync_items_to_notion(all_response_items, course_name)
    else:
        notion_sync = {
            "attempted": False,
            "reason": "sync_to_notion disabled",
        }

    return {
        "course_id": course_id,
        "changed": True,
        "snapshot_id": new_snapshot.id,
        "assignment_snapshot_id": assignment_result.get("snapshot_id"),
        "items": all_response_items,
        "metadata": result.get("metadata"),
        "sources": {
            "syllabus_changed": True,
            "assignment_feed_changed": assignment_result.get("changed", False),
        },
        "notion_sync": notion_sync,
        "notion_config": check_notion_config(),
    }


def persist_canvas_assignment_items(
    db: Session,
    course: Course,
    course_id: str,
    assignments: list
):
    normalized_assignments = [
        normalize_canvas_assignment(a)
        for a in assignments
        if isinstance(a, dict) and (a.get("name") or a.get("id"))
    ]

    feed_text = build_assignment_feed_text(assignments)
    normalized_feed_text = normalize_text(feed_text)
    content_hash = hash_text(normalized_feed_text)

    latest_assignment_snapshot = (
        db.query(SourceSnapshot)
        .filter(
            SourceSnapshot.course_id == course.id,
            SourceSnapshot.source_type == "assignment_feed"
        )
        .order_by(SourceSnapshot.created_at.desc())
        .first()
    )

    if latest_assignment_snapshot and latest_assignment_snapshot.content_hash == content_hash:
        cached_items = (
            db.query(Item)
            .filter(Item.snapshot_id == latest_assignment_snapshot.id)
            .all()
        )

        response_items = []
        for item in cached_items:
            response_items.append({
                "title": item.title,
                "item_type": item.item_type,
                "subtype": item.subtype,
                "start_date": item.start_date,
                "due_date": item.due_date,
                "description": item.description,
                "location": item.location,
                "external_id": item.external_id,
                "confidence": item.confidence,
                "item_hash": item.item_hash
            })

        return {
            "changed": False,
            "snapshot_id": latest_assignment_snapshot.id,
            "items": response_items
        }

    new_snapshot = SourceSnapshot(
        course_id=course.id,
        source_type="assignment_feed",
        source_name="canvas_assignments",
        source_identifier=course_id,
        content_hash=content_hash,
        normalized_text=normalized_feed_text
    )

    db.add(new_snapshot)
    db.commit()
    db.refresh(new_snapshot)

    response_items = []

    for assignment_item in normalized_assignments:
        item = Item(
            course_id=course.id,
            snapshot_id=new_snapshot.id,
            item_type=assignment_item.get("item_type"),
            subtype=assignment_item.get("subtype"),
            title=assignment_item.get("title"),
            description=assignment_item.get("description"),
            location=assignment_item.get("location"),
            start_date=assignment_item.get("start_date"),
            due_date=assignment_item.get("due_date"),
            external_id=assignment_item.get("external_id"),
            item_hash=assignment_item.get("item_hash"),
            confidence=assignment_item.get("confidence"),
            status="active"
        )
        db.add(item)
        db.flush()

        details = assignment_item.get("details") or {}
        assignment_detail = AssignmentDetail(
            item_id=item.id,
            points_possible=details.get("points_possible"),
            submission_type=details.get("submission_type")
        )
        db.add(assignment_detail)

        response_items.append({
            "title": assignment_item.get("title"),
            "item_type": assignment_item.get("item_type"),
            "subtype": assignment_item.get("subtype"),
            "start_date": assignment_item.get("start_date"),
            "due_date": assignment_item.get("due_date"),
            "description": assignment_item.get("description"),
            "location": assignment_item.get("location"),
            "external_id": assignment_item.get("external_id"),
            "confidence": assignment_item.get("confidence"),
            "item_hash": assignment_item.get("item_hash")
        })

    db.commit()

    return {
        "changed": True,
        "snapshot_id": new_snapshot.id,
        "items": response_items
    }

# ----- Endpoint -----
@app.post("/parse")
def parse(req: ParseRequest):
    if not req.text:
        raise HTTPException(status_code=400, detail="No syllabus text provided")

    prompt = f"""
Extract structured academic items from the following Canvas course text.

Return ONLY valid JSON with a top-level key "items".

Allowed item_type values:
- exam
- assignment
- reading
- lecture

Each item should represent ONE concrete academic object.

For each item include:
- item_type
- subtype
- title
- description
- location
- start_date in YYYY-MM-DD format or null
- due_date in YYYY-MM-DD format or null
- external_id
- confidence (0.0 to 1.0)
- details (object, may be empty)

Definitions:
- exam: a discrete assessment event such as a midterm, final, quiz, practical, or timed test
- assignment: a concrete deliverable or submission such as homework, lab report, \
discussion, project, paper, or worksheet
- reading: a specific reading task tied to a lecture, week, module, or date
- lecture: a class meeting, lecture session, lab meeting, field trip, review session, \
discussion section, or guest lecture

Important extraction rules:
- Prefer concrete, singular, actionable items.
- Do NOT invent dates, titles, IDs, or links between items.
- Do NOT extract broad category summaries as standalone items.
- Do NOT extract recurring patterns unless the text gives a concrete instance.
- Do NOT extract generic course-description prose.

Lecture rules:
- If the syllabus provides dated or clearly scheduled lectures, labs, field trips, or \
sessions, extract each as its own lecture row.
- Use subtype values like lecture, lab, field_trip, review_session, discussion_section, \
or guest_lecture when appropriate.
- A field trip should be item_type "lecture" with subtype "field_trip".

Reading rules:
- Extract readings only when they are specific and meaningful.
- If a reading is clearly tied to a lecture, week, module, or class meeting, include that \
linkage in the description.
- Do NOT invent a due_date for a reading if none is explicitly given.

Assignment rules:
- Extract only concrete assignments, not buckets or categories.
- Good examples: "Lab Report 2", "Homework 3", "Discussion Post 4".
- Bad examples: "Lab Write-Ups", "Weekly reflections", "There will be five quizzes" unless \
the text gives a specific concrete instance.

Quiz rules:
- If a quiz is presented as a scheduled/timed assessment, classify it as item_type "exam" \
with subtype "quiz".
- If a quiz is presented as a normal due-date task or submission, classify it as \
item_type "assignment" with subtype "quiz".

Date rules:
- For exams and lectures, prefer start_date.
- For assignments, prefer due_date.
- For readings, use due_date only if explicitly stated; otherwise leave dates null.
- If there are no valid items, return {{"items": []}}.

- Do NOT extract recurring or plural assignment categories as one item.
- Do NOT extract items like "weekly quizzes", "peer-review sessions", or "lab write-ups" \
unless the text gives a single concrete instance or clearly defines one formal named \
semester-long assignment.
- If the text describes multiple future assignments without enumerating them, do not \
collapse them into one row.
- A semester-long named project may be extracted as one assignment if it is clearly a \
single deliverable.
- If an item is a practical, lab practical, or practical assessment, classify it as \
item_type "exam", not "lecture".
- Use subtype values like practical or lab_practical for those items.
- Do not classfiy practical exams or assessments as lecture items, even if they occur \
during a lab meeting
Text:
{req.text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

    raw = response.choices[0].message.content

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON from LLM: {str(e)}")

    if "items" not in parsed or not isinstance(parsed["items"], list):
        raise HTTPException(status_code=422, detail="LLM output missing 'items' array")

    items = parsed["items"]

    avg_conf = (
        sum(i.get("confidence", 0) for i in items) / len(items)
        if items else 0.0
    )

    final_output = {
        "items": items,
        "metadata": {
            "course_id": req.course_id,
            "source": req.source,
            "extraction_confidence": round(avg_conf, 3)
        }
    }

    try:
        validate(instance=final_output, schema=ITEM_SCHEMA)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return final_output

@app.post("/canvas/ingest/{course_id}")
def ingest_canvas_course(
    course_id: str,
    db: Session = Depends(get_db)
):
    course_name = fetch_course_name(course_id)
    course = get_or_create_course(db, course_id, course_name)

    assignments = fetch_canvas_assignments(course_id)
    print(f"[INFO] Fetched {len(assignments)} assignments from Canvas for course {course_id}.")

    assignment_result = persist_canvas_assignment_items(
        db=db,
        course=course,
        course_id=course_id,
        assignments=assignments
    )

    syllabus_html = None
    final_text = None
    syllabus_source_type = None
    syllabus_source_name = None
    syllabus_source_identifier = None

    # Step 1: Try default syllabus_body
    try:
        syllabus_html = fetch_syllabus(course_id)
    except HTTPException:
        syllabus_html = None
    if syllabus_html and len(strip_html(syllabus_html)) >= 50:
        syllabus_source_type = "syllabus_body"
        syllabus_source_name = "course_syllabus_body"
        syllabus_source_identifier = course_id

    # If syllabus_body contains a link to another Canvas page, follow it
    linked_page_slug = extract_page_slug_from_html(syllabus_html)

    if linked_page_slug:
        try:
            print(f"[INFO] Found linked syllabus page: {linked_page_slug}")
            syllabus_html = fetch_page_body(course_id, linked_page_slug)
            if syllabus_html and len(strip_html(syllabus_html)) >= 50:
                syllabus_source_type = "page"
                syllabus_source_name = "linked_syllabus_page"
                syllabus_source_identifier = linked_page_slug
        except HTTPException:
            pass

    # Step 2: If syllabus_body is empty or too small, try attached file from syllabus HTML
    if not syllabus_html or len(strip_html(syllabus_html)) < 200:
        file_id = extract_file_id_from_html(syllabus_html or "")

        if file_id:
            extracted_text, source_name = fetch_and_extract_canvas_file(file_id)
            if extracted_text and extracted_text.strip():
                print(f"[INFO] Extracted syllabus text from attached file: {source_name}")
                final_text = extracted_text
                syllabus_source_type = "file"
                syllabus_source_name = source_name or "attached_syllabus_file"
                syllabus_source_identifier = str(file_id)

    # Step 3: If still nothing, try Canvas Pages
    if final_text is None and (not syllabus_html or len(strip_html(syllabus_html)) < 500):
        pages = fetch_course_pages(course_id)

        syllabus_page = None
        for page in pages:
            title = (page.get("title") or "").lower()
            if "syllabus" in title:
                syllabus_page = page
                break

        if syllabus_page:
            page_url = syllabus_page.get("url")
            syllabus_html = fetch_page_body(course_id, page_url)
            if syllabus_html and len(strip_html(syllabus_html)) >= 50:
                syllabus_source_type = "page"
                syllabus_source_name = syllabus_page.get("title") or "syllabus_page"
                syllabus_source_identifier = page_url

    # Step 4: If still nothing, try Modules for a syllabus-like file
    if final_text is None and (not syllabus_html or len(strip_html(syllabus_html)) < 500):
        module_file = find_syllabus_file_in_modules(course_id)

        if module_file:
            extracted_text, source_name = fetch_and_extract_canvas_file(module_file["file_id"])
            if extracted_text and extracted_text.strip():
                print(
                    f"[INFO] Extracted syllabus text from module file: "
                    f"{source_name} (module: {module_file['module_name']})"
                )
                final_text = extracted_text
                syllabus_source_type = "modules"
                syllabus_source_name = source_name or module_file["title"] or "module_syllabus_file"
                syllabus_source_identifier = str(module_file["file_id"])


    # Final failure
    if final_text is None and (not syllabus_html or len(strip_html(syllabus_html)) < 50):
        raise HTTPException(
            status_code=404,
            detail="No usable syllabus found in syllabus_body, pages, or module files"
        )

    # Prepare final text
    if final_text is None:
        final_text = strip_html(syllabus_html)

    return ingest_syllabus_text(
        db=db,
        course=course,
        course_id=course_id,
        course_name=course_name,
        final_text=final_text,
        source_type=syllabus_source_type or "syllabus_body",
        source_name=syllabus_source_name or "syllabus",
        source_identifier=syllabus_source_identifier or course_id,
        assignment_result=assignment_result,
        sync_to_notion=True,
        parse_source="canvas",
    )


@app.post("/manual/syllabus")
def ingest_manual_syllabus(
    req: ManualSyllabusRequest,
    db: Session = Depends(get_db),
):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No syllabus text provided")

    course_name = req.course_name or req.course_key
    course = get_or_create_course(db, req.course_key, course_name)

    if req.term:
        course.term = req.term
        db.commit()
        db.refresh(course)

    sync_to_notion = True if req.sync_to_notion is None else req.sync_to_notion

    return ingest_syllabus_text(
        db=db,
        course=course,
        course_id=req.course_key,
        course_name=course_name,
        final_text=text,
        source_type="manual_text",
        source_name="manual_paste",
        source_identifier=req.course_key,
        sync_to_notion=sync_to_notion,
        parse_source="manual",
    )

