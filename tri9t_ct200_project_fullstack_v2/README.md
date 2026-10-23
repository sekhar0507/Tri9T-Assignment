# Tri9T AI Engineering Assignment — CT-200 Document QA API

A FastAPI backend that ingests the supplied CT-200 PDFs, stores versioned section trees, pins selections to immutable version-specific text, generates structured QA test ideas, and exposes staleness when source text changes.

> **Scope note:** This is a practical assignment implementation, not a validated medical-device QA tool. Review extracted hierarchy and test cases manually before relying on them.

## Features

- PDF text extraction with PyMuPDF; tables remain represented as row-like text in section bodies.
- Hierarchical nodes, content SHA-256 hashes, versioned SQLite storage.
- v1 → v2 re-ingestion without deleting v1; stable logical keys for numbered sections.
- Browse top-level sections, fetch node tree, search heading/body, and view change diffs.
- Version-pinned selections store snapshots of heading, body, and hash.
- LLM generation through an optional OpenAI-compatible endpoint (e.g. Groq), JSON/schema validation, one retry, and deterministic offline fallback.
- Generation metadata in SQLite plus JSON artifact store; idempotent generation per selection unless `force=true`.
- Staleness endpoint exposes changed/removed selected nodes.
- Tests for hierarchy irregularities, out-of-order numbering, missing intermediate parent, hashes, and v1/v2 changes.

## Frontend + backend

The project now includes a responsive browser frontend served by FastAPI itself; no separate Node/Vite server is required. It supports custom PDF upload, version switching, a section-tree explorer, search, explicit v1/v2 comparison with diffs, pinned selections, QA generation, and stale-source warnings.

1. Start the API with `uvicorn app.main:app --reload`.
2. Open `http://127.0.0.1:8000/` for the Document QA Studio.
3. Use `http://127.0.0.1:8000/docs` for the underlying API explorer.
4. The frontend calls the same-origin `/health`, `/documents/...`, `/selections`, and `/generations/...` endpoints. No CORS setup is needed for this deployment.
5. Click **Ingest v2 manual** or **Run v1 → v2 demo**, explore sections, tick sections to include, save a selection, and generate/retrieve test cases.
6. Use **Upload PDF** to ingest a modified manual, and use **Version comparison** to inspect changed/added/removed sections and text diffs.

## Quick start

Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows; configure values only if using an LLM
# macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

If no LLM credentials are configured, generation uses a deterministic offline fallback. To enable Groq, set `LLM_BASE_URL=https://api.groq.com/openai/v1`, `LLM_API_KEY`, and `LLM_MODEL` in your environment before starting the server. Do not commit `.env`.

## Demonstrate v1 → v2

Run these in a second terminal while the server is running:

```bash
curl -X POST http://127.0.0.1:8000/documents/ct200/ingest/sample-v1
curl -X POST http://127.0.0.1:8000/documents/ct200/ingest/sample-v2
curl http://127.0.0.1:8000/documents/ct200/versions
curl "http://127.0.0.1:8000/documents/ct200/sections?version=1"
curl "http://127.0.0.1:8000/documents/ct200/search?q=Battery&version=1"
```

Use a returned node ID to create a selection, then generate and retrieve:

```bash
curl -X POST http://127.0.0.1:8000/selections ^
  -H "Content-Type: application/json" ^
  -d "{\\"name\\":\\"Battery QA v1\\",\\"node_ids\\":[NODE_ID]}"
curl -X POST http://127.0.0.1:8000/selections/SELECTION_ID/generate
curl http://127.0.0.1:8000/generations/GENERATION_ID
```

PowerShell line continuation differs; the Swagger UI at `/docs` is easiest on Windows. Replace placeholder IDs with actual response values. To force a new generation for an existing selection, use `POST /selections/{selection_id}/generate?force=true`.

Alternative smoke script: `python scripts/demo_flow.py`.

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/documents/{key}/ingest` | Upload a PDF |
| POST | `/documents/{key}/ingest/sample-v1` | Ingest bundled v1 |
| POST | `/documents/{key}/ingest/sample-v2` | Ingest bundled v2 |
| GET | `/documents/{key}/versions` | List versions |
| GET | `/documents/{key}/sections?version=N` | Top-level tree (defaults latest) |
| GET | `/nodes/{id}` | Node, body, hash, recursive children |
| GET | `/documents/{key}/search?q=...&version=N` | Search heading/body |
| GET | `/nodes/{id}/changes` | Compare logical node across versions |
| POST | `/selections` | Create version-pinned selection |
| GET | `/selections/{id}` | Read pinned snapshots and staleness |
| POST | `/selections/{id}/generate?force=false` | Generate 3–5 ideas |
| GET | `/generations/{id}` | Retrieve output and current staleness |
| GET | `/selections/{id}/generations` | List generations with staleness |

## Run tests

```bash
pytest -q
```

## Data and known limitations

- The two source PDFs are bundled in `data/`; the update note explicitly says to parse the PDFs, not Markdown.
- This source is text-based rather than purely scanned, so PyMuPDF extraction is used instead of OCR. For scanned pages, this implementation raises visible extraction/structure limitations rather than silently pretending OCR occurred.
- The PDF has irregularities: subsection `2.1.1.1` without a `2.1.1` parent; `3.4` appears before `3.3`; v2 changes battery estimates/threshold, cuff inflation increment, E3 timing, adds E6, and adds Data Export; and table content must be retained.
- Numbered section paths are used as logical identity. If a section is renumbered or duplicate numbering appears, identity may be imperfect; duplicate numbers are suffixed to preserve both nodes.
- Content hashes are exact normalized text hashes. A punctuation/wording change marks stale just as a clinically meaningful threshold change does. This favors safety/visibility over semantic judgment.
- The parser is tuned to these PDFs, not arbitrary regulatory documents. Manual comparison against rendered pages remains important. The API does not claim medical/regulatory validation.
