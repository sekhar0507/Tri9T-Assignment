# Approach Document — Tri9T CT-200 Document QA API

## 1. Parsing choice

The supplied CT-200 files are text PDFs with selectable text, so the first implementation uses PyMuPDF text blocks instead of running OCR on every page. This is cheaper, repeatable, and preserves text order well enough for this sample. OCR is not falsely claimed: scanned-only inputs require an OCR fallback (e.g. Tesseract) that is not enabled in this implementation. Table rows are retained as extracted text in the relevant section body. A production improvement would use table-region detection and store table cells as structured JSON.

## 2. Hierarchy reconstruction

Numbered headings are detected with a section-number pattern (`1`, `1.1`, `2.1.1.1`). Parentage follows numeric prefixes, not the physical order in the PDF. If an intermediate level is missing, the node attaches to the nearest existing ancestor and this behavior is covered by a test. The document root is represented as `document`. Every node has a version-specific database ID and a logical key. Duplicate logical keys are suffixed so content is not overwritten. Lists and table rows stay in body text rather than being promoted to headings.

## 3. Irregularities found in the source

- `2.1.1.1 Battery Life Under Typical Use` exists without a `2.1.1` section; it is attached to the nearest existing ancestor, `2.1`.
- Section `3.4 Auto Shutoff` occurs before `3.3 Result Display and Classification`; source order is preserved while parentage follows section numbering.
- v2 changes the battery estimate from 300 to 250 cycles and low-battery threshold from 15% to 10%.
- v2 changes cuff inflation increments from 40 mmHg to 30 mmHg.
- v2 changes E3 auto-deflation from 2 seconds to 1.5 seconds in the error-code table, while section 4.1 still says 2 seconds. This cross-section inconsistency is preserved, not silently reconciled.
- v2 adds E6 Bluetooth sync failure and section 5.3 Data Export.
- Error-code and specification tables are laid out visually as tables; the parser keeps extracted rows in body text but does not yet emit cell-level table structures.
- PDF text contains ligatures and special characters (e.g. “cuﬀ”); Unicode NFKC normalization helps normalize them.
- The document includes an image in the rendered page capture; no dedicated figure caption was identified by the parser's text layer.

## 4. Versioning and matching strategy

Each ingest creates a new immutable `DocumentVersion` unless the exact PDF SHA-256 has already been ingested. Nodes match across versions by section-number logical key. Exact normalized text hashes flag any body/heading change. This approach is explainable and reliable for unchanged numbering, but can fail when sections are renumbered, duplicated, or semantically moved. A future version could combine path, normalized title, parent similarity, and fuzzy matching with an explicit ambiguous-match queue.

## 5. Data model

- `document_versions`: document key, version number, source filename/hash, creation time.
- `section_nodes`: version-specific IDs, logical key, heading, level, body, parent/child links, content hash.
- `selections` and `selection_items`: version-pinned IDs plus immutable heading/body/hash snapshots.
- `generation_records`: output JSON, provider, status, warnings, source hashes.
- JSON files under `generated/` mirror generation artifacts as the lightweight NoSQL store; SQLite retains queryable traceability metadata.

## 6. LLM prompt and failure handling

The prompt asks for 3–5 concrete test ideas with title, requirement, preconditions, steps, expected result, severity, and traceability. The source excerpt is explicitly treated as untrusted data. The adapter supports an OpenAI-compatible API and requests JSON mode. It parses JSON, validates required fields/types, retries once on request or validation failure, then uses deterministic fallback cases and records warnings. Invalid individual cases are skipped rather than silently repaired. If fewer than three valid cases remain, the result status is partial/failed and the warning is queryable.

Repeated generation policy: the first generation for a selection is reused by default, so a repeated request is idempotent and avoids unexpected cost/variation. `force=true` deliberately creates another generation.

## 7. Staleness / impact detection

A selection snapshots exact source text and hashes. Retrieval compares each selected logical key to the latest version and reports `changed`, `removed`, or not stale. Generated records retain the source hashes used. Exact hashes deliberately mark even wording-only changes stale. This creates false positives for harmless edits but avoids pretending that semantic equivalence can be guaranteed. A future implementation could classify changed passages into wording-only vs threshold/behavior changes, but should not clear safety-critical stale flags automatically.

## 8. Validation

Tests cover: (1) the missing intermediate parent; (2) out-of-order `3.4`/`3.3`; (3) exact-hash change detection; (4) v1/v2 meaningful content and structural changes; and (5) root/section extraction. Recommended manual validation is visual comparison of each extracted page against PDF pages, especially table cells and heading boundaries. The demo flow ingests both versions, pins a selection to v1, generates cases, and retrieves generation staleness.

## 9. Decision log

1. **Most likely silent wrong result:** a visually aligned table may be flattened into text with columns mixed. Catch it by comparing extracted table rows against page renders and writing assertions for critical table values (E1–E6 and pressure limits).
2. **Simplicity over correctness:** logical section-number matching was chosen over semantic/fuzzy matching. Renumbering or moving a section may appear as removal/addition instead of continuity. Production should add an ambiguity-review step and parent/title similarity.
3. **Unsupported input:** a scanned-only PDF with no text layer is not OCRed by this version. It should be detected through low extracted-text coverage and rejected with an actionable error; OCR fallback is the next improvement. The current parser may need an explicit text-coverage guard before production use.

## 10. What I would improve next

- Add page/block coordinates and table-cell extraction with `pdfplumber` or layout models.
- Add OCR fallback and confidence thresholds for scanned pages.
- Add robust title/duplicate-heading detection using font size and coordinates.
- Add a semantic change-impact classifier while keeping exact-hash stale flags as the safety baseline.
- Add golden extraction fixtures and per-page coverage metrics.
- Add migrations, structured logs, rate limits, and secret management for deployment.
