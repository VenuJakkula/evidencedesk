# EvidenceDesk: Codex implementation brief

Version: 1.0 | Date: 2026-10-07

## How to use this file

Save this file as `docs/CODEX_BUILD_PLAN.md` in the existing EvidenceDesk GitHub checkout. Open the repository in VS Code and give Codex this instruction:

> Read AGENTS.md and docs/CODEX_BUILD_PLAN.md. Inspect the current repository and run its existing checks. Implement Milestone 1 end to end, including tests, sample workbooks and documentation. Preserve unrelated changes. Maintain docs/IMPLEMENTATION_STATUS.md with implemented, tested, blocked and planned capabilities. Do not stop at a plan. Do not implement later milestones until Milestone 1 passes its acceptance criteria. Report actual validation and remaining limitations.

For subsequent work, change the milestone number in that instruction. This file defines the full direction; implement one milestone at a time.

## 1. Product outcome

Build a commercially useful RFP and security-questionnaire response workspace for security/presales teams at B2B SaaS companies and IT service firms.

The user uploads a questionnaire, selects approved evidence, receives draft answers with citations, resolves missing/conflicting evidence through owners, approves responses, and downloads a completed copy of the original workbook. Evidence changes trigger re-review.

Commercial willingness to pay is unvalidated. Treat proposed quality/time-saving targets as hypotheses until agreed with a pilot buyer. Use only synthetic or explicitly authorized customer data.

## 2. Repository discovery and working rules

The initial starter had FastAPI, SQLite, deterministic lexical retrieval, extractive answers, API-key authentication, review approval, CSV export, tests, and Docker/CI definitions. The GitHub checkout may have changed: inspect it rather than assuming paths or implementation details.

1. Read applicable AGENTS.md files, README, dependency manifests, tests, architecture and backlog.
2. Inspect git status; preserve existing user changes. Never reset, force-push or delete unrelated files.
3. Run existing tests and record baseline failures separately from introduced failures.
4. Adapt to the repository's conventions. Avoid a wholesale rewrite.
5. Use migrations for schema changes; retain existing data and document upgrade steps.
6. Verify SDK APIs against official documentation when integrating them and lock compatible dependencies using the repository's package manager.
7. Keep secrets out of source control, fixtures, logs and screenshots.
8. Use local fakes for external integrations in CI. Live-provider tests must be separately enabled and budgeted.
9. Do not deploy, incur cloud charges, publish, push changes or send customer communications unless the user authorizes those actions.
10. Clearly distinguish deterministic extraction, vector retrieval, LLM generation and agentic execution in docs and demos. Never label a stub as completed integration.
11. Continue authorized local implementation until the milestone gates pass. Ask only for information that truly blocks work; choose and document reasonable defaults otherwise.

## 3. Initial boundaries

- English `.xlsx` files; explicit question/answer column mapping.
- Plain-text evidence initially; PDF/DOCX extraction follows later.
- API-driven workflow and a local demonstration; a polished frontend is not a Milestone 1 dependency.
- Existing SQLite can remain for Milestone 1. PostgreSQL/pgvector is the target for subsequent retrieval and deployment work.
- Local synthetic-data mode may retain existing authentication. Clearly label it local-only; enterprise OIDC/RBAC must precede real customer data.
- Do not require all advanced learning extensions to sell the first narrow pilot.

## 4. Milestone 1: questionnaire import, review and XLSX export

### 4.1 Required user journey

1. Upload a workbook and inspect sheet names and candidate columns.
2. Select sheets, header row, question column, answer column and optional identifier column explicitly.
3. Preview parsed rows, warnings and mapping before confirming import.
4. Create persistent questionnaire and item records.
5. Draft answers using the existing evidence service and link drafts to questionnaire items.
6. Review/edit/approve individual answers.
7. Export approved answers to their original cells in a new workbook.
8. Return a separate unresolved-items report and a machine-readable export manifest.

Automatic column inference may suggest options, but must never silently choose mappings.

### 4.2 Data model

Use opaque IDs and server-derived tenant scope. Suggested entities:

| Entity | Required data |
|---|---|
| WorkbookAsset | ID, tenant, safe original filename, server-generated storage key, SHA-256, size, created time |
| Questionnaire | ID, tenant, asset ID, mapping specification, status, created time |
| QuestionnaireItem | ID, questionnaire ID, sheet, row, question cell, answer cell, source identifier, original question, status, owner |
| AnswerRevision | ID, item ID, revision number, draft/final text, evidence snapshot, prompt/model versions when applicable, creator, created time |
| Approval | answer revision, verified reviewer when available, decision, timestamp, reason |
| ExportRecord | questionnaire, selected answer revisions, source checksum, output checksum, timestamp, unresolved item IDs |

Adapt existing answer/document schemas instead of creating two conflicting review systems. All relationships must enforce tenant consistency. Persist source-cell provenance; do not reconstruct it from question text.

### 4.3 API contract

Exact route names may follow repository conventions. Provide equivalents of:

- `POST /questionnaires/preview`: multipart workbook plus mapping; bounded parse and preview, no side effects beyond bounded temporary storage.
- `POST /questionnaires`: confirmed workbook/mapping import; accept an idempotency key.
- `GET /questionnaires/{id}`: summary and item counts.
- `GET /questionnaires/{id}/items`: paginated items with answer/review states.
- `POST /questionnaires/{id}/draft`: bounded draft generation; expose job status if asynchronous.
- `PATCH /questionnaire-items/{id}/answer`: create an edited answer revision.
- `POST /questionnaire-items/{id}/approve`: approve the current revision with optimistic concurrency.
- `POST /questionnaires/{id}/export`: produce workbook and manifest; reject stale approvals.

Reuse existing review endpoints if appropriate. Return stable structured errors with a code and actionable message. Do not expose filesystem paths or stack traces to callers.

### 4.4 Workbook handling and supported-format contract

Use an established XLSX library such as openpyxl after checking compatibility. Define support based on round-trip fixtures, not a claim of preserving every Excel feature.

- Default maximum upload: 10 MiB; maximum expanded archive: 100 MiB; maximum sheets: 20; maximum imported questions: 5,000. Make limits configurable and validate before expensive parsing.
- Validate extension and file structure. Reject malformed archives and encrypted files. Reject `.xls`, `.xlsm` and unsupported advanced workbook features with clear messages for this milestone.
- Never evaluate formulas, execute macros, follow external links or open uploaded URLs.
- Use safe server-generated storage paths. Reject ZIP traversal and excessive expansion; avoid extracting arbitrary archive entries.
- Reject external-link workbooks and templates with unsupported drawings/objects if faithful preservation is not demonstrated.
- Preserve the original bytes immutably; export to a separate file.
- Preserve supported formatting, formulas, sheet names/order, merged ranges, widths, heights and validations outside explicitly configured writable cells.
- Do not overwrite formula cells. Do not overwrite existing non-empty answer cells by default; require explicit overwrite intent and record it.
- Skip empty question cells; include hidden rows/sheets only through explicit mapping intent.
- Reject non-anchor merged answer cells and question/answer mappings that overlap. Reject duplicate destination mappings.
- Treat formulas in question cells as unsupported initially unless an explicit cached-value policy is implemented and tested. Never compute them.
- Store answers as literal strings, including strings beginning with `=`, `+`, `-` or `@`; verify output cell type. Preserve original values in non-target cells.
- Export approved, current revisions only. Leave unresolved target cells unchanged and provide the unresolved report; do not insert invented responses.
- Repeated questions in different rows are separate items, even if their texts match.

### 4.5 Review integrity

Editing an approved answer creates a new revision requiring approval. An approval is tied to one revision, not an item forever. Use compare-and-set revision checks to prevent concurrent edits silently overwriting each other.

Idempotent import retries return the same import for the same tenant/key/payload. Reusing a key with a different payload returns a conflict. Export never mutates the source workbook.

### 4.6 Tests and acceptance criteria

Create synthetic workbook fixtures covering two templates, multiple sheets, duplicate questions, empty rows, existing answers, formulas, merged cells and styled non-target cells.

Required tests:

- Correct import count and exact sheet/cell mapping.
- Round-trip preservation of supported workbook properties outside writable cells.
- Approved answers inserted only into mapped cells.
- Unapproved, edited-after-approval and stale answers excluded.
- Formula-like answer text remains literal text.
- Formula destinations and invalid merged-cell mappings rejected.
- Tenant cannot read, approve or export another tenant's questionnaire.
- Oversized, malformed and unsupported files rejected before expensive processing.
- Traversal-like filenames cannot select storage paths.
- Import retries are idempotent; conflicting keys return conflict.
- Export original checksum remains unchanged.
- API upload-to-export integration test, including pagination and stable errors.
- Migration upgrade preserves existing answers/documents.

Milestone 1 is complete only when these tests, existing tests and the documented local demonstration pass. Report which workbook features are unsupported. Do not claim GenAI readiness from this milestone alone.

### 4.7 Deliverables

Code, migration, fixtures, tests, dependency updates, API examples, local demo, README instructions and updated implementation status. Add an explanation of supported templates and overwrite behavior. No real customer files in the repository.

## 5. Milestone 2: evidence lifecycle and enterprise access

Implement document uploads/parsing, immutable versions, approval status, provenance, product/edition/deployment metadata, validity and deletion. Track every answer's dependencies on evidence versions.

Implement OIDC token verification, issuer/audience checks, tenant membership, document ACLs and roles for author/reviewer/admin. Reviewer identity must come from authentication, not a caller-provided name. Enforce permission checks in backend services and tools.

On source update, revocation, expiry or deletion, invalidate dependent approvals and scoped caches. Recheck evidence access and validity at review/export time. Restrict export by current permissions.

Add append-only audit records, secret management configuration, trace redaction, retention/deletion behavior and backup/restore instructions. Do not claim tamper-proof auditing unless infrastructure supports it.

Gate: unauthorized-source tests, permission revocation tests, approval invalidation tests, identity verification tests and a restore exercise. Live IdP integration may require user configuration; provide local fixtures without weakening production mode.

## 6. Milestone 3: measurable agentic RAG

### Retrieval

Use PostgreSQL with pgvector and schema migrations. Implement lexical, embedding and hybrid retrieval, followed by reranking experiments. Preserve document/page/section locations. Apply tenant, ACL, applicability, evidence approval and validity filters before passing text to the model.

Version embedding model, chunking configuration and corpus. Define reindex/delete behavior. Do not mix incompatible embedding spaces.

### Workflow

Implement a LangGraph state machine: classify -> retrieve -> assess evidence -> draft -> verify -> human review. Add bounded retrieval refinement when evidence is incomplete. Missing/conflicting sources become explicit owner tasks, not confident answers.

Use durable checkpoints, attempt/time/token budgets, retryable-error classification, deadlines and cancellation. Resume after process failure without duplicating externally visible actions. Tool authorization belongs in the tool implementation.

Provide structured output schemas with applicability, answer, claim-level evidence and uncertainty reasons. Validate source IDs and quotes against authorized retrieved material. Do not rely on self-reported confidence as correctness evidence.

Expose scoped evidence search through MCP if useful; maintain an ordinary API adapter for testing. Benchmark single-agent and separated retriever/verifier roles before adopting multiple agents.

Gate: hybrid retrieval ablation, citation integrity, unsupported-question abstention, conflicting policy handling, injection suite, restart recovery and bounded-loop tests.

## 7. Milestone 4: evaluation and observability

Start with 30-50 reviewed cases and grow toward 150-250. Label answerability, applicability, gold evidence, expected facts, contradictions and permissions. Split development/validation/held-out test sets. Keep optimization access away from held-out labels.

Track retrieval Recall@k/nDCG, answer correctness, citation support, unsupported claims, abstention, contradiction detection, review edits/time, p50/p95 latency and cost per questionnaire. Define metrics precisely; do not collapse all outcomes into 'accuracy'.

Use Ragas or DeepEval where appropriate, deterministic checks for invariants, and human calibration of LLM judges. Report sample sizes, denominators, model versions and judge limitations. Store versioned evaluation outputs and set documented release thresholds.

Integrate Langfuse or LangSmith for ingestion/retrieval/model/tool/workflow traces. Connect request/job IDs across spans. Capture usage and costs without retaining secrets or unrestricted document content. Add failure taxonomy, health/readiness checks and debugging runbooks.

Gate: prompt/model/retrieval changes generate comparable reports; CI fails on agreed regressions; seeded failures can be diagnosed through traces.

## 8. Milestone 5: optimization, resilience and deployment

Use LiteLLM or equivalent provider adapters with two providers. Implement routing based on measured task performance. Define retries, cooldowns and fallback policy. Provider fallback must not relax data residency, privacy, evidence or permission requirements.

Implement caches keyed by tenant, permission scope, corpus/evidence version, prompt/model version and request inputs. Invalidate on access/evidence changes. Test leakage and stale answers.

Use DSPy/GEPA for classification or supported-answer drafting after the baseline dataset exists. Compare fixed prompts and optimized prompts on held-out data. Report quality/cost/latency tradeoffs.

Lock dependencies, scan images/dependencies, run non-root containers, separate staging configuration/secrets, add CI/CD gates, migration checks, load tests and rollback. Establish RPO/RTO and practice restore. Do not provision paid cloud resources automatically.

Gate: provider outage tests, retry/idempotency tests, scoped-cache tests, reproducible optimization report, container smoke tests and staging rollback demonstration.

## 9. Milestone 6: advanced extensions for full learning coverage

These remain optional for the first paid pilot but must have concrete experiments if the learning goal is full JD coverage.

| Capability | Experiment | Completion evidence |
|---|---|---|
| A2A | Separate evidence-expert agent with authenticated scoped requests | Interoperability, timeout, unauthorized-request tests |
| Tavily/Firecrawl | Allowlisted public documentation discovery with approval before ingestion | Provenance, SSRF/redirect checks, freshness tests |
| Kubernetes | Staging API/workers with managed DB, probes, limits and secret injection | Load, restart, scaling and rollback exercise |
| Hugging Face/Transformers/PyTorch/LoRA | Fine-tune classifier or reranker only if data and baseline justify it | Held-out comparison and reproducible training artifacts |
| Multi-agent architecture | Compare single-agent versus specialist roles | Quality, latency and cost comparison |
| Third-party integration | Permission-aware document-store and owner-task connector | Upstream outage and revoked-access tests |

Public web evidence must never establish a company's private security capabilities. Crawling and remote tools require allowlists, limits and provenance.

## 10. Proposed pilot gates

Agree targets with a buyer; these are goals, not achieved results:

- Correct source-cell mapping on all supported pilot templates.
- No unauthorized evidence in the defined access test suite.
- No unapproved or stale final answers exported.
- At least 80% draft acceptance without material factual edits for answerable cases.
- At least 50% reduction in median human preparation/review time on comparable questionnaires.
- Report unsupported claims, abstention, citation quality, latency and cost separately.

Human review remains required before customer-facing representations. Record operating scope and known failure modes alongside every claim.

## 11. Implementation status template

Maintain `docs/IMPLEMENTATION_STATUS.md` with:

| Capability | Status | Evidence/test command | Limitation | Next task |
|---|---|---|---|---|
| XLSX import/export | planned | pending | pending | M1 |
| Evidence lifecycle/access | planned | pending | pending | M2 |
| Agentic RAG | planned | pending | pending | M3 |
| Evaluation/observability | implemented_unverified | Synthetic split reports and content-free trace checks; see OPERATIONS.md | Human labels/calibration/reviewer metrics and hosted trace verification pending | M4 |
| Routing/optimization/deployment | implemented_unverified | Offline routing/DSPy, scoped cache, runtime lock/audit and restore/load rehearsal | Live-provider comparison, container/image checks and staging rollback pending | M5 |
| Advanced extensions | planned | pending | pending | M6 |

Use `planned`, `in_progress`, `implemented_unverified`, `verified_local`, `verified_staging`, or `blocked`. Describe actual coverage; never mark an entire row complete from one passing happy-path test.

## 12. Codex completion report

After each milestone, report:

1. Behavior implemented and how it serves the user workflow.
2. Files changed and migration instructions.
3. Exact checks executed and outcomes.
4. Known limitations and external configuration still required.
5. Next milestone and its first actionable task.

Do not invent test results, live integrations, buyer validation or production readiness. This document authorizes scoped local implementation when invoked; it does not authorize external publishing or paid infrastructure.
