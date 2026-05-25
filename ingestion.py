from typing import Optional

from sqlalchemy.orm import Session

from models import Course, Item, SourceSnapshot
from utils import hash_item, hash_text, normalize_text

SYLLABUS_SNAPSHOT_SOURCE_TYPES = (
    "syllabus_body",
    "page",
    "file",
    "modules",
    "manual_text",
    "manual_file",
)


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

    project_indicators = ["project", "paper", "literature review", "final project", "term paper"]

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
        "multiple",
    ]

    if any(indicator in text for indicator in bucket_indicators):
        return False

    return True


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
    import main

    notion_results = {
        "attempted": True,
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
    }

    for item in items:
        sync_result = main.create_notion_item(item, course_name)
        notion_results["results"].append(sync_result)

        status = sync_result.get("status")
        if status == "created":
            notion_results["created"] += 1
        elif status == "skipped":
            notion_results["skipped"] += 1
        else:
            notion_results["failed"] += 1

    return notion_results


def notion_config_for_response(sync_to_notion: bool) -> dict:
    if not sync_to_notion:
        return {
            "status": "not_checked",
            "reason": "sync_to_notion disabled",
        }

    import main

    return main.check_notion_config()


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
        cached_items = db.query(Item).filter(Item.snapshot_id == latest_snapshot.id).all()

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
            "notion_config": notion_config_for_response(sync_to_notion),
        }

    import main

    req = main.ParseRequest(
        course_id=course_id,
        source=parse_source,
        text=normalized,
        term=course.term,
    )

    result = main.parse(req)
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
        response_items.append(_item_response_payload_from_parsed(parsed_item, item_hash_value))

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
        "notion_config": notion_config_for_response(sync_to_notion),
    }
