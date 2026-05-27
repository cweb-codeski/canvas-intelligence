# Manual syllabus demo (smoke test)

Demo **paste** and **file upload** syllabus ingestion without Canvas credentials or Notion. Uses the shared ingestion engine and a real OpenAI call on the first ingest for new content.

**Prerequisites:** Python 3.11+, virtualenv, dependencies from `requirements.txt`.

---

## Minimal environment

1. Copy the env template:

   ```bash
   copy .env.example .env    # Windows
   # cp .env.example .env    # macOS/Linux
   ```

2. Edit `.env` — minimum for this demo:

   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   ENABLE_NOTION_SYNC=false
   ```

   Leave Canvas and Notion placeholders unset (or commented). They are not read for manual ingest.

3. For every ingest request below, also set **`sync_to_notion=false`** so Notion config is not checked and sync is skipped.

---

## Start the server

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Docker (if used): port **8080** — use `http://127.0.0.1:8080/...` instead of `8000`.

First import creates `./app.db` in the project directory.

---

## Smoke checklist

| Step | Action | Pass if |
|------|--------|---------|
| 1 | Open Swagger UI | `GET /docs` loads |
| 2 | Paste ingest (curl below) | HTTP 200, `changed: true`, `items` non-empty |
| 3 | Repeat same paste request | `changed: false`, same `snapshot_id` |
| 4 | File upload (curl below) | HTTP 200, `changed: true` for new `course_key` |

There is no dedicated `/health` endpoint. Use **`GET /docs`** as the liveness check. Optional: `GET /notion/status` returns `skipped` when `ENABLE_NOTION_SYNC=false`.

---

## Create a local test file (do not commit)

**Windows (PowerShell):**

```powershell
Set-Content -Path syllabus.txt -Value "Homework 1 due 2026-02-10`nMidterm Exam March 1"
```

**macOS/Linux:**

```bash
printf 'Homework 1 due 2026-02-10\nMidterm Exam March 1\n' > syllabus.txt
```

Use fictional course ids only (e.g. `demo-101`). Do not commit `syllabus.txt` or real course materials.

---

## Manual text ingest (`POST /manual/syllabus`)

Request field: `course_key`. Response field: `course_id` (same value).

**Windows (cmd):**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus ^
  -H "Content-Type: application/json" ^
  -d "{\"course_key\":\"demo-101\",\"course_name\":\"Demo Course\",\"text\":\"Homework 1 due 2026-02-10\\nMidterm Exam March 1\",\"sync_to_notion\":false}"
```

**Windows (PowerShell)** — single line:

```powershell
curl.exe -X POST http://127.0.0.1:8000/manual/syllabus -H "Content-Type: application/json" -d '{"course_key":"demo-101","course_name":"Demo Course","text":"Homework 1 due 2026-02-10\nMidterm Exam March 1","sync_to_notion":false}'
```

**macOS/Linux:**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus \
  -H "Content-Type: application/json" \
  -d '{"course_key":"demo-101","course_name":"Demo Course","text":"Homework 1 due 2026-02-10\nMidterm Exam March 1","sync_to_notion":false}'
```

**Repeat** the same command to confirm caching: `changed` should be `false` and `snapshot_id` unchanged. Unchanged responses omit the `metadata` field.

---

## Manual file ingest (`POST /manual/syllabus/file`)

Supported: `.txt` (UTF-8), `.pdf`, `.docx`.

**Windows (cmd):**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus/file ^
  -F "course_key=demo-file-101" ^
  -F "sync_to_notion=false" ^
  -F "file=@syllabus.txt;type=text/plain"
```

**macOS/Linux:**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus/file \
  -F "course_key=demo-file-101" \
  -F "sync_to_notion=false" \
  -F "file=@syllabus.txt;type=text/plain"
```

Or use Swagger UI at `/docs` for paste and multipart file upload.

---
## Compare parse models (dev)

To compare different OpenAI parser models on persisted ingests:

- Set `OPENAI_PARSE_MODEL` in `.env` and restart the server if you're relying on env loading.
- Use different fictional `course_key` values for each model run (so snapshots/items don't overwrite).
- Inspect `metadata.parse_model` in the ingest response to confirm which model was used.
- Do not commit real syllabi or the parser output JSON.

---

## Response fields to inspect

On a **successful first ingest** with `sync_to_notion=false`:

| Field | Expected |
|-------|----------|
| `changed` | `true` |
| `sources.syllabus_changed` | `true` |
| `items` | Non-empty array (assignments, exams, readings, etc.) |
| `notion_config.status` | `"not_checked"` |
| `notion_sync.attempted` | `false` |
| `snapshot_id` | Integer id of the new snapshot |

On **repeat ingest** (identical normalized text):

| Field | Expected |
|-------|----------|
| `changed` | `false` |
| `sources.syllabus_changed` | `false` |
| `snapshot_id` | Same as first run |
| `notion_config.status` | `"not_checked"` |
| `notion_sync.attempted` | `false` |

See [README.md](../README.md#example-responses) for a full JSON example.

---

## What not to commit

- Real syllabi, uploads, or local `syllabus.txt` used for demos
- `.env`, `APIs.env`, or any file with API keys or tokens
- `app.db` or other `*.db` files
- Canvas personal access tokens in shared repos

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: OPENAI_API_KEY environment variable not set` at startup | Missing `OPENAI_API_KEY` in `.env` | Set a valid key in `.env` and restart |
| App won't start | Same as above | Copy from `.env.example` and fill `OPENAI_API_KEY` |
| `503` on `POST /canvas/ingest/...` | Canvas env not configured | Expected for manual-only demo; use `/manual/syllabus` instead |
| `notion_config.status` is `error` or sync `attempted: true` on manual demo | `sync_to_notion` omitted (defaults `true`) or `ENABLE_NOTION_SYNC=true` without credentials | Set `ENABLE_NOTION_SYNC=false` in `.env` and `"sync_to_notion": false` on each ingest |
| `GET /notion/status` shows `skipped` | `ENABLE_NOTION_SYNC=false` | Normal for manual-only; not required for manual ingest |
| `400` No syllabus text provided | Empty or whitespace-only text/file | Provide non-empty syllabus content |
| `400` Unsupported file type | Extension not `.txt`, `.pdf`, `.docx` | Rename or convert file |
| Second ingest still calls OpenAI / `changed: true` | Text normalization differs from first run | Use identical text; check extra whitespace |

**Costs:** First ingest for new content calls OpenAI (`gpt-4o-mini`). Identical re-ingest uses the snapshot cache (no second parse).

---

## Optional negative checks

- Paste with `"text": "   "` → **400**
- Upload `notes.csv` → **400** unsupported type
