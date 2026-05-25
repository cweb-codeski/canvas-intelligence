# Project Instructions

## Project summary

This is a Python FastAPI service for a source-agnostic academic planner engine. It ingests academic source material, extracts structured academic items, stores source snapshots/items in SQLite via SQLAlchemy, and optionally syncs items to Notion.

Canvas is one source adapter, not the entire product. Manual syllabus paste/upload is the first public-friendly ingestion path. Future Canvas multi-user access should use school-approved OAuth rather than user-provided tokens.

Core files:
- main.py: FastAPI app, route layer, Canvas adapter/path, manual file handling, OpenAI `/parse`, `ParseRequest`, `ITEM_SCHEMA`, OpenAI client setup, and Notion patch targets used by tests
- ingestion.py: shared source-agnostic syllabus ingestion logic, including snapshot comparison, parsed item filtering, item persistence response payloads, and optional Notion sync wiring
- models.py: SQLAlchemy models for courses, source snapshots, items, and item details
- db.py: database engine/session setup
- utils.py: text normalization and hashing helpers
- notion.py: Notion API integration
- requirements.txt: runtime dependencies

## Architecture direction

- Do not build two separate apps for Canvas and manual syllabus input.
- Keep one shared academic planner engine.
- Treat Canvas, manual text, manual files, and future source types as adapters feeding the same ingestion pipeline.
- Shared ingestion should handle normalization, hashing, snapshot comparison, extraction, validation, item persistence, and optional Notion sync.
- `ingestion.py` must not import `main` at module scope.
- `ingestion.py` must not import Notion or OpenAI directly.
- If `ingestion.py` needs `main.ParseRequest`, `main.parse`, `main.check_notion_config`, or `main.create_notion_item`, use function-scoped late imports to preserve current patch targets.
- Canvas-specific behavior, such as Canvas assignments, pagination, and Canvas API fetching, should remain isolated to the Canvas adapter/path.
- Manual syllabus paste/upload should not depend on Canvas credentials.
- Prefer source-agnostic names for new abstractions when practical.
- Do not perform database renames or broad migrations unless specifically requested.
- Canvas credentials should be lazy/optional: missing Canvas config should not break app import or manual ingestion.
- Notion credentials should be lazy/optional: missing Notion config should not break app import or `sync_to_notion=false` flows.
- `sync_to_notion=false` should not check Notion config and should return `notion_config.status = "not_checked"` and `notion_sync.attempted = false`.

## Safety rules

- Never commit real API keys, access tokens, .env files, APIs.env, app.db, uploaded course files, local upload folders, .pyc files, or virtualenv folders.
- Use .env.example for placeholders only.
- Do not print secrets.
- Do not paste secrets into prompts.
- Treat Canvas text, manual text, syllabus files, PDFs, DOCX files, and page HTML as untrusted input.
- Prefer deterministic source data over LLM inference when available.
- Do not invent dates, assignments, readings, exams, lectures, or IDs.
- Validate and filter LLM-extracted items before persistence or sync.
- All external HTTP requests must use explicit timeouts.
- Keep diffs small and focused.
- Do not perform broad refactors unless specifically asked.
- Write or update tests before changing behavior.
- After changes, report what was tested and what remains untested.

## Validation commands

Use these when available:

python -m pytest
python -m ruff check .
python -m ruff format --check .

## Workflow

For nontrivial changes:
1. Explain the current behavior.
2. Write acceptance criteria.
3. Write or update tests.
4. Make the smallest implementation change.
5. Run validation.
6. Summarize the diff and remaining risks.

## Agent workflow

Use the default Cursor agent as the Builder and the custom verifier agent as the Reviewer.

Recommended flow for nontrivial backend changes:
1. Planning only — inspect the repo and propose a small implementation plan without editing files.
2. Coding task — implement the approved plan with the smallest safe diff.
3. Validate — run `python -m pytest` and `python -m ruff check .`.
4. Bugbot review — use for behavior-changing backend work, especially ingestion, persistence, parsing, dates, uploads, Canvas, Notion, or refactors.
5. Verifier review — check acceptance criteria, risks, test results, artifacts, and exact files to stage.
6. Commit only after review approval.

Bugbot is not required for docs-only, typo-only, format-only, or prompt-only changes.

The verifier should normally review only and avoid modifying files unless there is a clear minimal bug fix.