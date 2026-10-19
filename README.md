# EvidenceDesk

Evidence-backed RFP and security-questionnaire response workspace for IT service companies and B2B SaaS vendors.

## Current milestone: Milestone 1 workbook workflow

Implemented: JSON evidence ingestion with versions/expiry, tenant-filtered lexical retrieval, extractive drafts with source quotes, missing-evidence escalation, persistent review state, explicit approval, approved-only CSV export, formula escaping, basic timing metadata, authenticated API, regression tests, Docker and CI definitions.

Milestone 1 adds bounded XLSX inspection/preview, explicit per-sheet mappings, immutable originals, persistent cell provenance, idempotent imports, bounded extractive drafting, answer revisions, concurrency-safe approval, and approved-current-only workbook exports with unresolved reports and checksum manifests. Two synthetic templates and an API demonstration are included. See [workbook workflow, API examples and migration instructions](docs/WORKBOOKS.md), [implementation status](docs/IMPLEMENTATION_STATUS.md), and [actual validation](VALIDATION.md).

**Not implemented yet:** live LLMs, embeddings, agentic RAG, contradiction verification, granular document ACLs, enterprise authentication, telemetry backend, distributed execution. This prototype is not ready for customer data or paid production use. Lexical matching can return irrelevant evidence and review does not independently verify factual correctness. Reviewer identity is supplied by the local caller, not verified through an identity provider. XLSX support is limited to the fixture-tested ordinary workbook features documented in docs/WORKBOOKS.md.

## Run without credentials or dependencies

Python 3.11+:

```bash
python -m scripts.demo
python -m scripts.evaluate
python -m unittest discover -s tests -p test_core.py -v
```

## Run the API

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
pip install -e '.[dev]'
# Set EVIDENCEDESK_API_KEY to a generated secret in your shell.
# Linux/macOS: export EVIDENCEDESK_API_KEY=your-generated-secret
# PowerShell: $env:EVIDENCEDESK_API_KEY='your-generated-secret'
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs. Provide X-API-Key for protected endpoints. Add a document, create an answer, approve it, then GET /export. API requests never accept a caller-selected tenant; the local key maps to the server-configured tenant. A production implementation must map verified identities to tenant and document permissions.

```bash
pytest -q
# Docker alternative, with EVIDENCEDESK_API_KEY set:
docker compose up --build
```

Docker/CI definitions are provided; see VALIDATION.md for what was actually executed. Dependencies use bounded ranges, not a production lockfile. Lock and scan them before deployment.

## Workbook demonstration

For a lost local API key, start a single-worker loopback server with recovery explicitly enabled:

```powershell
$env:EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY='1'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
$key = (Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/local/api-key' -Headers @{'X-Local-Key-Recovery'='true'}).api_key
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/export' -Headers @{'X-API-Key'=$key}
```

`POST /local/api-key` generates a new key, revokes the previous key and returns a non-cacheable response. Use the returned key as `X-API-Key` on protected endpoints. It is stored only in the current process; restart or reload restores the startup environment key, requiring another recovery call. The endpoint is disabled by default and rejects remote connections, proxy headers, non-loopback hostnames, cross-origin requests and requests without the explicit recovery header. Keep recovery disabled on shared/deployed servers; use one worker and no auto-reload while using a recovered key. Environment values in `.env.example` are examples and are not automatically loaded.

After installing dependencies:

```bash
python -m scripts.sample_workbooks
python -m scripts.workbook_demo
python -m pytest -q
```

The demo imports `samples/security.xlsx`, reviews supported drafts and exports to ignored `output/milestone1/` using an isolated temporary database. The API export ZIP contains a completed XLSX, a separate unresolved-items CSV and a JSON manifest. Existing answer cells are preserved unless the mapping explicitly enables overwrite; formulas are never writable. Editing an approved answer requires approval of the new revision. Store initialization applies the additive SQLite migration automatically; back up an existing database before upgrading.

## Product and engineering plan

T13's verified local synthetic evaluation/operations work and its remaining external release gates are documented in [OPERATIONS.md](docs/OPERATIONS.md). Reproduce the synthetic release gate with `python -m scripts.release_evaluate`; inspect the separate runtime and learning dependency audit reports. Human-reviewed evaluation and actual staging/container validation remain outstanding.

T01-T06 React frontend is available in `frontend/`: automatic local connection (with a manual-key fallback), saved-questionnaire pagination, legacy text evidence entry, explicit workbook upload/mapping/preview/import, drafting/review with citations, revision-aware edits and human approval, and ZIP export/download with unresolved snapshot receipts. See the [complete user walkthrough](docs/USER_GUIDE.md) and [frontend startup/checks](docs/FRONTEND.md). Set `$env:EVIDENCEDESK_ALLOW_LOCAL_FRONTEND='1'` before starting the single-worker loopback FastAPI server on port 8000, then run `npm.cmd ci` and `npm.cmd run dev` from `frontend/`; open http://127.0.0.1:5173. The frontend obtains a key automatically, keeps it in memory and reacquires it after refresh without rotating other tabs' keys. Restart both servers after upgrading. Open a saved questionnaire, select Review answers, then use Download export bundle.

- docs/PRODUCT.md: buyer, requirement, pilot and acceptance criteria.
- docs/COVERAGE.md: every resume gap and JD optional capability, mapped to implementation milestones.
- docs/ARCHITECTURE.md: target architecture, trust boundaries and design choices.
- docs/BACKLOG.md: ordered tasks with completion gates.
- [docs/NEXT_TASKS.md](docs/NEXT_TASKS.md): execution queue for the React frontend, MCP, agent workflow, AutoGen experiment and A2A integration; T01-T12 are verified locally, next is T13.
- evals/cases.json: three synthetic baseline regression examples, not a valid business benchmark.

No proprietary employer/customer material is included. All sample content is synthetic.


T07 adds immutable approved evidence versions, verified OIDC bearer sessions, current tenant memberships/roles, document ACLs, dependency invalidation, redacted reads and guarded exports. Local synthetic mode remains separate. See [access/lifecycle configuration and backup/restore](docs/ACCESS.md). Live IdP/SSO and hosted deployment are unverified; configure your issuer/API audience and public JWKS explicitly.

T08 exposes scoped MCP tools over stdio using verified OIDC principals, current roles/ACLs and unapproved CAS draft submission. See [MCP startup, schemas and real client demo](docs/MCP.md). No approval tool is exposed.

T09 adds an opt-in PostgreSQL/pgvector retrieval index, scoped lexical/embedding/hybrid search, versioned exact chunks, provider interfaces and strict extractive claim validation. Default embeddings remain synthetic fixtures; a trusted HTTPS gateway adapter is available. See [retrieval startup, APIs and ablations](docs/RETRIEVAL.md).

T10 adds a durable LangGraph drafting workflow with persisted budgets, bounded refinement/retries, isolated-worker cancellation, exact claim verification and a separate human-review gate. Verified sessions can use Agent workflow from item review. See [workflow setup, APIs and recovery](docs/WORKFLOWS.md). Defaults use deterministic providers; live gateway calls require explicit price/cost authorization.

- [AutoGen learning experiment](docs/AUTOGEN.md): offline three-agent execution, comparison commands and framework decision.

T12 adds optional separate A2A 1.0 evidence-expert and questionnaire-agent services using the official SDK. Scoped evidence returns to the primary workflow for citation checks and human review. Run `python -m scripts.a2a_demo` for a temporary synthetic two-process demonstration; see [A2A setup, tests and limits](docs/A2A.md).
