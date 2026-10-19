# Milestone 1 workbook workflow

Scope: English ordinary `.xlsx`, plain-text evidence, deterministic lexical retrieval and extractive drafts. No LLM, embeddings or agent execution. The API key maps to the server-configured tenant. Reviewer labels are caller-supplied and explicitly unverified. Use synthetic local data until enterprise access is implemented in Milestone 2.

## Run and demonstrate

```powershell
python -m pip install -e '.[dev]'
python -m scripts.sample_workbooks
python -m scripts.workbook_demo
python -m pytest -q
```

The demo uses an isolated temporary database and FastAPI's in-process HTTP client. It imports five questions, drafts them, approves three, leaves the existing response and missing-evidence item unchanged, and writes `completed.xlsx`, `manifest.json`, and `unresolved-items.csv` to ignored `output/milestone1/`. Existing database and authentication environment settings are restored. It does not require a live server or provider.

`samples/security.xlsx` has a row-1 header; `samples/rfp.xlsx` has a row-3 header. Both include multiple sheets, duplicate question text, blank questions, an existing answer, merged answer anchors, formulas outside target cells, hidden rows/sheets, styles and validation. Their companion `.mapping.json` files explicitly select two sheets. All content is synthetic.

## API sequence

Start the API using README instructions. All routes require `X-API-Key`. Never submit a tenant field.

0. `GET /questionnaires/limits`: authenticated upload metadata, returning `max_upload_bytes` from the configured limit. The browser uses this to reject oversized files before multipart transmission; server request/archive limits remain enforced independently.
1. `POST /questionnaires/preview`: multipart `file`, optional `mapping` JSON string. Without mapping, returns sheet names/states, extents and candidate columns with row-1 samples. Samples are inspection aids, not inferred mappings. With mapping, returns exact cell provenance and warnings; at most 100 preview rows are returned, with full `total`. Preview persists nothing.
2. `POST /questionnaires`: multipart `file` and confirmed `mapping`; header `Idempotency-Key` required. Stores the immutable original and every parsed question, including duplicate text in separate rows. Tenant/key/payload retries return the same questionnaire. Changed workbook, canonical mapping or safe filename with the same key returns 409.
3. `GET /questionnaires/{id}` returns summary/counts. `GET /questionnaires/{id}/items?offset=0&limit=100` returns items, current answer/evidence/approval, total and next offset. Page maximum is 200. `GET /questionnaire-items/{id}` returns the current item/answer/approval for scoped review conflict recovery; another tenant receives 404.
4. `POST /questionnaires/{id}/draft` with `{"limit":100}` drafts up to 200 previously undrafted items synchronously. Repeat while `remaining` is nonzero. Existing baseline answer records back each immutable revision. Missing evidence remains `needs_evidence` and cannot be approved.
5. `PATCH /questionnaire-items/{id}/answer` with `{"text":"Reviewed answer","expected_revision":1,"owner":"Security SME"}` creates revision 2. Evidence snapshot is inherited. It always requires a new approval. Use the returned current revision; concurrent edits conflict instead of overwriting each other. Owner is an optional local label for the unresolved report.
6. `POST /questionnaire-items/{id}/approve` with `{"expected_revision":2,"reviewer":"local reviewer","reason":"Checked against policy"}` approves exactly that revision and updates its linked baseline answer. Missing/changed/expired evidence and outdated revisions return 409.
7. `POST /questionnaires/{id}/export` returns a ZIP containing `completed.xlsx`, `unresolved-items.csv` and `manifest.json`. Only current approved revisions with still-valid snapshots are selected. Stale/unapproved revisions are excluded and reported; their original cells remain unchanged. The manifest records source/output SHA-256, exact cells, selected revision IDs/numbers, overwrite intent, unresolved IDs and timestamp. An export record and output are stored in SQLite in the same writer transaction. New manifests also include `unresolved_items`, capturing the report rows at export time; existing manifest fields and older stored exports remain compatible. The ZIP response includes `X-Export-ID` and `Cache-Control: no-store`.
8. `GET /questionnaires/{id}/exports/{export_id}?offset=0&limit=20` returns the saved export receipt: export/questionnaire IDs, creation time, total/selected/unresolved counts, bounded unresolved rows, pagination and `details_available`. Limit is 1-100 and offset is nonnegative. Only the current tenant and matching questionnaire can read it. The endpoint reads that recorded manifest, never current revision/owner state or workbook bytes. Older exports retain their original data: counts remain accurate, detailed rows use `details_unavailable`, and their CSV provides the reasons.

Multipart example (PowerShell uses `curl.exe`; POSIX uses `curl`):

```powershell
curl.exe -H "X-API-Key: $env:EVIDENCEDESK_API_KEY" -F "file=@samples/security.xlsx" -F "mapping=<samples/security.mapping.json" http://127.0.0.1:8000/questionnaires/preview
curl.exe -H "X-API-Key: $env:EVIDENCEDESK_API_KEY" -H "Idempotency-Key: security-import-1" -F "file=@samples/security.xlsx" -F "mapping=<samples/security.mapping.json" http://127.0.0.1:8000/questionnaires
```

Mapping fields per sheet: `sheet`, `header_row`, `question_column`, `answer_column`, optional `identifier_column`, `include_hidden` (default false), `overwrite_existing` (default false). Columns use uppercase Excel letters. Column roles must be distinct. Unknown mapping fields are rejected. Existing answers are imported as preserved destinations, not automatically converted into approved revisions. Setting `overwrite_existing:true` explicitly authorizes overwriting existing literal values only after approval; the intent is persisted and included in preview warnings and the manifest. Formulas are never writable even with overwrite intent.

Workbook errors use `{"error":{"code":"formula_destination","message":"Formula answer cells cannot be overwritten."}}`. Mapping/body errors, pagination, conflicts, authentication and missing records on questionnaire routes also have stable codes. No filesystem paths or parser traces are returned. Authentication errors on legacy endpoints retain FastAPI's `detail` shape for compatibility.

## Supported format and limits

Fixture-tested preservation covers original sheet order/names/state, literal values and formulas outside writable cells, fonts/fills/borders/alignment/number formats, merged ranges, column widths, row heights/hidden flags, freeze panes and ordinary data validation. Export is a semantic round trip, not byte-identical serialization; formulas are preserved without calculation. The immutable source is retained byte for byte.

Reject `.xls`, `.xlsm`, templates, encrypted or malformed files, duplicate/unsafe ZIP entries, external relationships (including URL hyperlinks), drawings/images/charts/shapes, comments, tables, pivots, embedded objects, VBA, custom XML/package parts and extensions the parser cannot preserve. The package part allowlist is intentionally conservative. No URLs are opened, formulas evaluated, macros run or archives extracted. Formula questions, formula destinations, non-anchor merged destinations, overlapping mappings and duplicate destinations are rejected. Empty question cells are skipped. Hidden rows are skipped unless explicitly included; mapped hidden sheets require explicit intent. Formula-like answers beginning with `=`, `+`, `-`, `@` are exported with cell type `s` and no added apostrophe. XML control characters in edited answers are rejected.

Defaults and positive integer environment overrides:

| Setting | Default |
|---|---:|
| `EVIDENCEDESK_MAX_UPLOAD` | 10485760 bytes (10 MiB) |
| `EVIDENCEDESK_MAX_EXPANDED` | 104857600 bytes (100 MiB) |
| `EVIDENCEDESK_MAX_SHEETS` | 20 |
| `EVIDENCEDESK_MAX_QUESTIONS` | 5000 |
| `EVIDENCEDESK_MAX_CELLS` | 100000 populated/merged cells |
| `EVIDENCEDESK_MAX_ROWS` | 20000 row extent |
| `EVIDENCEDESK_MAX_ENTRIES` | 1000 ZIP entries |

The entire multipart body is bounded at upload limit plus 64 KiB before multipart parsing. ZIP directory sizes are checked before XML or openpyxl loading. XML is parsed with defusedxml before openpyxl and merged-cell expansion is bounded. Storage is an immutable SQLite BLOB addressed by server-generated UUIDs, so uploaded filenames never choose filesystem paths. SQLite storage quotas and per-user rate limits remain deployment work.

## Migration and operating limits

Stop writers and back up the SQLite database before upgrading. Install updated dependencies, then start the API or construct `Store(path)`. `app/migrations/001_questionnaires.sql` is applied transactionally and idempotently, recorded in `schema_migrations`, and adds tables/indexes/triggers without changing legacy documents or answers. Connections now explicitly close after commit/rollback to avoid Windows database locks. Foreign keys enforce scoped workbook/questionnaire/item/revision/approval/export relations; a trigger verifies the linked legacy answer tenant. Existing legacy review and CSV endpoints remain available.

There is no destructive downgrade. To roll back the schema, restore a pre-upgrade backup while the service is stopped. Do not mix old and new writers during an upgrade. Originals/revisions are immutable against updates; this is application/database integrity, not infrastructure tamper-proofing. A racing draft batch may leave an unlinked legacy draft but cannot produce duplicate current questionnaire revisions. Drafting and export are synchronous and bounded; export holds a SQLite writer transaction. No retention policy, job queue or production scalability is claimed. Evidence checks cover the current document version, quote and expiry; immutable evidence lifecycle, authenticated reviewer identity and permission revocation are Milestone 2 work.

Library behavior was checked against [openpyxl's official tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html) and [FastAPI's multipart documentation](https://fastapi.tiangolo.com/tutorial/request-forms-and-files/). New direct dependencies are pinned; existing FastAPI/test dependency ranges remain as in the starter.
