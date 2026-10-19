# Next tasks - React frontend and agent integrations

Updated: 2026-10-19. This is the ordered execution queue requested after Milestone 1. The detailed `EvidenceDesk_Codex_Build_Plan.md` retains its milestone definitions; this queue adds a React frontend and explicit MCP, AutoGen and A2A learning tasks. **T01-T13 are verified_local within the agreed local synthetic scope. External M4/M5 gates remain pending.** Complete one task and record its actual checks in IMPLEMENTATION_STATUS.md and VALIDATION.md before starting the next.

## Intended user journey

Open the React app -> connect to the local API -> add evidence -> upload a workbook -> select sheets/header rows/columns -> preview and confirm -> generate drafts -> inspect citations -> edit and approve -> download the completed workbook and unresolved report. Later agent integrations improve drafting while the same human approval and export rules remain enforced by backend services.

## Ordered queue

| Order | Task | Depends on | Completion gate |
|---|---|---|---|
| T01 | React application foundation and API connection - verified_local | Existing M1 API | Build/type check, 36 frontend tests, 54 backend tests and 18 live HTTP smoke checks passed, including automatic local connection; see FRONTEND.md |
| T02 | Questionnaire dashboard and evidence entry - verified_local | T01 | Users add synthetic evidence and reopen saved questionnaires through paginated APIs |
| T03 | Workbook upload, mapping and preview - verified_local | T02 | Both sample workbooks import correctly through explicit browser mappings |
| T04 | Drafting and answer review workspace - verified_local | T03 | Citations, missing evidence, edits, revision conflicts and approval are visible and correct |
| T05 | Export/download experience - verified_local | T04 | Browser downloads the export bundle; approved/current-only behavior matches the API |
| T06 | Frontend end-to-end tests and user guide - verified_local | T05 | Complete synthetic user journey passes browser tests and backend regressions |
| T07 | Evidence lifecycle and enterprise access - verified_local | T06; detailed plan M2 | Verified identities, scoped access and evidence invalidation tests pass |
| T08 | MCP server with scoped evidence/questionnaire tools - verified_local | T07 | A real MCP client discovers and invokes tools with isolation and protocol tests |
| T09 | Retrieval and model-provider foundation - verified_local | T07; detailed plan M3 | Hybrid retrieval, citation provenance and deterministic provider fakes pass |
| T10 | Bounded agent drafting and verification workflow - verified_local | T08, T09 | Research/draft/verify/human-review flow passes citation, abstention and recovery gates |
| T11 | AutoGen learning experiment and framework comparison - verified_local | T10 | Actual AutoGen agents complete a bounded scenario; comparison is reproducible |
| T12 | A2A evidence-expert service - verified_local | T10, T11 | Two separate services exchange real A2A tasks with auth, timeout and isolation tests |
| T13 | Evaluation, observability and deployment work - verified_local (synthetic scope) | T10; extend after T12 | Follow detailed-plan M4/M5 gates; measure results rather than claiming readiness |

T01-T06 are a local synthetic-data frontend phase, not an enterprise deployment. T08 is scheduled early within M3 after M2 access controls; T11/T12 are learning extensions aligned with M6. Existing advanced learning tasks remain in the detailed plan. Do not skip the evidence/access prerequisite when connecting external clients or agents.

## T01 - React foundation and API connection

- Create `frontend/` using React, TypeScript and Vite; choose compatible versions from official documentation during implementation and commit an npm lockfile.
- Add navigation and accessible page structure for questionnaires, evidence entry and review. Include loading, empty, error and connection states.
- Add a typed API client for JSON, multipart uploads and binary downloads. Handle both existing legacy `detail` errors and questionnaire `error.code/message` errors.
- Use a Vite development proxy for ordinary API traffic so local development can use one browser origin. Define production routing later; do not enable unrestricted CORS.
- User-requested follow-up: automatically obtain a key through an opt-in loopback development-session bridge, then authenticate it; keep masked manual entry as a fallback. Keep keys in memory, clear them on disconnect, and exclude them from URLs, localStorage, logs and committed configuration. Ordinary proxy access to recovery/bootstrap remains blocked; the bridge uses a separately constrained direct backend request. Reuse current keys so page refreshes do not revoke other tabs.
- Provide `.env.example` for non-secret client configuration and document starting FastAPI and React in separate terminals. Do not put secrets in `VITE_*` variables, which are bundled into browser code.

Acceptance: production build and type check pass; a focused client test verifies error handling; the app checks `/health`, and validates the key through an authenticated read endpoint before declaring the connection authenticated. No full questionnaire screens are required to finish T01.

## T02 - Dashboard and evidence entry

- Add a tenant-scoped paginated `GET /questionnaires` API; the current backend exposes individual questionnaires but no listing endpoint. Return summaries suitable for the dashboard without workbook bytes or secrets.
- Display questionnaire title/safe filename, status, item count and created time. Open an existing questionnaire after browser refresh/reconnection.
- Add an evidence form for the current `POST /documents` fields: title, plain text, version and expiry, with validation and a clear success result.
- If evidence browsing is needed, add a bounded tenant-scoped document-list endpoint. Label this as legacy text evidence entry; version upload/revocation/approval belong to T07.

Acceptance: list pagination and cross-tenant backend tests pass; users can create evidence and select a persisted questionnaire through the UI. Preserve existing API contracts and data.

## T03 - Workbook upload and mapping

- Upload `.xlsx` and inspect `/questionnaires/preview` without a mapping to show sheet names/states and candidate columns.
- Provide explicit per-sheet controls for header row, question/answer columns and optional identifier column. Do not silently choose mappings from suggestions.
- Explain hidden-row inclusion and existing-answer overwrite options; require explicit intent. Keep the default of preserving existing answers.
- Show the mapped preview, exact source/destination cells, total counts, warnings and unsupported-format errors before confirmation.
- Create a request idempotency key and retain it across retries of the same confirmed payload. Use a new key when the payload changes or the user intentionally starts another import.

Acceptance: security and RFP samples each import five items with the expected cells; invalid mapping, hidden-sheet intent, existing-answer warnings, upload limits and retry conflicts are correctly displayed. Uploaded files are not retained in browser storage.

## T04 - Drafting and review

- Render paginated items with question, sheet/row, original identifier, draft, evidence quotes and current revision/approval state.
- Call bounded draft batches until completion; show progress and recoverable failures without duplicate approval actions.
- Edit using `expected_revision`; show conflicts with a reload action and preserve unsaved text for comparison in memory.
- Approve a specific current revision only after explicit user action. Editing an approved response visibly requires reapproval.
- Explain missing evidence and preserved destinations; allow an owner label through the current edit contract. Do not suggest missing-evidence drafts are approved or factually verified.

Acceptance: browser checks cover edit/reapprove, stale-revision conflict, citation display and missing-evidence rejection. The backend remains the authority for approval and tenant checks.

## T05 - Export/download

- Download the API's ZIP response with a safe client filename and release temporary object URLs after use.
- Explain the three bundle files: completed XLSX, unresolved-items CSV and machine-readable manifest. Display confirmation that export applies approved current revisions only.
- Keep unresolved items visible in the review workflow. Add a bounded export-summary API only if needed to display authoritative counts before/after downloading; do not infer export success from UI selection alone.

Acceptance: the sample browser journey produces the correct mapped answers; existing answers and formulas remain unchanged; editing after approval excludes the edited answer until reapproval. No automatic customer delivery is added.

## T06 - Frontend verification and documentation

- Add Playwright or an equivalent real-browser test against an isolated FastAPI database with synthetic fixtures. Cover connect, add evidence, import, draft, edit, approve and export/download.
- Cover invalid key, mapping failure, revision conflict and missing-evidence states. Include keyboard navigation and basic accessibility checks for forms and review actions.
- Add frontend checks and the browser journey to CI with bounded runtime and no live paid model calls. Retain the full backend regression suite and workbook demo.
- Write a user walkthrough with local start commands, supported formats, expected sample results and troubleshooting for dependency/connection failures.

Acceptance: record actual build/type-check/browser/backend/demo results. Container or hosted deployment remains unverified unless separately executed. Do not mark a screen complete from a screenshot alone.

## T07 - Evidence lifecycle and access (M2)

Follow the detailed plan: immutable evidence versions, source dependency snapshots, review invalidation, OIDC verification, tenant membership, author/reviewer/admin roles and document ACLs. Reviewer identity must come from authenticated claims. Add migration/restore tests and permission-revocation tests. Adapt the React app to authenticated sessions without exposing local recovery in deployed mode.

Acceptance: backend and browser access checks prevent unauthorized sources, stale approvals and cross-tenant reads/exports. Live IdP configuration is a separate explicitly recorded dependency; CI uses local fakes.

## T08 - MCP integration

- Implement an actual MCP server with SDK compatibility verified against official documentation and locked dependencies.
- Begin with bounded read tools such as `search_evidence`, `get_questionnaire` and `get_questionnaire_items`. Reuse backend authorization and services; derive tenant scope from authenticated context.
- Add `submit_draft` only after revision/CAS rules are integrated; it must create an unapproved revision. Do not make human approval available to autonomous callers by default.
- Demonstrate a real MCP client discovering and invoking the tools. Document transport, authentication, schemas and local startup.

Acceptance: protocol/client tests, tenant/ACL isolation, input validation, expired/revoked evidence and failure handling pass. A renamed REST endpoint is not an MCP implementation.

## T09-T10 - Retrieval and agent workflow

Use the detailed M3 design for PostgreSQL/pgvector, lexical/hybrid retrieval, model adapters and durable orchestration. Retain LangGraph as the planned primary workflow until a documented comparison justifies changing it. Add classify -> retrieve -> assess -> draft -> verify -> human review, with deadlines, attempt/token budgets, citation validation and resumable state. CI uses deterministic provider fakes; live runs require explicit credentials and a budget. The React app exposes progress, evidence and review decisions without treating agent output as approved.

Acceptance: answerable/unanswerable/conflicting-evidence cases, prompt injection, invalid citations, permission checks, cancellation and restart recovery pass. Measure quality/cost/latency before introducing more specialist agents.

## T11 - AutoGen experiment

The user explicitly wants AutoGen coverage. Add an isolated experiment with actual researcher/writer/verifier agents, shared scoped service adapters and bounded execution. Keep it separate from the primary production path while evaluating it; avoid maintaining two full workflow engines for the same job without measured benefit.

Before implementation, recheck AutoGen's maintenance/support status and compatible versions against Microsoft's official documentation. The earlier feasibility review found maintenance-mode guidance and an Agent Framework successor; document the then-current choice. An Agent Framework implementation must not be labelled as AutoGen coverage. Compare the AutoGen experiment against the existing primary workflow on the same synthetic cases, including citation correctness, unsupported claims, latency, model calls and cost. Record an adoption/non-adoption decision.

Acceptance: real framework execution with fake-model CI tests and a reproducible comparison report; no completion claim from stub agents or a framework dependency alone.

## T12 - A2A integration

Run an independently addressable evidence-expert service and a questionnaire-agent client. Use the actual A2A SDK/protocol, agent discovery metadata, task submission/status and result artifacts. Verify current protocol compatibility from official documentation before implementation. Authenticate both sides, scope evidence access, and implement timeout/cancellation/retry behavior. Results return provenance to the primary workflow for verification and human review; agents cannot approve final answers or export on a user's behalf without separately authorized backend policy.

Acceptance: two-service interoperability demonstration plus unauthorized-request, tenant isolation, timeout, upstream outage, duplicate-request and cancellation tests. Internal function calls between two classes do not count as A2A.

## Working on one task at a time

T01-T12 are verified locally; see IMPLEMENTATION_STATUS.md and VALIDATION.md. The agreed local synthetic queue is complete. External M4/M5 gates remain listed in OPERATIONS.md.

For each task, change `planned` to `in_progress`, then `implemented_unverified` or `verified_local` based on actual results. Record blockers separately; do not silently change a task's scope or replace a requested framework. No task in this queue authorizes publishing, paid infrastructure, customer communications or unbudgeted live-provider calls.

T11 (2026-10-19): `verified_local`. Actual three-role AutoGen execution, 23 offline tests and four-case same-fixture comparison passed. LangGraph remains primary; see AUTOGEN.md and VALIDATION.md.

T12 (2026-10-19): `verified_local`. Official A2A 1.0 SDK, separate evidence-expert and questionnaire services, 26 passing acceptance tests and a successful two-process demonstration with provenance and explicit human review. See A2A.md and VALIDATION.md. T13 remains planned.

T13 (2026-10-19): `implemented_unverified`. Local evaluation/observability/resilience/operations implementation passes its synthetic checks. Full completion still requires human-reviewed/calibrated cases and real reviewer metrics, measured live-provider routing/optimization, Docker image smoke/security checks, and actual staging rollback evidence. No approved staging target or reviewed dataset was supplied. See OPERATIONS.md and VALIDATION.md for exact local results and limits.

T13 scope confirmation (2026-10-19): The user selected "Use local synthetic validation; keep external gates explicit". T13 is `verified_local` for that agreed scope, based on the recorded 207 passing backend tests, 73 frontend tests, 20/20 synthetic held-out cases and operations checks. Human-reviewed evaluation, live-provider validation and actual container/staging rollback remain pending external gates; full M4/M5 or production readiness is not claimed.
