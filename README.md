# canvas-intelligence
FastAPI-based ingestion pipeline that converts unstructured Canvas course data into structured, queryable academic items.

---

## Overview

Canvas Intelligence is designed to transform unstructured and semi-structured course content into a consistent data model. 

The system integrates directly with the Canvas API, extracts syllabus and assignment data across multiple sources, applies structured extraction using LLMs, and persists results with snapshot-based change tracking.

It is built as a single-user MVP backend with a focus on reliability, deterministic processing, and extensibility.

---

## Core Capabilities

### Multi-Source Ingestion

* Canvas syllabus body
* Canvas pages
* Attached files (PDF, DOCX)
* Canvas modules
* Canvas assignments API

### Structured Extraction Pipeline

* LLM-based semantic parsing into typed academic items
* JSON schema validation for output integrity
* Confidence scoring for each extracted item
* Filtering logic to remove non-actionable content

### Data Normalization + Hashing

* Text normalization for deterministic comparisons
* Content hashing for snapshot detection
* Item-level hashing to prevent duplication

### Persistence Layer

* SQLite + SQLAlchemy
* Snapshot-based versioning (SourceSnapshot)
* Structured item storage (Item table)
* Detail tables for assignments, exams, readings

### Change Detection

* Content hash comparison to detect updates
* Cached response return for unchanged sources
* Incremental ingestion behavior

### Notion Integration

* Automatic sync of structured items to a Notion database
* Duplicate prevention using item_hash
* Schema validation + config checks

---

## Architecture

High-level pipeline:

1. Fetch data from Canvas (syllabus, pages, modules, assignments)
2. Normalize and clean raw text
3. Generate content hash and compare with latest snapshot
4. If changed:

   * Run LLM extraction
   * Validate output against schema
   * Filter low-quality items
   * Persist snapshot + items
5. Sync results to Notion
6. Return structured response via API

---

## Tech Stack

* Python
* FastAPI
* SQLAlchemy
* SQLite
* OpenAI API (LLM extraction)
* Canvas LMS API
* Notion API

---

## Project Structure

```
main.py            # API routes and ingestion pipeline
models.py          # Database schema
utils.py           # normalization and hashing utilities
db.py              # database setup
notion.py          # Notion sync logic
requirements.txt   # dependencies
Dockerfile         # containerization
```

---

## API Endpoints

### POST /canvas/ingest/{course_id}

Ingests a Canvas course and returns structured academic items.

**Response includes:**

* extracted items (exams, assignments, lectures, readings)
* snapshot IDs
* change detection flags
* Notion sync results

---

### POST /parse

Runs standalone LLM-based parsing on provided text input.

---

### GET /notion/status

Validates Notion API configuration and database schema.

---

## Environment Variables

Set the following before running:

* OPENAI_API_KEY
* CANVAS_BASE_URL
* CANVAS_ACCESS_TOKEN
* NOTION_API_KEY
* NOTION_DATABASE_ID
* ENABLE_NOTION_SYNC

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Running the Server

```bash
uvicorn main:app --reload
```

---

## Design Principles

* Deterministic pipelines over ad hoc parsing
* Strong schema validation for LLM outputs
* Separation of ingestion, extraction, and persistence
* Idempotent processing via hashing
* Explicit handling of unreliable upstream data

---

## Future Improvements

* Multi-user support and authentication
* PostgreSQL migration
* Background job queue (Celery / Redis)
* Vector search over course content
* Frontend dashboard for visualization

---

## Author

Built as part of an AI + backend systems project focused on intelligent data ingestion and structuring pipelines.
