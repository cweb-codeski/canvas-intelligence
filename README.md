# Academic Planner Ingestion API

**canvas-parser-service** — a source-agnostic FastAPI backend that ingests academic source material, extracts structured items (exams, assignments, readings, lectures), persists snapshots in SQLite, and optionally syncs to Notion.

Manual syllabus **paste** and **file upload** work without Canvas credentials. Canvas is an optional source adapter.

---

## Quick start (manual demo, no Canvas or Notion)

**Smoke-test runbook:** [docs/MANUAL_DEMO.md](docs/MANUAL_DEMO.md) (checklist, file upload, response fields, troubleshooting).

1. **Prerequisites:** Python 3.11+, `pip`
2. **Install:**

   ```bash
   cd canvas-parser-service
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1    # Windows PowerShell
   pip install -r requirements.txt
   copy .env.example .env            # Unix: cp .env.example .env
   ```

3. **Configure** `.env` (minimal):

   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   ENABLE_NOTION_SYNC=false
   ```

4. **Run:**

   ```bash
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

5. **Ingest** sample syllabus text:

   ```bash
   curl -X POST http://127.0.0.1:8000/manual/syllabus ^
     -H "Content-Type: application/json" ^
     -d "{\"course_key\":\"demo-101\",\"course_name\":\"Demo Course\",\"text\":\"Homework 1 due 2026-02-10\\nMidterm Exam March 1\",\"sync_to_notion\":false}"
   ```

6. **Verify:** open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI). First run creates `./app.db`. Repeat the same curl → `changed: false` (see runbook).

---

## Overview

This service is a single-user MVP academic planner **ingestion engine**. Multiple source adapters feed one shared pipeline:

1. Normalize text and compute a content hash
2. Compare against the latest `SourceSnapshot` for the course
3. If changed: run LLM extraction (default `gpt-4o-mini`, override with `OPENAI_PARSE_MODEL`), validate JSON schema, filter low-confidence items
4. Persist snapshot and `Item` rows in SQLite
5. Optionally sync items to a Notion database

**Manual paths** (`POST /manual/syllabus`, `POST /manual/syllabus/file`) are the simplest way to demo the engine. **Canvas** (`POST /canvas/ingest/{course_id}`) adds assignment-feed ingestion and syllabus discovery from the Canvas API. **Notion** is fully optional.

Design principles: deterministic hashing over ad hoc parsing, schema validation for LLM output, idempotent re-ingest, no invented dates or IDs.

---

## Architecture

```mermaid
flowchart TD
  subgraph adapters [Source adapters]
    ManualPaste[POST manual/syllabus]
    ManualFile[POST manual/syllabus/file]
    CanvasIngest[POST canvas/ingest]
  end

  subgraph engine [Shared ingestion engine]
    Normalize[normalize_text + hash]
    Snapshot[SourceSnapshot compare]
    LLM[OpenAI parse (default gpt-4o-mini, override OPENAI_PARSE_MODEL)]
    Filter[should_keep_item]
    Persist[(SQLite app.db)]
  end

  subgraph optional [Optional]
    NotionSync[Notion API]
  end

  ManualPaste --> Normalize
  ManualFile --> Normalize
  CanvasIngest --> Normalize
  Normalize --> Snapshot
  Snapshot -->|changed| LLM
  LLM --> Filter --> Persist
  Persist --> NotionSync
```

### Shared engine

- Text normalization and content hashing (`utils.py`)
- Snapshot-based change detection (`SourceSnapshot`, `Item` in `models.py`)
- LLM extraction with JSON schema validation and filtering (`main.py`)
- SQLite persistence via SQLAlchemy (`db.py`)

### Manual adapters

- **Paste:** plain text JSON body
- **File upload:** `.txt`, `.pdf`, `.docx` (UTF-8 for text files)

### Canvas adapter (optional)

- Assignments API (deterministic assignment feed snapshot)
- Syllabus discovery waterfall: syllabus body → linked page → attached file → syllabus-titled pages → module files
- Requires `CANVAS_BASE_URL` and `CANVAS_ACCESS_TOKEN` only when calling Canvas endpoints (validated lazily at request time)

### Notion (optional)

- Duplicate prevention via `item_hash` / `Event_hash`
- Config check via `GET /notion/status`
- Per-request `sync_to_notion` on manual and Canvas ingest endpoints

---

## Pipeline flow

### Manual ingest

1. Accept text (paste or extracted file)
2. Normalize and hash; compare to latest syllabus snapshot for `course_key`
3. If unchanged: return cached items (no OpenAI call)
4. If changed: LLM extract → filter → persist snapshot + items
5. Optionally sync to Notion
6. Return JSON with `changed`, `items`, `notion_sync`, `notion_config`

### Canvas ingest

1. Validate Canvas env (503 if missing)
2. Fetch course name and assignments (assignment feed snapshot)
3. Discover syllabus text via Canvas fallbacks
4. Run shared syllabus pipeline with `parse_source=canvas`
5. Merge assignment items into response; sync to Notion if enabled
6. Return JSON (same shape as manual, plus `assignment_snapshot_id`)

---

## Prerequisites

- Python **3.11+**
- `pip` and a virtual environment (recommended)
- **OpenAI API key** (required to start the app)
- Canvas URL + personal access token (only for Canvas ingest)
- Notion integration token + database ID (only if `ENABLE_NOTION_SYNC=true`)

---

## Local setup

```bash
cd canvas-parser-service
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows; Unix: cp .env.example .env
```

Edit `.env` for your demo profile (see [Environment variables](#environment-variables)).

The app creates `./app.db` on first import (`Base.metadata.create_all` in `main.py`).

**Verify after start:**

| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:8000/docs` | FastAPI Swagger UI (primary check for manual demo) |
| `http://127.0.0.1:8000/notion/status` | Optional; Notion config (or `skipped` when `ENABLE_NOTION_SYNC=false`) |

Manual smoke checklist: [docs/MANUAL_DEMO.md](docs/MANUAL_DEMO.md).

---

## Environment variables

Copy [.env.example](.env.example) to `.env`. Prefer a `.env` file over exporting secrets in your shell.

### Startup (environment)

| Variable | Required when | Notes |
|----------|---------------|-------|
| `OPENAI_API_KEY` | **Always** | Missing → `RuntimeError` at import; app will not start |
| `OPENAI_PARSE_MODEL` | Optional | OpenAI model for `main.parse()` / `POST /parse` (LLM extraction only). Default `gpt-4o-mini` |
| `ENABLE_NOTION_SYNC` | Optional | Default in code: `true`. Set `false` for local dev and tests |
| `NOTION_API_KEY` | Notion check/sync (`ENABLE_NOTION_SYNC=true`) | Required when calling `GET /notion/status` or syncing items; not required to start the app |
| `NOTION_DATABASE_ID` | Notion check/sync (`ENABLE_NOTION_SYNC=true`) | Same as `NOTION_API_KEY` |
| `CANVAS_BASE_URL` | Canvas endpoints only | Lazy; not required to start the app |
| `CANVAS_ACCESS_TOKEN` | Canvas endpoints only | Lazy; missing Canvas vars → **503** on `/canvas/ingest/*` |

### Per-request (JSON or form)

| Flag | Applies to | Behavior |
|------|------------|----------|
| `sync_to_notion` | `POST /manual/syllabus`, `POST /manual/syllabus/file`, `POST /canvas/ingest/{course_id}` (query) | Default `true`. `false` → `notion_config.status: "not_checked"` and no `check_notion_config()` call |

### Recommended demo profiles

1. **Manual only (no Canvas, no Notion):** `OPENAI_API_KEY` + `ENABLE_NOTION_SYNC=false`; set `"sync_to_notion": false` on manual requests.
2. **Manual + Notion:** `OPENAI_API_KEY`, `ENABLE_NOTION_SYNC=true`, `NOTION_API_KEY`, `NOTION_DATABASE_ID`; use default `sync_to_notion` or `true`.
3. **Full stack:** profile 2 + `CANVAS_BASE_URL` + `CANVAS_ACCESS_TOKEN`.

**Note:** If `ENABLE_NOTION_SYNC=false` but `sync_to_notion=true`, sync is marked attempted but each item is skipped with reason `ENABLE_NOTION_SYNC is false`.

Manual syllabus paste and file upload do **not** require Canvas credentials.

---

## Running the server

### Local development (port 8000)

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Docker (port 8080)

```bash
docker build -t canvas-parser-service .
docker run --rm -p 8080:8080 --env-file .env canvas-parser-service
```

Use `http://127.0.0.1:8080/...` when running in Docker.

---

## API reference

Interactive docs: `GET /docs` (Swagger UI).

### `POST /manual/syllabus`

Ingest syllabus plain text without Canvas.

**JSON body:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `course_key` | yes | — | Stable course id (stored in `Course.canvas_course_id`) |
| `text` | yes | — | Syllabus text; whitespace-only → **400** |
| `course_name` | no | `course_key` | Display name |
| `term` | no | — | Passed to LLM for date inference (e.g. `Spring 2026`) |
| `sync_to_notion` | no | `true` | Set `false` to skip Notion config check and sync |

**Example (Windows curl):**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus ^
  -H "Content-Type: application/json" ^
  -d "{\"course_key\":\"demo-101\",\"course_name\":\"Demo Course\",\"text\":\"Homework 1 due 2026-02-10\\nMidterm Exam March 1\",\"sync_to_notion\":false}"
```

**macOS/Linux:**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus \
  -H "Content-Type: application/json" \
  -d '{"course_key":"demo-101","course_name":"Demo Course","text":"Homework 1 due 2026-02-10\nMidterm Exam March 1","sync_to_notion":false}'
```

Re-ingesting identical normalized text returns `changed: false` and reuses the snapshot (no second OpenAI call).

---

### `POST /manual/syllabus/file`

Ingest syllabus from an uploaded file (multipart form).

**Form fields:**

| Field | Required | Default |
|-------|----------|---------|
| `course_key` | yes | — |
| `file` | yes | — |
| `course_name` | no | `course_key` |
| `term` | no | — |
| `sync_to_notion` | no | `true` |

**Supported types:** `.txt` (UTF-8), `.pdf`, `.docx`. Other extensions → **400** `Unsupported file type`.

**Example:**

```bash
curl -X POST http://127.0.0.1:8000/manual/syllabus/file ^
  -F "course_key=demo-file-101" ^
  -F "sync_to_notion=false" ^
  -F "file=@syllabus.txt;type=text/plain"
```

Uploads are processed in memory. Do not commit uploaded course files to git.

---

### `POST /canvas/ingest/{course_id}`

Ingest a Canvas course: assignment feed + syllabus discovery.

**Requires** `CANVAS_BASE_URL` and `CANVAS_ACCESS_TOKEN` at request time.

**Syllabus discovery order:**

1. Course `syllabus_body`
2. Linked Canvas page (if linked from syllabus HTML)
3. Attached file referenced in syllabus HTML
4. Course page whose title contains `syllabus`
5. Syllabus-like file in modules

**Query parameters:**

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `sync_to_notion` | no | `true` | Set `false` to skip Notion config check and sync for this ingest (syllabus and assignment items) |

**Example** (use your own numeric Canvas course id, not a real production example):

```bash
curl -X POST http://127.0.0.1:8000/canvas/ingest/12345678
```

Skip Notion for a Canvas ingest:

```bash
curl -X POST "http://127.0.0.1:8000/canvas/ingest/12345678?sync_to_notion=false"
```

**Errors:**

| Status | Meaning |
|--------|---------|
| **503** | Canvas not configured (`CANVAS_BASE_URL` / `CANVAS_ACCESS_TOKEN` missing) |
| **404** | No usable syllabus after all fallbacks |
| **500** | OpenAI or upstream errors |

External HTTP (Canvas, Notion) uses a **10 second** timeout.

**Finding `course_id`:** numeric id from your Canvas course URL (e.g. `https://<school>.instructure.com/courses/<course_id>`).

When `sync_to_notion=true` (default), Notion sync follows `ENABLE_NOTION_SYNC` when syllabus or assignment feed changes. When `sync_to_notion=false`, all Notion sync for that ingest is skipped (syllabus and assignment items).

---

### `POST /parse`

Stateless LLM parse on provided text. **Does not persist** to SQLite — useful for debugging prompts and extraction rules.

**JSON body:** `course_id`, `source`, `text` (required), optional `term`.

---

### `GET /notion/status`

Checks Notion API access and database schema when `ENABLE_NOTION_SYNC=true`.

Expected database properties: `Title` (title), `Course`, `Item type`, `Event_hash` (rich_text). Returns `skipped` when `ENABLE_NOTION_SYNC=false`.

---

## Example responses

### Manual ingest (`POST /manual/syllabus`)

```json
{
  "course_id": "demo-101",
  "changed": true,
  "snapshot_id": 1,
  "assignment_snapshot_id": null,
  "items": [
    {
      "title": "Homework 1",
      "item_type": "assignment",
      "subtype": "homework",
      "start_date": null,
      "due_date": "2026-02-10",
      "description": null,
      "location": null,
      "external_id": null,
      "confidence": 0.95,
      "item_hash": "..."
    }
  ],
  "metadata": {
    "course_id": "demo-101",
    "source": "manual",
    "extraction_confidence": 0.95
  },
  "sources": {
    "syllabus_changed": true,
    "assignment_feed_changed": false
  },
  "notion_sync": {
    "attempted": false,
    "reason": "sync_to_notion disabled"
  },
  "notion_config": {
    "status": "not_checked",
    "reason": "sync_to_notion disabled"
  }
}
```

### Canvas ingest (`POST /canvas/ingest/{course_id}`)

```json
{
  "course_id": "12345678",
  "changed": true,
  "snapshot_id": 1,
  "assignment_snapshot_id": 1,
  "items": [],
  "sources": {
    "syllabus_changed": true,
    "assignment_feed_changed": true
  },
  "notion_sync": {
    "attempted": true,
    "created": 2,
    "skipped": 0,
    "failed": 0
  },
  "notion_config": {
    "status": "ok",
    "missing_properties": []
  }
}
```

Response fields:

- **`changed`** — whether any source changed this run
- **`snapshot_id`** — latest syllabus-related snapshot id
- **`assignment_snapshot_id`** — Canvas assignment feed snapshot (Canvas ingest only)
- **`sources.syllabus_changed`** / **`assignment_feed_changed`** — per-source flags
- **`notion_sync`** — sync attempt summary
- **`notion_config`** — config probe result, or `not_checked` when `sync_to_notion=false`

---

## Notion setup

1. Create a Notion integration and share your target database with it.
2. Set in `.env`:
   - `ENABLE_NOTION_SYNC=true`
   - `NOTION_API_KEY`
   - `NOTION_DATABASE_ID`
3. Confirm schema via `GET /notion/status`.
4. For manual demos without Notion: `ENABLE_NOTION_SYNC=false` and `"sync_to_notion": false` on ingest requests.

Duplicate items are skipped using `Event_hash` (mapped from `item_hash`).

---

## Development

### Tests and lint

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

### Test conventions

- Tests set `OPENAI_API_KEY=test-openai-key` and usually `ENABLE_NOTION_SYNC=false`.
- Canvas tests use fake `CANVAS_BASE_URL` / `CANVAS_ACCESS_TOKEN`.
- Most tests mock `main.parse` or Canvas HTTP — no live OpenAI or Canvas required for CI-style runs.
- Direct unit tests often use in-memory SQLite with an explicit `db` session.
- Test imports set `DATABASE_URL` in `tests/conftest.py` (system temp SQLite file) before `db`/`main` load so import-time `Base.metadata.create_all` does not touch `./app.db`.
- HTTP route writes in TestClient tests still use a function-scoped per-test temp SQLite database via a FastAPI `get_db` dependency override in `tests/conftest.py` (separate from the import-time DB).

| Test file | Covers |
|-----------|--------|
| `test_database_url.py` | `DATABASE_URL` honored at import; pytest avoids default `./app.db` |
| `test_db_isolation.py` | TestClient uses isolated DB via `get_db` override |
| `test_manual_syllabus.py` | Paste, snapshots, empty text 400 |
| `test_golden_syllabus_ingest.py` | Golden syllabus fixture; multi-item ingest regression (mocked parse) |
| `test_manual_syllabus_file.py` | txt/pdf/docx upload, unsupported types |
| `test_canvas_config.py` | Start without Canvas; 503 on ingest |
| `test_ingest_notion_sync.py` | `sync_to_notion` / `notion_config` gating |
| `test_syllabus_snapshot.py`, `test_canvas_*.py` | Canvas pagination, assignments, snapshots |

Manual demo smoke test: [docs/MANUAL_DEMO.md](docs/MANUAL_DEMO.md).

See [AGENTS.md](AGENTS.md) for contributor workflow and safety rules.

---

## Local artifacts and git hygiene

**Do not commit:**

- `.env`, `APIs.env`, or any file containing real API keys or tokens
- `app.db` or other `*.db` files
- Uploaded syllabus files or local upload folders
- `__pycache__/`, `.pyc`, virtualenv folders (`.venv/`, `venv/`)
- Generated artifacts, ZIP archives, screenshots (`.png`), exported HTML (`.html`)

Use [.env.example](.env.example) for placeholders only.

---

## Known limitations

- **Single-user MVP** — no authentication or multi-tenant isolation
- **SQLite** — `sqlite:///./app.db`; not ideal for concurrent multi-writer production
- **Canvas auth** — personal access token in env; school-approved OAuth is the intended future direction
- **LLM extraction** — uses `gpt-4o-mini` by default (configurable via `OPENAI_PARSE_MODEL`); affects parser calls only; may omit or mis-parse items; `should_keep_item` filters low-quality rows
- **Dates** — model must not invent dates; `term` helps infer year only when rules in the parse prompt allow it
- **Assignment vs syllabus snapshots** — separate; unchanged syllabus may still trigger Notion sync for changed assignment feed
- **Syllabus heuristics** — nonstandard Canvas layouts may return **404**
- **PDF/DOCX** — extraction quality varies; scanned PDFs are often poor
- **`course_key`** — stored in DB column `canvas_course_id` (historical name)
- **`POST /parse`** — no persistence; only ingest endpoints write snapshots/items
- **Notion schema** — fixed property names; mismatches reported by `/notion/status`
- **HTTP timeouts** — 10s for external APIs; very large courses rely on pagination helpers tested in `test_canvas_*`

---

## Security

- Treat syllabus text, uploads, Canvas HTML, and PDFs as **untrusted input**
- Never commit or log secrets; do not paste tokens into prompts
- Canvas tokens in `.env` are **dev-only**; prefer OAuth for multi-user deployments
- Use fictional ids in examples (`demo-101`, `12345678`)

---

## Project structure

```text
main.py            # FastAPI app, adapters, ingestion pipeline, OpenAI parse
models.py          # SQLAlchemy models (Course, SourceSnapshot, Item, details)
db.py              # SQLite engine and sessions (creates app.db)
utils.py           # Normalization and hashing
notion.py          # Notion API sync and config checks
requirements.txt   # Runtime and dev dependencies
.env.example       # Environment template
Dockerfile         # Container image (port 8080)
tests/             # pytest suite
AGENTS.md          # Agent and contributor instructions
```

---

## Tech stack

Python, FastAPI, SQLAlchemy, SQLite, OpenAI API, optional Canvas LMS API, optional Notion API.

---

## Future improvements

- Multi-user support and authentication
- PostgreSQL migration
- Background job queue
- School-approved Canvas OAuth
- Frontend dashboard for course visualization
