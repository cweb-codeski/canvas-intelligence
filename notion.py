import os

import requests

NOTION_API_URL = "https://api.notion.com/v1"
REQUEST_TIMEOUT_SECONDS = 10
MISSING_CREDENTIALS_REASON = "NOTION_API_KEY or NOTION_DATABASE_ID is not set"


def _is_notion_sync_enabled() -> bool:
    return os.environ.get("ENABLE_NOTION_SYNC", "true").lower() == "true"


def _notion_credentials() -> tuple[str | None, str | None]:
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip() or None
    database_id = (os.environ.get("NOTION_DATABASE_ID") or "").strip() or None
    return api_key, database_id


def _credentials_missing() -> bool:
    api_key, database_id = _notion_credentials()
    return not api_key or not database_id


def _notion_headers() -> dict:
    api_key, _ = _notion_credentials()
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def check_notion_config():
    if not _is_notion_sync_enabled():
        return {"status": "skipped", "reason": "ENABLE_NOTION_SYNC is false"}

    if _credentials_missing():
        return {"status": "error", "reason": MISSING_CREDENTIALS_REASON}

    _, database_id = _notion_credentials()
    url = f"{NOTION_API_URL}/databases/{database_id}"
    response = requests.get(url, headers=_notion_headers(), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 401:
        return {
            "status": "error",
            "code": 401,
            "reason": "Unauthorized: invalid NOTION_API_KEY or missing workspace access",
        }

    if not response.ok:
        return {"status": "error", "code": response.status_code, "reason": response.text}

    data = response.json()
    props = data.get("properties", {})

    required = {
        "Title": "title",
        "Course": "rich_text",
        "Item type": "rich_text",
        "Event_hash": "rich_text",
    }

    missing = []
    for name, expected in required.items():
        if name not in props:
            missing.append(f"{name} missing")
            continue
        actual = props[name].get("type")
        if actual != expected:
            missing.append(f"{name} type mismatch: {actual} (expected {expected})")

    return {"status": "ok", "missing_properties": missing, "database_name": data.get("title")}


def create_notion_item(item, course_name):
    if not _is_notion_sync_enabled():
        return {
            "status": "skipped",
            "title": item.get("title"),
            "reason": "ENABLE_NOTION_SYNC is false",
        }

    if _credentials_missing():
        return {
            "status": "failed",
            "title": item.get("title"),
            "reason": MISSING_CREDENTIALS_REASON,
        }

    _, database_id = _notion_credentials()
    item_hash = item.get("item_hash")

    if item_hash and item_exists(item_hash):
        print("Skipping duplicate:", item.get("title"))
        return {"status": "skipped", "title": item.get("title"), "reason": "duplicate Event_hash"}

    notion_date = item.get("start_date") or item.get("due_date")

    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Title": {"title": [{"text": {"content": item.get("title") or "Untitled"}}]},
            "Course": {"rich_text": [{"text": {"content": course_name or ""}}]},
            "Item type": {"rich_text": [{"text": {"content": item.get("item_type") or ""}}]},
            "Subtype": {"rich_text": [{"text": {"content": item.get("subtype") or ""}}]},
            "ExamID": {"rich_text": [{"text": {"content": item.get("external_id") or ""}}]},
            "Notes": {"rich_text": [{"text": {"content": item.get("description") or ""}}]},
            "Confidence": {"number": item.get("confidence")},
            "Location": {"rich_text": [{"text": {"content": item.get("location") or ""}}]},
            "Event_hash": {"rich_text": [{"text": {"content": item.get("item_hash") or ""}}]},
        },
    }

    if notion_date:
        payload["properties"]["Date"] = {"date": {"start": notion_date}}

    url = "https://api.notion.com/v1/pages"
    response = requests.post(
        url,
        json=payload,
        headers=_notion_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        msg = response.text
        if response.status_code == 401:
            msg = "Unauthorized: check NOTION_API_KEY and database integration permissions"
        print("Notion write error:", msg)
        return {
            "status": "failed",
            "title": item.get("title"),
            "reason": msg,
            "status_code": response.status_code,
        }

    return {"status": "created", "title": item.get("title")}


def item_exists(item_hash):
    if not _is_notion_sync_enabled():
        return False

    if _credentials_missing():
        return False

    _, database_id = _notion_credentials()
    url = f"https://api.notion.com/v1/databases/{database_id}/query"

    payload = {"filter": {"property": "Event_hash", "rich_text": {"equals": item_hash}}}

    response = requests.post(
        url,
        json=payload,
        headers=_notion_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        print("Query error:", response.text)
        return False

    data = response.json()
    return len(data.get("results", [])) > 0
