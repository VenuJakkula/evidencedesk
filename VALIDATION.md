# Validation history

## Automatic local frontend connection on 2026-10-08

User-requested automatic key acquisition replaces repeated manual pasting in local development. Added opt-in `POST /local/session-key` (reuse or generate, no rotation) and a Vite development-only `POST /dev/session-key` bridge. React automatically acquires a memory-only key and verifies health/authentication; manual entry and explicit retry remain available. Disconnect clears the client, while refresh can reacquire the current server key. Backend configuration is disabled by default and requires explicit `EVIDENCEDESK_ALLOW_LOCAL_FRONTEND=1`; production/preview hosting is not enabled by this change.

Actual validation: `npm.cmd run build` passed strict typing and production bundling; `npm.cmd test` passed **36 tests** across 3 files; `.venv\Scripts\python.exe -m pytest -q` passed **54 tests** with the same upstream Starlette/httpx warning; `.venv\Scripts\python.exe -m scripts.frontend_smoke` passed **18 real HTTP checks** with no database side effects. Tests cover automatic acquisition/authentication, fallback errors, malformed key responses, key reuse/generation, rejection of remote/proxied/cross-origin requests, and ordinary-proxy blocking of both local key endpoints. Build output was 231.67 kB JS (72.48 kB gzip). Browser automation was not executed; component tests use jsdom. No persistent user key or running server was changed by the checks.

## T01 React foundation validation on 2026-10-08

Implemented React navigation/connection shell, typed JSON/multipart/binary client, memory-only keys, cancel/timeout/error states, read-only authenticated `GET /session`, restricted same-origin development proxy, non-secret configuration and npm lockfile. Existing changes were preserved; T02 screens and listing APIs were not started.

Baseline: `.venv\Scripts\python.exe -m pytest -q` reported **51 passed**, one upstream Starlette/httpx warning. Node is **24.20.0**, npm is **11.19.0**. PowerShell blocked `npm.ps1`; commands used `npm.cmd` without changing execution policy. Official React/Vite/Vitest documentation and npm package compatibility were checked; references are in docs/FRONTEND.md.

| Command | Actual result |
|---|---|
| `npm.cmd install` / `npm.cmd ci` in frontend | Both succeeded; lockfile reinstall added 100 packages, audited 101; reported zero vulnerabilities at execution time |
| `npm.cmd run build` | Strict TypeScript check and production Vite build passed; final JS bundle 230.73 kB (72.22 kB gzip), CSS 9.19 kB |
| `npm.cmd test` | **32 passed**, 3 test files; client errors/JSON/multipart/binary/cancellation, connection UI, key clearing and proxy boundaries |
| `.venv\Scripts\python.exe -m pytest -q` | **52 passed**, one existing upstream Starlette/httpx warning; new test verifies session authentication, server-derived tenant and no database access |
| `.venv\Scripts\python.exe -m scripts.frontend_smoke` | **9 real HTTP checks passed** across isolated running Vite/FastAPI processes; valid/invalid/missing keys, health, blocked recovery/traversal, no database side effects |
| `.venv\Scripts\python.exe -m compileall -q app scripts tests` | Passed |
| `git diff --check` | Passed; existing Windows line-ending informational warnings |

During implementation, an initial build caught an incorrect `loadEnv` import and optional proxy-response typing; both were fixed. A focused test caught DOMException cancellation being classified as a network error across test realms; it was fixed and the final suite passed. Null/malformed successful API responses are now checked explicitly. The successful `npm ci` run verifies dependency installation from the lockfile. No API keys were stored in frontend configuration or persistent browser storage.

CI configuration now includes frontend installation/build/tests and the real HTTP smoke script. Hosted CI, container build, real-browser rendering/accessibility automation, the full workbook browser journey and deployment were not executed for T01. The React component tests use jsdom; the HTTP smoke test is not a browser test. No persistent database, existing server process or user API key was changed by the smoke checks.

The earlier validation sections below record previous milestones on 2026-10-07.

## Local API-key recovery follow-up

Added opt-in `POST /local/api-key` for single-process loopback development, with explicit recovery header, remote/host/proxy/origin rejection and non-cacheable generated-key responses. Rotation revokes the previous process key; restart/reload restores startup configuration. Actual command `.venv\Scripts\python.exe -m pytest -q`: **51 passed**, one upstream Starlette/httpx warning, 20.98 seconds. Tests verify authentication with the issued key, previous-key revocation and access controls. `git diff --check` passed with Windows line-ending informational warnings. No running server or persistent secret configuration was changed by this implementation.

Executed locally using Python 3.12:

- `python -m pytest -q`: 8 passed. One upstream Starlette/httpx deprecation warning.
- `python -m scripts.evaluate`: 3 synthetic regression cases, zero failures.
- `python -m scripts.demo`: evidence -> draft -> approval -> CSV completed.

Tested FastAPI 0.142.2, Uvicorn 0.54.0, httpx 0.28.1, pytest 9.1.1. Dependency ranges are specified; a complete locked environment remains a deployment task.

Docker executable is unavailable in the initialization environment. Image build, Compose, GitHub-hosted CI and cloud/Kubernetes deployment were not executed. No live LLMs or external services were called by the application. No benchmark, production reliability or commercial validation is claimed.

## Windows baseline check on 2026-10-07

Using the local Python 3.14 virtual environment, pytest reported 2 passed and 6 failed. The six core tests failed during temporary-directory cleanup with WinError 32 because SQLite database files remained open. This issue is preserved in the initial baseline for a follow-up fix. One Starlette/httpx deprecation warning was also reported.

## Milestone 1 validation on 2026-10-07

The Windows baseline issue above is now fixed: `Store.connect()` commits/rolls back and explicitly closes every connection. This also makes temporary database cleanup in the legacy demo and evaluation succeed. The first system-Python pytest attempt lacked pytest; after installing declared dependencies, the original suite passed 8/8. A separate check in the existing virtual environment confirmed the original baseline was 2 passed/6 cleanup failures before the fix.

Final checks executed using system Python 3.14.7 on Windows:

| Command | Actual result |
|---|---|
| `python -m pip install -e '.[dev]'` | Editable install succeeded, including pinned openpyxl 3.1.5, python-multipart 0.0.22 and defusedxml 0.7.1 |
| `python -m pytest -q` | **49 passed**, one upstream Starlette/httpx deprecation warning, 17.14 seconds |
| `python -m unittest discover -s tests -p test_core.py -v` | **6 passed**, including successful Windows temporary-directory cleanup |
| `python -m scripts.sample_workbooks` | Generated two synthetic XLSX files and their explicit mapping JSON files in `samples/` |
| `python -m scripts.workbook_demo` | API preview/import/draft/review/export passed; 5 items imported, 3 approved answers exported, 2 unresolved; source checksum unchanged |
| `python -m scripts.demo` | Original evidence/draft/approval/CSV demonstration passed |
| `python -m scripts.evaluate` | 3 synthetic regression cases, zero failures |
| `python -m compileall -q app scripts tests` | Passed |
| `python -m pip check` | No broken requirements found |
| Docker availability check | Docker CLI unavailable; existing image-build check could not run locally |
| `git diff --check` | Passed; Git emitted Windows LF-to-CRLF informational warnings |

The 49 tests include the 8 original tests and 41 workbook/migration/API cases. Tested workbook scope: two synthetic multi-sheet templates, duplicate questions, exact source/destination cells, empty/hidden rows, existing answers, formula/merged-cell rejection, supported styles/geometry/validations/formulas, literal formula-like answer strings, immutable source checksums, revision conflicts, unapproved/stale answer exclusion, bounded uploads/ZIP expansion/merged areas, encrypted/malformed/unsafe/unsupported packages, stateless preview, migration preserving legacy data, tenant isolation and API pagination/errors.

The generated demonstration artifacts are in ignored `output/milestone1/`: completed XLSX, unresolved CSV and export manifest. Both committed sample templates are exercised by the tests. No customer files are included.

Only local checks are claimed. GitHub-hosted CI, Docker/Compose, browser UI, Microsoft Excel/LibreOffice rendering, live providers, enterprise identity and staging/cloud deployment were not executed for this milestone. New direct dependencies are pinned; the existing application/test dependency ranges remain and a complete locked environment is future deployment work. Workbook support and upgrade/rollback instructions are documented in `docs/WORKBOOKS.md`. Milestone 1 is deterministic extraction and human review, not GenAI or production-readiness validation.


## T02 dashboard and evidence entry ? 2026-10-08

Status: verified_local. Existing working changes preserved; T03 not started.

- `npm.cmd run build` (frontend): passed TypeScript and Vite production build.
- `npm.cmd test` (frontend): 40 passed. New checks cover pagination, persisted selection after remount, list error/refresh, whitespace validation, exact evidence payload, success/reset and retention after API failure. Foundation expectations updated for the new authenticated listing request.
- `.venv\Scripts\python.exe -m pytest -q`: 56 passed, one existing upstream Starlette/httpx deprecation warning. New service/API checks cover bounds, empty/out-of-range pages, stable ordering, restart, summary allowlist and cross-tenant isolation. Initial new-test failures were corrected: store is a service closure rather than a FastAPI dependency, and invalid pagination uses the established 422 contract.
- `.venv\Scripts\python.exe -m scripts.frontend_smoke`: 26 checks passed against actual isolated FastAPI/Vite HTTP servers. Includes paginated list/read, authentication, other-tenant exclusion and evidence creation through the proxy; only the temporary test database is populated.
- `.venv\Scripts\python.exe -m scripts.workbook_demo`: 5 imported, 3 approved exported, 2 unresolved; source unchanged.
- `git diff --check`: passed (existing Windows line-ending notices).

No real-browser automation or deployment was run. React interactions were checked with jsdom and the proxy/API with real HTTP. Evidence lifecycle remains legacy text entry; browsing, version uploads, revocation and approval were not added.


## T03 workbook upload, explicit mapping and preview ? 2026-10-08

Status: verified_local. Existing working changes preserved; T04 not started.

- Frontend `npm.cmd install --save-dev --save-exact @playwright/test`: installed Playwright 1.64.0 and updated the npm lockfile; audit reported zero vulnerabilities. No browser download was needed: the gate used installed headless Edge. Channel support was checked against [official Playwright browser documentation](https://playwright.dev/docs/browsers).
- Frontend `npm.cmd run build`: passed TypeScript and Vite production build. `npm.cmd run typecheck` also passed after the browser response-interception test update.
- Frontend `npm.cmd test`: **47 passed**. New focused tests cover mapping-free inspection, no implicit choices, default preservation, cell/warning/count preview, truncation notice, explicit hidden intent, distinct-column validation, stale-preview invalidation, same-payload retry key retention, changed-payload/new-import keys, conflict/format/413 errors, configured-size preflight, and reset abort/late-result suppression. Vitest excludes the separate Playwright suite.
- `.venv\Scripts\python.exe -m scripts.workbook_browser`: **5 passed in 22.2 seconds**, actual headless Edge with temporary FastAPI/Vite servers and an isolated SQLite database. Both security and RFP samples each imported five questions through explicitly entered browser mappings. Exact source/destination cells and backend item provenance matched their fixtures. Each reopened after refresh; localStorage and sessionStorage remained empty. Other cases checked hidden-sheet intent, preservation/overwrite warnings, mapping invalidation, unsupported/malformed/oversized files, and safe retries.
- Browser retry case: CDP response-stage interception dropped the genuine POST response after the server committed. Confirming again retained the same Idempotency-Key and returned the same questionnaire ID, with one matching persisted record. Starting another import generated a different key. A subsequent simulated 409 verified the displayed conflict and recovery message; real API idempotency conflicts remain covered by backend tests.
- `.venv\Scripts\python.exe -m pytest -q`: **57 passed**, one existing upstream Starlette/httpx deprecation warning. The new limits endpoint is authenticated and reports the configured value. Existing mapping, import, idempotency, tenant, upload-limit and export regressions pass.
- `.venv\Scripts\python.exe -m scripts.frontend_smoke`: **26 checks passed** against isolated real HTTP proxy/backend servers.
- `.venv\Scripts\python.exe -m scripts.workbook_demo`: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.
- `.venv\Scripts\python.exe -m compileall -q app scripts tests`: passed. `git diff --check`: passed, with existing Windows line-ending notices.

Initial browser failures were investigated and fixed: the harness needed captured Unicode-safe subprocess output; tests needed the fixture's actual Internal sheet name and required same-origin bootstrap header. Oversized browser uploads exposed a real early-rejection/proxy connection reset, so the UI now reads authenticated upload metadata and checks file size before sending bytes. Attempting to resend intercepted multipart requests through Playwright's request helper did not preserve the file payload; the retry gate now drops the genuine browser response after server commit using CDP instead. The final complete five-case run passed.

This gate covers T03, not the future complete evidence/draft/edit/approve/export browser journey or CI browser integration. No deployment, real-data upload, schema migration, paid model call or external communication occurred. UI files and retry keys are not stored in browser storage and are released on success/reset/navigation/disconnect. Server originals remain persisted only after confirmation.


## T04 drafting and answer review - 2026-10-08

Status: verified_local. Existing working changes preserved; T05 was not started.

- Frontend `npm.cmd run build`: passed TypeScript and Vite production build.
- Frontend `npm.cmd test`: **56 passed**. Nine new focused tests cover citation/provenance display, approved-answer edit/reapprove, expected revisions/owner payloads, genuine conflict handling with local-text retention and explicit rebase, unknown approval response/reload without a duplicate request, missing evidence/preserved destinations, multi-batch drafting without approval, persistent failure/resume, pagination/reload edit retention, no-progress stopping and cancellation/late-result suppression. Existing connection/import/evidence tests pass.
- `.venv\Scripts\python.exe -m pytest -q`: **58 passed**, one existing upstream Starlette/httpx deprecation warning. Added authenticated current-item reads and cross-tenant 404 checks; existing revision, approval, evidence and export tests remain green.
- `.venv\Scripts\python.exe -m scripts.workbook_browser`: **9 passed in 39.5 seconds**, actual headless Edge against temporary synthetic FastAPI/Vite servers and SQLite database. Five existing workbook cases and four review cases passed. Review cases exercise citation/version/cell display, edit/reapprove, owner persistence, missing-evidence UI blocking plus real backend 409 rejection, and preserved-destination explanation. A real competing API edit triggers browser CAS conflict; reloading retains local text for explicit comparison and resaving at revision 3. CDP drops a genuine successful approval response after server commit; the UI requires reload, displays the saved approval and sends exactly one approval request. A 45-item fixture drafts 25 items, encounters a simulated 503 interruption, then resumes the remaining 20, with all items at revision 1 and no approvals. Unsaved text survives item pagination and workspace tabs; disconnect clears the review workspace and browser storage remains empty.
- `.venv\Scripts\python.exe -m scripts.frontend_smoke`: **26 checks passed**.
- `.venv\Scripts\python.exe -m scripts.workbook_demo`: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.

Initial implementation type-check failures in the local-edit merge were corrected; initial new-unit-test failures came from a test helper treating the API client's explicit GET method as a non-read. Draft errors now persist after refreshing completed/partial items, and failed reloads keep the mutation recovery gate. Final focused tests passed. The final browser run passed all nine cases.

Draft runs are bounded to 25-item requests, 201 batches and two minutes; mutations/read recovery have 30-second deadlines. There is no autonomous approval or automatic retry of save/approve requests. Reviewer/owner labels remain unverified, evidence lifecycle remains legacy, and browser export/download plus full-journey CI work remain T05/T06. No schema/data replacement, live model call, deployment or external communication occurred.

T04 final housekeeping: `.venv\Scripts\python.exe -m compileall -q app scripts tests` and `git diff --check` passed (existing Windows line-ending notices). Production build/type checking also passed after removing obsolete planned-screen metadata.


## T05 export/download experience - 2026-10-08

Status: verified_local. Existing working changes preserved; T06 was not started.

- Frontend `npm.cmd run build`: passed TypeScript and Vite production build after export integration and browser test additions.
- Frontend `npm.cmd test`: **67 passed** across eight test files. New coverage verifies sanitized/ZIP-only/reserved Windows filenames, removal of the temporary anchor, delayed object URL revocation, immediate cleanup on dispatch failure, authoritative snapshot counts and unresolved pagination, metadata-only recovery after receipt failure, unsaved/recovery export blocking, safe receipt IDs, historical metadata fallback, failed exports without success/download claims, and abort/late-result suppression on unmount. An initial integration assertion failed because PowerShell's Python source pipeline changed Unicode separators into question marks; the assertion was corrected to use an ASCII-safe pattern. Final full suite passed.
- `.venv\Scripts\python.exe -m pytest -q`: **61 passed**, one existing upstream Starlette/httpx deprecation warning. Added checks cover receipt/header agreement with the ZIP manifest, pagination/bounds, tenant/questionnaire isolation, authentication, frozen owner/reason/count snapshots after later edits, response allowlist and honest compatibility with manifests predating detailed unresolved rows. Existing edit/reapproval/export/evidence regressions remain green.
- `.venv\Scripts\python.exe -m scripts.workbook_browser`: **12 passed** in approximately 1.1 minutes, real headless Edge against temporary synthetic FastAPI/Vite servers and SQLite database. Five import, four review and three export cases passed. Security and RFP exports each applied three writable approved answers and kept two unresolved items, including an approved preserved destination. The browser actually saved the ZIPs. `scripts.inspect_export_bundle` inspected all three bundle files, exact selected cells, every original cell outside selected destinations, original formulas/merged ranges/sheet states, CSV unresolved reasons and source/output checksums. Formula-like edited responses remained literal strings. Security additionally exported a saved unapproved edit (two selected/three unresolved, original destination restored) and its reapproved revision (three selected/two unresolved). Receipts agreed with each bundle and the older receipt stayed a snapshot until another download. Simulated export 503 created no download/success claim; simulated receipt 503 retried only metadata and did not generate another export. Browser storage remained empty.
- `.venv\Scripts\python.exe -m scripts.frontend_smoke`: **26 checks passed**.
- `.venv\Scripts\python.exe -m scripts.workbook_demo`: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.
- `.venv\Scripts\python.exe -m compileall -q app scripts tests`: passed.
- `git diff --check`: passed, with existing Windows line-ending notices.

Implementation keeps the existing ZIP body and bytes-only service call compatible. `X-Export-ID` identifies the received export; `GET /questionnaires/{id}/exports/{export_id}` reads only that tenant/questionnaire's persisted manifest and returns at most 100 unresolved rows (default 20). New manifests include unresolved report snapshots without modifying old exports or database schema. A receipt is an export-time result, not a live eligibility estimate. The UI reports that the bundle was received and browser download started; it does not claim the browser saved the file at a particular location. Object URLs are revoked after a one-second dispatch delay or immediately on dispatch failure, following [MDN object URL lifetime guidance](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Schemes/blob).

The three export browser cases prepare fixtures through the existing API and exercise review/download in the browser; the single full UI-only evidence/import/review/export journey and CI/browser/user-guide gate remain T06. No deployment, customer delivery, schema replacement, paid model call or external communication occurred.


## T06 full frontend verification and user guide - 2026-10-08

Status: verified_local. Existing working changes preserved; T07 was not started.

- `npm.cmd install --save-dev --save-exact @axe-core/playwright` in frontend/: installed/locked axe 4.13.0, audit zero vulnerabilities. Playwright remains 1.64.0. Official [accessibility](https://playwright.dev/docs/accessibility-testing) and [CI](https://playwright.dev/docs/ci) documentation was checked before configuration.
- `npm.cmd ci --prefix output/t06-install-check`: clean installation using copies of the actual package.json/package-lock.json in an ignored directory, 105 packages added, 106 audited, zero vulnerabilities. This verified the lockfile without replacing dependencies used by the user's already-running development server.
- Frontend `npm.cmd run build`: production Vite build and TypeScript checks passed.
- Frontend `npm.cmd test`: **67 passed** across eight test files. Existing client/connection/evidence/import/review/export regressions remain green.
- `.venv\Scripts\python.exe -m pytest -q`: **63 passed**, one existing upstream Starlette/httpx deprecation warning. New fixture tests verify ordered reset of all synthetic workflow records, schema retention and reuse, untouched sibling databases, and rejection of unowned directories/incorrect ownership markers before creating or mutating data.
- `.venv\Scripts\python.exe -m scripts.workbook_browser`: **15 passed** in headless Edge (about one minute).
- `$env:EVIDENCEDESK_BROWSER_CHANNEL='chromium'` followed by the same harness command: **15 passed** in locked Chromium (about one minute). `npx.cmd playwright install chromium` installed Chrome for Testing 156.0.8078.4, Playwright build v1248, locally. Windows Chromium was verified; a Linux/GitHub-hosted run was not executed.
- New browser cases complete the whole security and RFP workflows through UI actions: automatic connection, evidence form submission, workbook selection/inspection, explicit per-sheet mappings, mapped preview/confirmation, persisted questionnaire selection, bounded drafting, citation inspection, text/owner edit, explicit revision approval and real ZIP download. No API fixture creation is used by these two cases. ZIPs were inspected using `scripts.inspect_export_bundle`: each has five imported items, three applied and two unresolved, correct mapped cells/checksums/CSV reasons and original values/formulas outside selected destinations. The exact newly-entered evidence title/version appears in citations because every case starts with an empty owned database.
- Keyboard checks cover the skip link/main focus, navigation, evidence input order, sheet checkbox toggling, mapping inputs and save/approve/download actions. Axe scans use WCAG 2 A/AA and 2.1 A/AA tags on connection, evidence, mapped preview, review and receipt screens for both journeys, plus invalid-key error state (11 scans, zero violations in final runs). New invalid-key case verifies failed authentication, cleared key field, absent connected state and keyboard automatic recovery. Existing cases retain genuine CAS conflict/local-text recovery and missing-evidence UI/backend rejection coverage. Full UI journeys observed zero external browser requests and no page errors; browser storage remained empty.
- Initial axe scans failed on muted shell text/status contrast; colors were darkened without disabling contrast rules. A subsequent invalid-key scan identified the error pill's 4.44:1 contrast; its color was corrected. Focus outlines were also darkened. Final complete suites passed on both engines. These automated checks do not constitute a full accessibility certification.
- `.venv\Scripts\python.exe -m scripts.frontend_smoke`: **26 checks passed**.
- `.venv\Scripts\python.exe -m scripts.workbook_demo`: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.
- `.venv\Scripts\python.exe -m scripts.evaluate`: **3 cases, zero failures**, extractive-baseline provider.
- `.venv\Scripts\python.exe -m compileall -q app scripts tests`: passed. `git diff --check`: passed, with existing Windows line-ending notices.

The browser harness owns a marked temporary directory/database; the reset helper checks its prefix, ownership marker and resolved database location before clearing only fixed workflow tables. It never uses the user's application database and exposes no reset API. Tests use one worker, zero retries, a 60-second per-case bound, three-minute suite deadline and four-minute runner timeout; server readiness has a 15-second deadline. Traces/video/screenshots stay disabled. Existing live servers and data were preserved.

`.github/workflows/ci.yml` retains backend regressions/evaluation/demo, workbook demo, frontend build/unit checks and HTTP smoke. It now installs Chromium/system dependencies and runs the full browser harness, with five-minute install/browser steps and a 15-minute job bound. Workflow configuration was reviewed; GitHub-hosted CI, Linux system dependency installation, Docker/container checks and deployment were not run and remain unverified. There were no live paid model calls, customer communications, pushes or publishing actions.

USER_GUIDE.md now includes Windows/macOS/Linux startup, explicit sample mappings/cells/counts, supported-format/limit details, keyboard use, conflict/retry behavior, browser download/receipt meaning and dependency/connection troubleshooting. FRONTEND.md and README link the guide and current gate.


## T07 evidence lifecycle and enterprise access ? 2026-10-12

Implemented additive schema migration, immutable evidence payloads and dependency snapshots, lifecycle/expiry invalidation, current tenant memberships and document ACLs, RS256 OIDC API access-token verification, verified reviewer attribution, minimal append-only audit records, and operator bootstrap/backup/restore. Existing local synthetic behavior remains available; non-local deployments require OIDC and cannot recover local keys. Frontend bearer sessions remain in memory with no automatic bootstrap. Legacy evidence is migrated as pending in managed access mode.

Actual local checks:

- `.venv\Scripts\python.exe -m pytest -q`: **86 passed**, one upstream Starlette/httpx deprecation warning. Coverage includes signed-token rejection, tenant isolation, author/reviewer/admin enforcement, immutable versions/audits, current source ACLs, reviewer role revocation, invalidation on updates/revoke/expiry/delete, redaction, upload bounds/control characters, legacy migration and backup/restore integrity.
- Frontend unit suite: **70 passed**; production build/type check passed.
- Local browser harness: **15 passed in Edge**. Signed OIDC browser harness: **2 passed in Edge and 2 in Chromium**, using ephemeral RSA signatures and the unchanged production verifier. Browser checks cover evidence creation/approval, immutable update invalidation, redraft/reapproval, real export inspection, ACL removal, cross-tenant isolation and membership revocation. No live identity provider was contacted.
- HTTP proxy smoke: **26 checks passed**. Workbook demo: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.
- `pip check`: no broken requirements. Python compileall and `git diff --check` passed.

CI now includes the signed OIDC browser profile; hosted CI/Linux/container execution was not performed. Live IdP/SSO/refresh and deployed operation remain unverified. Upload parsing is bounded UTF-8 plain text only. Deletion is a retained tombstone; physical purge/retention scheduling is not implemented. Audit records are append-only through application/schema controls, not external tamper-proof storage. Backup restore creates a new destination and preserves revoked access; operators must reconcile revocations since the backup before serving restored data. Configuration and operational limits are documented in docs/ACCESS.md. T08 was not started.


## T08 scoped MCP server ? 2026-10-13

Pinned the official Python MCP SDK at 2.3.0 after checking official server/client documentation and available package versions. Implemented stdio transport with one host-bound OIDC principal/tenant per process, reverified on every call. SDK-generated input schemas constrain queries, IDs, pagination and CAS revisions. Structured output contains bounded exact evidence quotes and immutable version/hash provenance. Search filters live ACLs before scanning at most 100 current approved versions, checks expiry/reviewer authority and reports scan truncation. Questionnaire reads and CAS draft edits reuse existing scoped services. Draft submission retains existing citations and creates a new unapproved revision; approval/admin/export are not MCP capabilities. Added `python -m scripts.mcp_client` for actual stdio discovery/invocation without printing tokens or customer evidence.

Final validation: `python -m pytest -q` **97 passed**, including **11 MCP cases** covering real SDK protocol discovery/invocation, subprocess stdio, tenant isolation, ACL redaction, pending/expired/revoked/deleted/superseded evidence, reviewer/membership revocation, expired tokens, role rejection, CAS conflict, bounded input validation, absent approval tools, ignored extra identity arguments retaining server scope, safe storage failure and local-mode denial. `pip check`: no broken requirements. `compileall -q app scripts tests` and `git diff --check` passed. SDK v2 required typed mappings for structured outputs and `.tools` on discovery results; final tests use these current interfaces.

No frontend behavior changed in T08; no additional browser validation was needed. Existing CI pytest includes the MCP protocol/subprocess tests. Hosted CI, live IdP, third-party MCP host and HTTP/OAuth discovery transport remain unverified/not implemented. This is bounded deterministic lexical search; hybrid retrieval and agent orchestration remain T09/T10. No paid calls, external messages, commits, pushes or deployments were performed.


## T09 retrieval and model-provider foundation ? 2026-10-13

Implemented packaged PostgreSQL/pgvector migration, exact cosine and PostgreSQL full-text rankings, reciprocal-rank hybrid fusion and optional lexical reranking. SQLite remains the authoritative identity/evidence/questionnaire store; the PostgreSQL index is disposable derived data. Authorization, reviewer authority, lifecycle and applicability are applied before embedding/model exposure. Exact chunks retain source/version/hash, character offsets and line/section provenance. Profiles bind embedding identity/dimensions/chunking, corpus snapshots bind authorized chunk sets, and index IDs are checked against authoritative chunks. Added strict extractive structured claims, deterministic embedding/draft fakes, a trusted HTTPS gateway adapter, bounded budgets, ordinary retrieval API and opt-in integration with persisted drafts/questionnaire revisions/MCP. No human approval capability was added.

Actual validation:

- Full suite with `EVIDENCEDESK_TEST_RETRIEVAL_DSN` enabled: **121 passed**, including **24 retrieval cases**. There were no skipped PostgreSQL tests in the final run. Cases cover all three retrieval modes, locations/profile separation, applicability and unauthorized-provider input, updates/revoke/delete/expiry/reviewer/member changes, poisoned index IDs, malformed vectors/model output, invented IDs/quotes/prose, synthetic conflict/instruction abstention, provider failures/deadline, corpus bounds, API role/input checks, persisted dependency invalidation and MCP/questionnaire foundation integration.
- Real PostgreSQL **18.0** plus pgvector **0.8.7** was tested locally. Because no Docker/PostgreSQL runtime was installed, an owned temporary portable PostgreSQL archive was obtained from EnterpriseDB and official pinned pgvector source was compiled using the existing Visual Studio toolchain. The synthetic cluster used a generated password and an unused loopback-only port, without creating a system service. Real SQL migration repeatability, lexical/vector/hybrid queries, tenant/profile exclusion, failed-rebuild transaction rollback, ACL revocation and physical derived-index purge passed. The test cluster was stopped and its owned temporary runtime/data/password removed afterward.
- Real local HTTP gateway fixture exercised both `/embed` and `/draft`, model identity and secret-header handling; no live paid provider was contacted. Unsupported output schemas/citations fail rather than falling back.
- Four-case ablation ran on **both memory and PostgreSQL**. Recall@3 and nDCG@3: lexical **0.75**, embedding **1.0**, hybrid **1.0**, hybrid plus lexical reranking **1.0** (denominator 4 each). Fixture synonyms deliberately enable the synthetic embedding case; no improvement from reranking was measured. These metrics validate adapters, not learned semantic retrieval or production quality. Exact versioned reports are in `evals/retrieval_ablation.json`; regenerate with `python -m scripts.retrieval_evaluate` / `--postgres`.
- `pip check`: no broken requirements. `compileall -q app scripts tests` and `git diff --check` passed. Existing extractive evaluation: **3 cases, zero failures**. Workbook demo: **5 imported, 3 approved exported, 2 unresolved, source unchanged**.

CI now provisions pinned pgvector/PostgreSQL and runs the real gate plus ablation. Hosted CI/Compose execution and live paid models remain unverified. Frontend behavior is unchanged; no new browser gate was run for T09. Defaults retain baseline drafting; foundation requires explicit configuration and OIDC. This is bounded synchronous retrieval with 64-dimensional embeddings, 20-second cooperative phase deadlines, conservative fixture checks and strict exact-quote output. Arbitrary semantic entailment, robust injection/contradiction verification, hard cancellation, durable checkpoints and agent loops remain T10. Derived historical corpora retain copied text until operator purge; they cannot be selected through scoped API/tool queries. See docs/RETRIEVAL.md for configuration, provider gateway contract, retention and concurrency limits. T10 was not started.


## T10 durable bounded LangGraph workflow ? 2026-10-13

Pinned LangGraph 1.2.15, checkpoint 4.3.0 and SQLite checkpointer 3.1.2 after checking official persistence/interrupt/reference documentation. SQLite migration 003 adds immutable inputs, phase/call ledgers, budget counters, leases and one active job per item. Actual graph nodes perform classify ? retrieve ? assess ? draft ? verify ? human review with static phase checkpoints, a dynamic human-review interrupt, bounded refinement and classified retry routing. Publication and its receipt/dependencies are atomic with one unapproved revision; replay reads completed ledgers instead of repeating external calls or revisions. Current source/reviewer permissions and verified human approval are rechecked before completion.

Actual checks:

- `python -m pytest -q`: **140 passed, 2 skipped** in the final complete run. The skipped tests are the optional real PostgreSQL retrieval/workflow gates because this turn had no running PostgreSQL instance; CI provisions pgvector and enables both. Existing PostgreSQL retrieval was verified in T09. T10 has **20 passing workflow cases** plus its one skipped SQL integration case. Tests cover signed/API identity, original-author membership, tenant/owner enforcement, redaction, all assessment outcomes, invalid claims, immutable/reserved budgets, bounded retries across restart, source changes, CAS conflict, real worker cancellation, hard timeout, committed-call/publication checkpoint gaps, unknown-call nonreplay and real Python-process restart with checkpoint privacy inspection.
- The first final full run caught a leaked SQLite connection in the checkpoint-inspection test, whose resource warning was mistakenly captured by the existing XLSX feature-warning guard. The test connection now closes explicitly; the complete rerun passed. Production checkpointer/control connections also close explicitly.
- Frontend: **73 tests passed**, production build/type check passed. New UI tests cover role separation, unapproved workflow results and stable request keys/budgets after a lost creation response. Test workers are bounded to two after this host's larger fork pool hit startup timeouts. New assertions use the repository's configured matchers.
- Actual signed OIDC workflow browser: **1 passed in Edge**, executing real graph/API publication from revision zero, confirming no approval, using the separate verified reviewer action, then finishing without another revision. Existing production-mode signed OIDC lifecycle/access browser: **2 passed in Edge**. Workflow fixtures explicitly use local deployment + memory index and deterministic providers with real RSA verification; they do not weaken the original production OIDC profile. Browser storage remains empty.
- Existing local browser regressions were rerun separately after a concurrent-load attempt passed 14 cases but reached the fixed 180-second suite deadline before the last case. Final standalone results are recorded below.
- HTTP/proxy smoke: **26 checks passed**. Workbook demo: **5 imported, 3 approved exported, 2 unresolved, source unchanged**. `pip check`: no broken requirements. `compileall -q app scripts tests` and `git diff --check` passed.
- `python -m scripts.workflow_evaluate --output evals/workflow_results.json`: **4 cases, zero failures**, all citation/reason/fixture-answer checks pass, no automatically approved revisions and fixture cost **0 USD**. The recorded p50 wall latency is **7852.60 ms**, p95 nearest-rank latency **15097.71 ms**, including spawned-process startup. Answerable uses two reserved provider attempts; missing uses none; conflict/injection use one embedding attempt and no draft call. This small synthetic set is not learned-model quality, production performance or paid-provider cost evidence.

React controls show resource limits, phase receipts, reserved budgets and the current human-review decision; they refresh source-scoped revisions after publication/reload. Unknown creation responses retain their request key and fixed budget; known validation failures permit correction. Cancel writes to a separate durable control DB and kills active local workers. Checkpoint state contains only references and safe primitive/Interrupt data, with pickle fallback disabled and framework tracing off. Protected phase rows may retain copied source text; both SQLite files require coordinated stopped-worker backup/restore and revocation reconciliation.

Limits: 16 phases, up to one retrieval refinement, 1?6 reserved provider attempts, byte-based conservative token units, contracted-price authorization and local worker cutoff <=20 seconds/remaining job deadline. Remote computation/billing may continue after local cancellation; unknown started calls are not replayed. Live gateway calls require explicit opt-in, positive configured price caps and a positive per-job cost authorization. There is no unattended scheduler, free-form semantic proof, general contradiction/injection detector, distributed failover or production readiness claim. Hosted CI, paid providers and PostgreSQL workflow execution were not run locally. WORKFLOWS.md documents startup, APIs, exact recovery semantics, cancellation, provider contracts and retention. T11 was not started.

Final standalone local browser gate: **15 passed in Edge (2.5 minutes)**, within the unchanged 180-second suite deadline. Combined browser validation for T10 is 15 local cases, 2 production-mode signed OIDC lifecycle cases and 1 local signed workflow case.

Final focused checks also passed for the human-review/publication path and its committed-publication recovery window. Fixture traces distinguish one completed draft-adapter call from zero LLM calls; live vendor-internal counts remain unknown. After readable phase/accessibility label cleanup, the three affected UI cases and production build/type check passed again.

## T10 existing implementation recheck - 2026-10-13

The requested T10 was already implemented and marked verified_local on arrival. Rechecked its existing implementation without changing workflow code: workflow tests 20 passed, 1 skipped in 99.74 seconds; the optional PostgreSQL/pgvector integration test was skipped because no test DSN was configured. Frontend suite: 73 passed across 10 files. Production build and TypeScript check passed. Corrected the stale NEXT_TASKS.md footer that still named T07 as next; T11 remains planned and was not started. This recheck did not run browser tests, hosted CI, or paid providers; the earlier T10 results above remain separate historical checks.

## T11 AutoGen experiment and framework comparison - 2026-10-19

Completed the existing in-progress experiment with actual AutoGen 0.7.5 AssistantAgent researcher/writer/verifier roles, RoundRobinGroupChat and ReplayChatCompletionClient. Offline scoped services reuse T10 assessment and exact citation checks; no answer revision, approval or export is published. The optional dependencies are pinned and CI installs them and runs the comparison. Microsoft's repository and official teams/replay API documentation were checked; AutoGen remains in maintenance mode. Retain LangGraph as primary; AutoGen remains a learning experiment. See docs/AUTOGEN.md.

Initial focused execution found 21 passing and two failing cancellation cases: runtime shutdown waited roughly ten seconds for a sleeping tool. A first fix exposed a runtime drain hang and its test runs were interrupted. The final fix signals the cancellation token before awaiting team shutdown and lets cancelled tool calls return without successful phase receipts, allowing runtime queue acknowledgement. Existing deadline and caller-cancellation tests now pass within their three-second bound; permission/revision/citation/budget failures remain fail closed.

Final checks:

- `python -m pytest tests/test_autogen.py -q`: **23 passed** in 26.53 seconds.
- `python -m pytest -q`: **163 passed, 2 skipped** in 243.45 seconds. Skips are the optional PostgreSQL retrieval and workflow integration tests: no test DSN. AutoGen emits 32 upstream Python coroutine-introspection deprecation warnings; no failing tests.
- `python -m scripts.autogen_compare`: **four cases per framework, zero failures**. Both: 4/4 citation integrity, zero unsupported claims, zero automatic approvals, three embedding calls and one draft adapter call. AutoGen uses 12 replay model-client calls; both use zero real LLM calls and zero paid fixture cost. Report regenerated at evals/autogen_comparison.json.
- Recorded p50/p95 nearest-rank wall latency: LangGraph **8370.40/15441.54 ms**, AutoGen **100.67/116.37 ms**. LangGraph includes durable checkpoints, spawned processes and unapproved publication; AutoGen returns an ephemeral candidate. These timings do not establish an equivalent-work production speedup.
- `pip check`: no broken requirements. `compileall -q app scripts tests` and `git diff --check` passed.

Four deterministic extractive fixtures do not measure learned-model reasoning, semantic entailment or paid-provider performance. No live provider, hosted CI, PostgreSQL or new browser run was performed. No frontend behavior changed. No commits, pushes or deployments were made. T12 remains planned.

## T12 A2A two-service integration - 2026-10-19

Completed verification and documentation of the existing in-progress A2A implementation. Official SDK repository, 1.0 migration guide and pinned 1.1.5 release were checked before completion; references are in docs/A2A.md. SDK protobuf/JSON-RPC discovery, task submission/status/cancellation and provenance artifacts connect an independent evidence expert to a separate questionnaire-agent service and primary LangGraph workflow. Existing backend policy retains human approval and export control.

Checks performed:

- `python -m pytest tests/test_a2a.py -q`: **26 passed** in 29.83 seconds. Covers unauthorized/expired requests, tenant and author isolation, evidence/ACL/membership changes, invalid provenance, duplicate and lost-response submissions, timeout/outage/restart/cancellation, discovery credential redirection, body bounds and actual two-process workflow/human review.
- `python -m scripts.a2a_demo`: **passed**. Two services, A2A 1.0 JSON-RPC, completed workflow, one citation, remote task recorded, automatic approval false, explicit human reviewer decision approved, zero paid calls.
- `python -m pip check`: no broken requirements. Installed a2a-sdk 1.1.5, protobuf 5.29.6, google-api-core 2.25.1, googleapis-common-protos 1.70.0 and proto-plus 1.28.2.
- `python -m compileall -q app scripts tests` and `git diff --check`: passed.

CI installs the A2A extra and now runs the standalone demo in addition to tests. Hosted CI was not executed. The services share authoritative SQLite state and an OIDC audience; no token exchange or replicated database is implemented. One expert process owns task recovery. Finite worker threads may finish after cancellation but cannot publish late results; killed workflow workers leave remote work bounded by the expert deadline. Capacity and unsupported operations are documented. No live provider, live IdP, deployment, frontend/browser work, commit or push was performed. T13 remains planned.

T12 final backend regression (2026-10-19): `python -m pytest -q` completed with **189 passed, 2 skipped** in 176.13 seconds. The two skips are opt-in PostgreSQL gates without a test DSN. The 32 warnings are upstream AutoGen coroutine-introspection deprecations. No failing tests.

## T13 evaluation, observability, resilience and operations - 2026-10-19

Status: `implemented_unverified` for the full M4/M5 task. Local components are tested; full milestone completion remains conditional on external evidence described below. No publishing, paid infrastructure, live model call, customer communication, commit or push was performed.

Implemented:

- Fifty explicitly synthetic/unreviewed cases across ten scenarios, separated into development 20, validation 10 and held-out 20. Gold source IDs, expected facts, applicability, answerability, contradictions and access labels are versioned. Metrics and denominators are defined in OPERATIONS.md. CI enforces fixture quality/integrity thresholds; a seeded invalid-citation check proves the gate rejects failures. These template variants are not independent human-reviewed business evaluation data.
- Content-free HTTP/ingestion/retrieval/model/MCP/A2A/workflow spans, request IDs, job IDs and spawned-worker linkage; numeric/status-only allowlist, failure taxonomy, no raw headers/inputs/outputs/source text; explicit opt-in LangSmith SDK export with empty/hidden inputs and outputs. Real SDK serialization was verified against a local HTTP fixture, not a hosted account. Remote export requires an approved HTTPS endpoint. Trace sink failure cannot change business results.
- Opt-in bounded process-local retrieval-ID cache with database/identity/corpus/version/prompt/model/input scope; authorization and evidence always rechecked. Tests reject stale evidence, revoked permissions, cross-user access, expired entries and capacity overflow. Cache contents are not serialized into spawned workers. No answer/approval cache.
- Two offline extractive-provider experiment, development-set measurements, conservative routing choice, finite deadline, cooldown, policy-preserving fallback and no fallback on invalid claims. Primary workflow rejects the experimental router to prevent bypassing live-provider cost accounting. This does not establish a measured production two-provider deployment.
- Actual DSPy 3.4.1 LabeledFewShot compilation (four demos from 20 development cases) and Predict execution with a rule-derived fake LM. Fixed/compiled validation 10/10 and held-out 20/20; zero paid calls. Retain fixed baseline: fake models do not measure learned-model optimization benefit.
- Generic /ready checks for auth/JWKS/SQLite, runtime dependency lock (65 pins) and target-aware Linux/Python 3.12 CI lock (145 packages, uv 0.13.1), non-root Docker healthcheck/read-only resource-constrained Compose recipes, staged OIDC configuration and explicit rollback/backup runbook. CI adds release, routing/optimization, restore, scan and real container smoke/restart gates without deployment credentials.

Actual local results:

- `python -m scripts.release_evaluate --split validation --output evals/release_validation.json`: 10/10 correct, no failures.
- `python -m scripts.release_evaluate`: 20/20 held-out correct, 20/20 citation integrity, zero unsupported claims, unauthorized evidence or automatic approvals. Recall@5/nDCG@5=1.0 over six gold cases; abstention recall 16/16; answerable coverage 4/4; contradiction detection 2/2. Four draft adapter calls, paid cost zero. Latest p50/p95 service latency and dataset hash are in evals/release_results.json. Reviewer edits/time remain null, not fabricated zeros.
- `python -m scripts.optimize_classifier`: real DSPy compile and fake-model execution passed; report evals/optimization_results.json.
- `python -m scripts.routing_compare`: both adapters 20/20 on development cases, zero unsupported/unauthorized evidence; provisional latency-ranked choice recorded, no production adoption. Report evals/routing_results.json.
- `python -m scripts.operations_check`: SQLite integrity/migration reapply passed, original backup marker retained and candidate write removed on restore; 80 in-process ASGI health requests at concurrency four, zero failures. Timings in evals/operations_results.json. Proposed RPO 60 minutes/RTO 30 minutes are operator objectives, not production guarantees. No checkpoint-sidecar coordinated backup or image rollback was exercised.
- New operations tests initially 14 passed, then expanded to 18 passed after real SDK serialization, evaluation-gate negative test, split labels and live-budget bypass checks. Intermediate focused protocol/operations run: 51 passed. Workflow/operations recheck: 34 passed, one optional PostgreSQL skip.
- Frontend production build/typecheck passed; 73 frontend tests passed. `python -m scripts.frontend_smoke`: 26 real HTTP checks, zero failures. No new browser journey was needed for these backend/operations changes.
- Initial dependency audit found 14 advisory entries across three packages (including duplicates). Upgraded PyJWT 2.14.0 -> 2.15.0 and python-multipart 0.0.22 -> 0.0.32; official release references are in OPERATIONS.md. `pip check` passes. Runtime lock audit finds no known vulnerabilities. Full local/CI learning scan retains one distinct DiskCache advisory (PYSEC-2026-2447 / GHSA-w8v5-vhqr-4h9v), with no fix listed; optimizer disk caching disabled and package excluded from runtime. The learning audit tolerates only this explicitly recorded offline exception and fails on new or unscanned findings. Reports in evals/runtime_audit.json, evals/dependency_audit.json and evals/learning_audit.json.
- Runtime wheel availability for Python 3.12 Linux passed with pip --no-deps target options. An initial cross-target pip dependency dry run evaluated Windows markers and failed on pywin32; the actual CI dependency set was then resolved successfully with uv's explicit Linux target. No Linux installation/container execution is claimed.
- `compileall -q app scripts tests`, YAML parsing and `git diff --check` passed.

Outstanding M4/M5 evidence: human-reviewed/calibrated evaluation and real review edits/time; a learned-model comparison and measured eligible live-provider routing/cost/residency; Docker image build/smoke/security scan and actual staging promotion/rollback. Docker was absent from PATH, and no approved staging target/reviewed dataset was supplied. Hosted CI, remote LangSmith account, container/OS image scans and staging rollback were not executed locally. The prepared scripts/runbook make those remaining steps reviewable, but T13 is not marked complete from synthetic substitutes.

T13 final backend regression (2026-10-19): **207 passed, 2 skipped** in 208.41 seconds, with local content-free tracing enabled. Skips are optional PostgreSQL integrations (no test DSN); 32 warnings are upstream AutoGen deprecations. Trace summary: 672 spans, 90 linked children, 136 job spans; all event/metric keys passed the allowlist inspection. See evals/trace_results.json.

T13 user scope confirmation (2026-10-19): The user selected "Use local synthetic validation; keep external gates explicit". Status is now `verified_local` for the agreed local synthetic scope using the existing recorded results; no new execution or external validation is implied. Human-reviewed evaluation/reviewer metrics, live-provider validation and actual Docker/staging rollback remain pending M4/M5 gates. No deployment or production readiness is claimed.
