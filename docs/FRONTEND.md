# React frontend - evidence, workbook review and export

T01 implements React/TypeScript/Vite navigation and local API connection. The frontend now obtains a key automatically in explicitly enabled local-development mode; manual entry remains a fallback. T02 adds the saved-questionnaire dashboard and evidence form; T03 adds browser workbook inspection, explicit mapping, preview and import. T04 adds bounded drafting, citations, revision-aware editing and explicit approval. T05 adds ZIP downloads with authoritative snapshot receipts and unresolved reports. T06 adds complete UI-only sample journeys, basic keyboard/axe checks and the bounded CI browser gate. For the end-user flow, see [USER_GUIDE.md](USER_GUIDE.md). The existing backend API workflow remains available.

## Start locally on Windows

Use Node 24 LTS (tested with 24.20.0). The locked toolchain supports Node 22.13+, 24+, or 26+. Use `npm.cmd` in PowerShell if execution policy blocks `npm.ps1`; no execution-policy change is needed.

Terminal 1, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
$env:EVIDENCEDESK_ALLOW_LOCAL_FRONTEND='1'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Restart an already-running backend to load the new local session-key endpoint and setting. Use a single-worker loopback server. Automatic frontend connection does not require enabling the older key-rotation/recovery API.

Terminal 2, from the repository root:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. The app obtains a local key and authenticates automatically; there is no copy/paste step. Restart Vite after upgrading to load the new bridge. If automatic mode is disabled, the UI explains the setting and offers manual key entry. On macOS/Linux use the corresponding Python virtual-environment executable and `npm` instead of `npm.cmd`.

## What to test as a user

1. Open the app with automatic mode enabled. Expect the backend tenant and an authenticated connection indicator without typing a key. Health alone does not authenticate the session.
2. Disconnect, then try a wrong key through the manual fallback. The app should show an error and remain disconnected. Select Connect automatically to recover access without pasting a key.
3. Use Questionnaires to browse saved imports or import a workbook. Evidence accepts legacy plain text. Open a saved questionnaire and select Review answers to draft, edit and approve.
4. Disconnect. The key and session details are cleared; automatic reconnection is available through the button, but does not immediately undo your disconnect action.
5. Refresh the page. It reacquires the current key automatically; nothing is saved to localStorage, sessionStorage, cookies or URLs. Another tab gets the same current key, without invalidating the first tab.
6. Stop the backend, then connect. A network/connection error should appear. A connection attempt can be cancelled and times out after 15 seconds.
7. Use keyboard Tab/Enter to reach navigation, the connection form and the skip link; resize the window to check the stacked mobile layout.

Explicit key rotation/restarting the backend may invalidate an existing key. Refresh or select Connect automatically to obtain the current one. An existing connected indicator records the successful connection check; continuous background session monitoring is not implemented in T01.

## API and configuration

The UI uses relative `/api/...` requests through the Vite development proxy. The default upstream is `http://127.0.0.1:8000`. For a different backend port, copy `frontend/.env.example` to `frontend/.env.local`, update the non-secret `EVIDENCEDESK_API_TARGET` origin and restart Vite. The client cannot select an arbitrary remote endpoint from the connection form.

`GET /session` requires `X-API-Key` and returns only the server-derived tenant, mode and local authentication type. It does not read/write a database or return the secret. Backend authentication remains local-only; enterprise identity is T07.

The typed API client supports JSON, FormData uploads with optional idempotency headers, and binary downloads with sanitized filenames. It normalizes both legacy `detail` errors and structured `error.code/message` errors, treats non-JSON/network failures safely and preserves request cancellation. Redirects are rejected to avoid forwarding keys elsewhere. The app stores keys only in its in-memory API client and clears them on failed connection, disconnect or unmount.

The ordinary proxy permits API routes and explicitly blocks `/api/local/api-key`, `/api/local/session-key`, encoded/traversal paths and arbitrary routes. A separate development-only `POST /dev/session-key` bridge checks a direct loopback peer, local Host, matching browser Origin, explicit `X-Local-Session: true` header and same-origin fetch metadata when present. It rejects forwarded requests. The bridge makes a fresh direct server-to-server request to the loopback backend's `POST /local/session-key`, without forwarding browser credentials or proxy headers.

The backend session-key API is disabled unless `EVIDENCEDESK_ALLOW_LOCAL_FRONTEND=1`; it requires direct loopback, an explicit local-session header and no forwarded/cross-origin headers. It returns the configured/current key, or generates one if none exists. It never rotates a valid key on refresh, and serializes first-key generation. Both responses are non-cacheable. Ordinary proxied requests carry forwarding headers and cannot access local bootstrap/recovery endpoints. No permissive backend CORS setting was added. Both development servers bind to loopback. Enable automatic mode only for your own local synthetic-data instance; enterprise sessions remain T07.

Never store keys in frontend environment variables, especially `VITE_*` values; those are included in browser bundles. No external fonts, analytics or image requests are needed by this shell. Production hosting/routing is not configured; the built app expects a future same-origin `/api` gateway. Automatic key acquisition exists only in the Vite development server, not preview or deployed builds. Vite's development or preview server is not a production deployment.

## Checks

From `frontend/`:

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.frontend_smoke
```

The smoke script launches its own FastAPI and Vite processes on temporary loopback ports, creates a random in-memory key, uses an isolated database path, checks the real HTTP proxy/authentication boundary and stops only the processes it started. It leaves existing servers, keys and databases untouched. It is not a browser automation test. The separate T03 browser gate below verifies workbook import; the complete UI-only browser journey now runs through the separate T06 harness.

Official setup/configuration references checked for this task: [React from scratch](https://react.dev/learn/build-a-react-app-from-scratch), [Vite guide](https://vite.dev/guide/), [Vite proxy configuration](https://vite.dev/config/server-options.html#server-proxy), [Vite environment variables](https://vite.dev/guide/env-and-mode.html), [Vitest guide](https://vitest.dev/guide/). Exact direct versions and the resolved dependency graph are recorded in `frontend/package.json` and `frontend/package-lock.json`.


## T02 dashboard and evidence entry

After connecting, Questionnaires automatically loads the current tenant's saved imports, twenty per page. Use Previous/Next page, Refresh questionnaires, and Open to retrieve a saved questionnaire summary. Reconnect after a page refresh to load persisted imports again. Empty lists are expected until a workbook has been imported. Browser upload is available above the dashboard; select Review answers after opening a saved questionnaire.

Evidence provides legacy plain-text entry: title (300 characters), text (100,000), version (100), and an ISO expiry date. Use synthetic data in this local phase. Saving returns a document ID and clears the form only on success; errors preserve entered text. Evidence approval/revocation and immutable version uploads remain T07. Disconnect clears the displayed tenant data.

`GET /questionnaires?offset=0&limit=20` returns `items`, `total`, `offset`, `limit`, and `next_offset`. Each summary contains only `id`, safe `filename`, `status`, `created_at`, and `total` item count. Offset is nonnegative; limit is 1-100, default 20. Ordering is newest creation first, with ID as a deterministic tie-breaker. Concurrent imports may shift offset pages; refresh to reload. This endpoint excludes workbook bytes, mapping internals, keys and other tenants.

The smoke script now also seeds isolated synthetic questionnaire fixtures and verifies dashboard/evidence requests through the actual proxy (26 checks). The current frontend suite has 67 tests; T06 adds the full UI-only browser journeys. See VALIDATION.md for the actual latest results.


## T03 workbook upload, mapping and preview

1. Connect and open Questionnaires. Choose an ordinary `.xlsx` file, then select **Inspect workbook**. The app reads the authenticated server upload limit before sending workbook bytes, and displays server format/package/mapping errors. No sheets or column roles are chosen for you.
2. Inspect sheet names, visibility, row counts and expandable candidate columns. Samples come from row 1 even when the real header is later in the sheet. Check **Map** for each intended sheet, enter its header row and distinct question/answer Excel letters, and optionally enter an identifier column.
3. Hidden rows are skipped and existing answers preserved by default. Select inclusion explicitly for hidden rows/sheets. Overwrite intent permits replacing literal answers only after later human review/approval; formula destinations are rejected regardless of this choice.
4. Select **Preview mapped questions**. Check total count, source/destination cells, identifiers, destination behavior and warnings. The backend returns at most 100 preview rows; all mapped questions are imported. The UI shows the first 100 warnings and reports when more exist. Mapping edits remove the old preview and require another preview.
5. Select **Confirm import** to persist the workbook. Success displays the questionnaire ID and refreshes the dashboard. Confirm again after a failed request to retry the same payload with its retained in-memory idempotency key. A conflict is displayed explicitly. Editing the mapping/file or selecting **Start another import** creates a new request; intentionally importing again can create another questionnaire. Resetting or leaving the page drops an unsaved file and retry key. If a response was lost before leaving, check the dashboard before starting another import.

The file is held only in component memory, never browser storage. Disconnect or navigation unmounts the importer and aborts pending requests; success releases the file. The backend retains the immutable original on confirmed import. The review workspace is available through the saved questionnaire; download its export bundle from the review workspace.

### Sample mappings

Keep hidden inclusion and overwrite unchecked for these fixtures:

| Workbook | Sheet | Header row | Question | Answer | Identifier |
|---|---|---:|---|---|---|
| `samples/security.xlsx` | Security | 1 | B | C | A |
| `samples/security.xlsx` | Operations | 1 | A | B | empty |
| `samples/rfp.xlsx` | RFP | 3 | B | C | A |
| `samples/rfp.xlsx` | Operations | 1 | A | B | empty |

Each imports five items. Security uses B2 to C2, B3 to C3, B5 to C5, B6 to C6; RFP uses B4 to C4, B5 to C5, B7 to C7, B8 to C8. Both also use Operations!A2 to B2. Existing-answer preservation and hidden-row warnings are expected. Leave Internal unmapped unless you explicitly want that hidden sheet.

### Focused real-browser gate

After installing frontend dependencies, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.workbook_browser
```

This starts isolated FastAPI/Vite servers on temporary loopback ports and uses headless Edge on Windows. It populates only a temporary synthetic database and terminates its own servers. Playwright 1.64.0 is pinned in the lockfile. On other platforms install the matching Chromium with `npx playwright install chromium` from `frontend/` first; set `EVIDENCEDESK_BROWSER_CHANNEL` to use another already-installed Chromium channel. The script accepts Playwright arguments such as `--grep`. API keys remain in memory; traces/video/screenshots are disabled. This fifteen-case gate covers both sample imports, refresh/reopen, warnings/hidden intent, format/size errors, import retries/conflicts, the four T04 review cases below, the three T05 export cases, and complete UI-only journeys for both samples plus invalid-key recovery. It is configured in CI with Chromium.

Runner/channel behavior was checked against [Playwright browser documentation](https://playwright.dev/docs/browsers).


## T04 drafting and answer review

Open a saved questionnaire on Questionnaires and select **Review answers**. Review then shows that questionnaire in pages of 20 items, including original sheet/row/identifier/cells, saved answer, current revision and approval record.

Select **Draft remaining items** to process undrafted items in batches of 25. Progress reports remaining items; the run stops at completion, no progress, 201 batches or two minutes. Failures remain visible after the items refresh. Resume to process the remaining undrafted items; existing revisions are skipped. **Stop drafting** aborts the browser request. A batch already received by the backend may finish, so the UI reloads and offers remaining work. Drafting never approves answers.

Each drafted item shows source quotes, document titles/IDs and versions. Compare those quotes with the question and saved answer; extraction and human review do not independently verify factual correctness. Missing-evidence items cannot be approved. Assign an owner through **Owner label** and **Save new revision** when needed; owner-only changes also create a revision. Adding evidence does not automatically redraft existing revisions. Preserved destinations remain unchanged on export even when their draft is approved.

Edit **Answer text** or its optional owner and select **Save new revision**. The request includes the revision you edited. A saved edit always requires a new approval, including edits to previously approved answers. Enter a **Reviewer label (unverified)** and optional approval reason, then explicitly select **Approve revision N** after checking that revision. The backend checks the current revision and evidence and records the approval; the UI never retries an approval automatically. Labels are caller-supplied in this local prototype; verified identities remain T07. An approval display records the saved review decision; the backend rechecks evidence again on export.

If another reviewer changes the answer, the save/approval fails with a revision conflict. **Reload current item** fetches the saved answer without replacing local text. Compare saved text/owner with your unsaved edits. Select **Keep my edits against revision N** to deliberately save your proposed text against the new revision, or **Discard local edits** to use the saved answer. A failed or uncertain save/approval response blocks further mutation until a reload checks the actual saved revision. If an approval was already saved, reloading shows it and keeps approval disabled.

Unsaved edits stay in memory across item pagination, page reload within the review workspace, and workspace tabs. Switching to a different questionnaire, disconnecting, or refreshing the browser clears them. Requests are aborted when the review workspace is removed. Use the T05 export panel below the review toolbar to download the approved-current snapshot.

The browser harness adds four review acceptance cases using synthetic fixtures: citation/edit/reapprove/missing evidence/preserved destinations; a genuine competing revision edit; a genuine dropped approval response after server commit with one approval request; and interrupted drafting of 45 items, resumed in bounded batches with pagination/tab edit retention. It uses the same command above; `--grep review` runs just these cases. The browser gate also checks real export downloads; the complete UI-only evidence/import/review/export journeys and CI configuration are included in T06.


## T05 export and download

In the review workspace, select **Download export bundle**. No additional approval is performed: the backend includes only the approved current revision for a writable destination with still-valid evidence. Edited saved answers are excluded until reapproved; preserved existing answers and formulas remain unchanged. Save or discard all local edits first, including edits on another item page. Resolve uncertain save/approval results with item reload before exporting.

The ZIP contains three files:

| File | Contents |
|---|---|
| `completed.xlsx` | Original workbook with eligible approved answers in mapped cells |
| `unresolved-items.csv` | Excluded items with their question, destination, owner and reason |
| `manifest.json` | Selected revisions/cells, unresolved snapshot, source/output checksums and export timestamp |

The app displays **Browser download started** after it receives a nonempty ZIP response and dispatches the browser download. Check browser downloads to confirm where it was saved. Filenames are sanitized and forced to `.zip`; the temporary Blob URL is released after a one-second dispatch delay. No API key is put in a download URL, and downloaded bytes are not stored in browser storage. [MDN documents object URL lifetime and cleanup](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Schemes/blob).

After receipt, the app fetches paginated counts and unresolved rows for that specific server export ID. These are the snapshot used to generate the downloaded bundle, not inferred from visible approval badges or the current item page. It shows 20 unresolved rows per page. Receipt reasons include preserved answers, unapproved current revisions and stale evidence. Current review cards stay available below the receipt to resolve work. The receipt keeps the export-time question/destination/owner/reason when later edits occur; download again for a new snapshot.

A failed export starts no download and offers an explicit retry, generating a new export. The server may have recorded an export even when a response was lost; a retry does not deliver anything to a customer. A receipt read failure does not undo an already received ZIP: **Reload export receipt** retries only metadata. The ZIP manifest and unresolved CSV remain authoritative. Historical export receipts return accurate counts but indicate unavailable details; use their original CSV rather than reconstructed current owner/reason values.

The T05 browser gate saves and inspects actual ZIP downloads from security and RFP fixtures, checks every original cell outside the selected destinations (including existing answers/formulas), and verifies manifest checksums and CSV unresolved reasons. Security additionally exports before editing, after saving an unapproved edit, and after reapproval. Both samples produce three applied answers and two unresolved items in the approved fixture; the saved unapproved edit produces two applied and three unresolved. Export/receipt error recovery is also covered. The focused export cases prepare fixtures through the API. T06 adds separate complete UI-only journeys and CI browser checks. Run the same browser command above, or add `--grep export` for these three cases.


## T06 end-to-end gate and user guide

[USER_GUIDE.md](USER_GUIDE.md) provides the local install/start commands, complete sample walkthrough, expected cells/counts, supported formats, keyboard/conflict steps and troubleshooting.

The harness now runs 15 sequential browser cases. Its two sample journeys create evidence and import/map workbooks through the UI, then draft, inspect citations, edit, approve and save/inspect real ZIP downloads. They use no API fixture preparation. Keyboard checks cover the skip link, navigation, evidence fields, mapping controls and save/approve/download actions. Axe 4.13.0 checks WCAG 2 A/AA and 2.1 A/AA tagged rules on connection, evidence, mapped preview, review and receipt screens, plus invalid-key error/recovery. Contrast findings in muted text and connection pills were corrected; focus outlines were darkened. Automated checks are not a complete accessibility certification.

Each case resets only the marked temporary SQLite database owned by the harness. `scripts.browser_fixture` verifies the directory prefix, ownership marker and resolved database location before resetting rows; tests verify that unowned/sibling databases stay intact. API keys remain process-local; no reset route was added to the application. Existing servers and their databases are untouched. Tests use one worker, no retries, a three-minute suite deadline, four-minute runner timeout and 15-second startup deadline. Traces/video/screenshots remain off.

CI installs pinned Chromium plus system dependencies and runs the same harness after build/unit/backend checks. Browser/install steps are bounded to five minutes and the job to 15 minutes. The backend regressions, sample workbook demo and HTTP smoke checks remain. Local Windows verification uses both installed Edge and locked Chromium; hosted CI/Linux/container execution is separately unverified until actually run.

Official references: [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing), [Playwright CI](https://playwright.dev/docs/ci).
