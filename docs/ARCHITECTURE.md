# Architecture

## Current

FastAPI -> deterministic evidence/review service -> SQLite. Documents are plain text with tenant, version and expiry. Drafting extracts matching sentences; it does not use embeddings or generation. SQLite persists review state across restarts. Single API key and server-configured tenant are local-only identity controls.

Milestone 1 adds bounded multipart/ZIP/XML preflight -> openpyxl inspection/mapping -> immutable SQLite workbook assets -> questionnaire items with source-cell provenance -> immutable revisions linked to baseline answers -> revision-specific approvals -> separate XLSX/report/manifest export. Writer transactions serialize revision edits, approvals, idempotent imports and export snapshots. Additive migration 001 preserves the legacy schema and data; see WORKBOOKS.md for upgrade and supported-format limits.

## Target

FastAPI/OIDC -> questionnaire parser -> durable LangGraph workflow -> permission-filtered hybrid retrieval -> model gateway -> claim verifier -> review queue -> workbook exporter. PostgreSQL/pgvector stores evidence, workflow and audit records; object storage holds original files; Langfuse receives redacted traces.

The graph should have explicit classify/retrieve/check-evidence/draft/verify/review/export states. Retrieval retries are bounded. Missing evidence and contradictory evidence interrupt for SMEs. Approved external actions require tool-side authorization and idempotency. Start single-agent; benchmark role separation before adding multiple agents.

## Trust boundaries

- Derive tenant and role from verified identity, never document text or request-selected tenant.
- Apply ACLs before retrieval and again when reading/exporting evidence.
- Retrieved content cannot issue instructions or grant tool permissions.
- Include tenant, ACL scope, prompt/model version and corpus version in cache keys.
- Review identity must be server-derived; record an append-only audit trail.
- Changing evidence invalidates dependent approvals and caches.
- Redact secrets and personal data in traces; configure retention and deletion.
- Crawling requires URL allowlists, SSRF protection and provenance; public evidence cannot establish private company capabilities.

## ADRs

1. Local baseline is dependency-light and fully extractive to make workflow testable without API credentials.
2. PostgreSQL/pgvector is the initial target to minimize operational components; compare other databases only when needed.
3. Provider/model selection follows measured quality/cost, not a fixed latest-model assumption.
4. Numeric and date checks run in code; LLMs interpret text and propose structured answers.
5. Enterprise readiness requires OIDC/RBAC, encryption, secret management, audit, backups, dependency lock/scans and agreed evaluation gates.

## Documentation references checked during initialization

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://fastapi.tiangolo.com/tutorial/testing/
- https://docs.litellm.ai/docs/routing

Pin compatible SDK versions when those integrations are implemented; no live SDK integration is claimed in this milestone.
