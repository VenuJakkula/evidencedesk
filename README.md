# EvidenceDesk

Evidence-backed RFP and security-questionnaire response workspace for IT service companies and B2B SaaS vendors.

## Current milestone: initialized local baseline

Implemented: JSON evidence ingestion with versions/expiry, tenant-filtered lexical retrieval, extractive drafts with source quotes, missing-evidence escalation, persistent review state, explicit approval, approved-only CSV export, formula escaping, basic timing metadata, authenticated API, regression tests, Docker and CI definitions.

**Not implemented yet:** live LLMs, embeddings, agentic RAG, contradiction verification, granular document ACLs, enterprise authentication, real questionnaire imports, layout-preserving exports, telemetry backend, distributed execution. This prototype is not ready for customer data or paid production use. Lexical matching can return irrelevant evidence and review does not independently verify factual correctness. Reviewer identity is supplied by the local caller, not verified through an identity provider.

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

## Product and engineering plan

- docs/PRODUCT.md: buyer, requirement, pilot and acceptance criteria.
- docs/COVERAGE.md: every resume gap and JD optional capability, mapped to implementation milestones.
- docs/ARCHITECTURE.md: target architecture, trust boundaries and design choices.
- docs/BACKLOG.md: ordered tasks with completion gates.
- evals/cases.json: three synthetic baseline regression examples, not a valid business benchmark.

No proprietary employer/customer material is included. All sample content is synthetic.
