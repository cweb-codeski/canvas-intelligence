import os
import requests

NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
ENABLE_NOTION_SYNC = os.environ.get("ENABLE_NOTION_SYNC", "true").lower() == "true"

if ENABLE_NOTION_SYNC:
    if not NOTION_API_KEY:
        raise RuntimeError("NOTION_API_KEY environment variable not set")
    if not NOTION_DATABASE_ID:
        raise RuntimeError("NOTION_DATABASE_ID environment variable not set")

NOTION_API_URL = "https://api.notion.com/v1"
REQUEST_TIMEOUT_SECONDS = 10

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}


def check_notion_config():
    if not ENABLE_NOTION_SYNC:
        return {
            "status": "skipped",
            "reason": "ENABLE_NOTION_SYNC is false"
        }

    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        return {
            "status": "error",
            "reason": "NOTION_API_KEY or NOTION_DATABASE_ID is not set"
        }

    url = f"{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 401:
        return {
            "status": "error",
            "code": 401,
            "reason": "Unauthorized: invalid NOTION_API_KEY or missing workspace access"
        }

    if not response.ok:
        return {
            "status": "error",
            "code": response.status_code,
            "reason": response.text
        }

    data = response.json()
    props = data.get("properties", {})

    required = {
        "Title": "title",
        "Course": "rich_text",
        "Item type": "rich_text",
        "Event_hash": "rich_text"
    }

    missing = []
    for name, expected in required.items():
        if name not in props:
            missing.append(f"{name} missing")
            continue
        actual = props[name].get("type")
        if actual != expected:
            missing.append(f"{name} type mismatch: {actual} (expected {expected})")

    return {
        "status": "ok",
        "missing_properties": missing,
        "database_name": data.get("title")
    }


def create_notion_item(item, course_name):
    if not ENABLE_NOTION_SYNC:
        return {
            "status": "skipped",
            "title": item.get("title"),
            "reason": "ENABLE_NOTION_SYNC is false"
        }

    item_hash = item.get("item_hash")

    if item_hash and item_exists(item_hash):
        print("Skipping duplicate:", item.get("title"))
        return {
            "status": "skipped",
            "title": item.get("title"),
            "reason": "duplicate Event_hash"
        }

    notion_date = item.get("start_date") or item.get("due_date")

    payload = {
        "parent": {
            "database_id": NOTION_DATABASE_ID
        },
        "properties": {
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": item.get("title") or "Untitled"
                        }
                    }
                ]
            },
            "Course": {
                "rich_text": [
                    {
                        "text": {
                            "content": course_name or ""
                        }
                    }
                ]
            },
            "Item type": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("item_type") or ""
                        }
                    }
                ]
            },
            "Subtype": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("subtype") or ""
                        }
                    }
                ]
            },
            "ExamID": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("external_id") or ""
                        }
                    }
                ]
            },
            "Notes": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("description") or ""
                        }
                    }
                ]
            },
            "Confidence": {
                "number": item.get("confidence")
            },
            "Location": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("location") or ""
                        }
                    }
                ]
            },
            "Event_hash": {
                "rich_text": [
                    {
                        "text": {
                            "content": item.get("item_hash") or ""
                        }
                    }
                ]
            }
        }
    }

    if notion_date:
        payload["properties"]["Date"] = {
            "date": {
                "start": notion_date
            }
        }

    url = "https://api.notion.com/v1/pages"
    response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if not response.ok:
        msg = response.text
        if response.status_code == 401:
            msg = "Unauthorized: check NOTION_API_KEY and database integration permissions"
        print("Notion write error:", msg)
        return {
            "status": "failed",
            "title": item.get("title"),
            "reason": msg,
            "status_code": response.status_code
        }

    return {
        "status": "created",
        "title": item.get("title")
    }


def item_exists(item_hash):
    if not ENABLE_NOTION_SYNC:
        return False

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

    payload = {
        "filter": {
            "property": "Event_hash",
            "rich_text": {
                "equals": item_hash
            }
        }
    }

    response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if not response.ok:
        print("Query error:", response.text)
        return False

    data = response.json()
    return len(data.get("results", [])) > 0