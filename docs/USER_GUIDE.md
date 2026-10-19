# EvidenceDesk local user walkthrough

This guide covers the synthetic-data React workflow through T06. Drafting uses deterministic evidence extraction; reviewer/owner labels are unverified. For implemented T07 verified identity and evidence lifecycle configuration, see [ACCESS.md](ACCESS.md).

## Install once

From the repository root, with Python 3.11+ and Node 24 available:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm.cmd --prefix frontend ci
```

If `.venv` already exists, use its interpreter and skip creation. PowerShell users can use `npm.cmd` directly without changing execution policy. Sample workbooks and mappings are included in `samples/`; regenerate them only when needed with `python -m scripts.sample_workbooks`.

On macOS/Linux use `python3 -m venv .venv`, `.venv/bin/python`, and `npm` in the equivalent commands.

## Start the two local servers

Terminal 1, from the repository root:

```powershell
$env:EVIDENCEDESK_ALLOW_LOCAL_FRONTEND='1'
$env:EVIDENCEDESK_DB='walkthrough.db'
$env:EVIDENCEDESK_TENANT='walkthrough'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Choose a separate database filename for your walkthrough if needed. The server persists documents/questionnaires there across restarts. Run one backend worker for the process-local automatic key bridge.

Terminal 2, from the repository root:

```powershell
Set-Location frontend
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. The app checks API health and authenticates a local key automatically. Keys stay in memory and are reacquired on refresh; refreshes do not rotate another tab's key. A masked manual key fallback is available. If the local bridge was just enabled or the app upgraded, restart both servers.

On macOS/Linux set the same environment variables with `export`, start `.venv/bin/python -m uvicorn ...`, and use `npm run dev` from `frontend/`.

## Complete a sample questionnaire

1. Confirm **Your workspace is connected**. Select **Evidence** and enter:

   | Field | Value |
   |---|---|
   | Title | Synthetic security policy |
   | Plain text | Customer data is encrypted at rest using AES-256. Transport encryption uses TLS 1.2 or higher. |
   | Version | 1 |
   | Expiry date | 2099-01-01 |

   Select **Save evidence**. Success shows the document ID and clears the form; a failed save keeps the entered text.

2. Select **Questionnaires**, choose `samples/security.xlsx` or `samples/rfp.xlsx`, and select **Inspect workbook**. Inspect sheet visibility and row-1 samples. No sheet or mapping is selected automatically.

3. Check **Map** for the two intended sheets and enter the matching values:

   | Workbook | Sheet | Header row | Question column | Answer column | Identifier column |
   |---|---|---:|---|---|---|
   | security.xlsx | Security | 1 | B | C | A |
   | security.xlsx | Operations | 1 | A | B | empty |
   | rfp.xlsx | RFP | 3 | B | C | A |
   | rfp.xlsx | Operations | 1 | A | B | empty |

   Leave Internal unmapped, hidden inclusion unchecked, and overwrite unchecked. Hidden rows are skipped; existing answers are preserved. The RFP's real header is row 3 even though inspection samples show row 1.

4. Select **Preview mapped questions**. Expect **5 questions total** and exact source/destination cells. Existing-answer preservation and a skipped hidden row are expected warnings. Check the preview, then select **Confirm import**. Success shows the questionnaire ID and refreshes the saved list. If import failed after a lost response, Confirm retries the same payload with the same request key. Editing the mapping or starting another import creates a new request.

5. Open the saved workbook and select **Review answers**. Select **Draft remaining items**. Drafting runs in bounded batches and shows remaining work. It never approves an answer. Inspect question text, sheet/row/identifier, source quotes, document version, revision and destination behavior.

6. For the first encryption answer, edit **Answer text** to a reviewed response supported by the quotes, optionally set an owner, and select **Save new revision**. Saving requires a new explicit approval. Enter a reviewer label above and select **Approve revision 2** after checking that revision. Also review and approve the second encryption item and Operations' encryption item. These are separate cells even when question text repeats.

   The transport-encryption destination already contains an answer and stays preserved. The biometric question has no supporting evidence and cannot be approved; an owner can be assigned through a saved revision. Adding evidence does not automatically redraft existing revisions.

7. Select **Download export bundle**. Save or discard local edits first; uncertain save/approval errors require reloading the affected item. The app receives a ZIP and starts a browser download. Check the browser's downloads to locate the saved file.

   | Bundle file | What to inspect |
   |---|---|
   | completed.xlsx | Answers written only to eligible mapped cells; original existing answers/formulas preserved |
   | unresolved-items.csv | Excluded questions, destinations, owners and reasons |
   | manifest.json | Selected current revisions, unresolved snapshot and source/output checksums |

   The receipt displays the backend's actual export counts and paginated unresolved rows. It describes that bundle's export-time snapshot; later edits do not change the downloaded file. Download again to generate a new snapshot.

8. Refresh the browser and reconnect automatically. Open the saved questionnaire again; its imported items, saved answers and approvals persist. Unsaved text, upload files and the on-screen receipt are session-only.

## Expected sample results

With the three writable evidence-backed items approved, each workbook has **5 imported items, 3 applied answers and 2 unresolved items**. The two exclusions are the preserved transport answer and unapproved biometric answer. Approval of a preserved destination still does not make it writable.

| Workbook | Writable encryption destinations | Preserved answer | Missing evidence |
|---|---|---|---|
| security.xlsx | Security!C2, Security!C3, Operations!B2 | Security!C5 | Security!C6 |
| rfp.xlsx | RFP!C4, RFP!C5, Operations!B2 | RFP!C7 | RFP!C8 |

Formulas outside these cells remain unchanged. The hidden row is excluded with the default mapping. Saving another edit after approval excludes that edited destination: the next bundle has **2 applied / 3 unresolved** until that new revision is reapproved.

## Keyboard and conflict recovery

Tab/Shift+Tab move through controls. The first Tab reaches **Skip to workspace**; Enter moves to the main region. Enter activates buttons, Space toggles sheet/options checkboxes, and form inputs have associated labels. Review actions display their revision and approval state.

A revision conflict means another change was saved first. **Reload current item** fetches current saved text/owner while retaining your unsaved text. Compare both, then choose **Keep my edits against revision N** to save intentionally against that revision, or **Discard local edits** to use the saved answer. A lost save/approval response also requires reload so an already-saved action is not duplicated.

Unsaved review edits remain in memory across item pagination and workspace tabs. Browser refresh, disconnect or switching to another questionnaire clears them.

## Troubleshooting

| Symptom | Action |
|---|---|
| `npm.ps1` execution-policy error | Use `npm.cmd` in PowerShell |
| Unsupported Node/toolchain or dependency errors | Check `node --version`; use Node 24 and rerun `npm.cmd ci` in frontend/ |
| Python module not found | Use the repository virtual-environment interpreter and install `.[dev]` from the repository root |
| Automatic connection disabled | Set EVIDENCEDESK_ALLOW_LOCAL_FRONTEND=1 before starting the backend; restart both servers and use the development app on port 5173 |
| API unavailable or connection timeout | Check the backend terminal and /health; confirm the loopback port. For a different port, copy frontend/.env.example to frontend/.env.local, set the non-secret EVIDENCEDESK_API_TARGET origin, and restart Vite |
| Invalid or stale API key | Select Connect automatically again. If using manual entry, use the current backend key; key rotation/server restart can invalidate older keys |
| Port already in use | Stop the server you started or choose another port and update the frontend API target |
| Unsupported workbook | Use ordinary unencrypted .xlsx. .xls/.xlsm, macros, external links, tables, drawings and other unsupported package features are rejected; see WORKBOOKS.md |
| Invalid mapping or hidden-sheet error | Use distinct Excel columns and an existing header row; check the sample table above and require explicit hidden inclusion for a hidden sheet |
| Upload limit exceeded | The default is 10 MiB; the UI reads the backend's configured limit before sending workbook bytes |
| Missing/expired evidence | Use valid supporting evidence and assign an owner to unresolved items. Approval/export are checked by the backend |
| Receipt unavailable after download | Reload export receipt to retry only metadata. Inspect the already-downloaded CSV/manifest for the actual result |
| Browser executable missing for tests | From frontend/, run `npx.cmd playwright install chromium`, then set EVIDENCEDESK_BROWSER_CHANNEL=chromium before running the harness |

Vite preview/hosted builds do not provide automatic local key bootstrap. Hosted deployment remains separately unverified. Do not put secrets in VITE_* configuration.

## Run the verification gate

From `frontend/`:

```powershell
npm.cmd ci
npm.cmd run build
npm.cmd test
```

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.frontend_smoke
.\.venv\Scripts\python.exe -m scripts.workbook_demo
.\.venv\Scripts\python.exe -m scripts.workbook_browser
```

The browser harness starts temporary loopback servers and uses a marked temporary SQLite database. Each case resets only that owned synthetic database; your app database is not used. Tests are sequential, with no retries, a three-minute browser-suite deadline and a four-minute harness timeout. Server readiness has a 15-second deadline. Traces, video and screenshots are disabled; saved ZIP test artifacts are under ignored frontend/test-results/.

Windows defaults to installed headless Edge. To use locked Chromium, install it as above and set `$env:EVIDENCEDESK_BROWSER_CHANNEL='chromium'`. Linux CI installs Chromium and system dependencies with `npx playwright install --with-deps chromium`, then runs this same harness. The workflow retains backend regressions, the workbook demo, frontend build/unit tests and HTTP smoke checks; browser/install steps have five-minute limits and the job has a 15-minute limit.

Automated axe scans and keyboard assertions check the connection, evidence, mapped preview, review and receipt screens. These are basic automated checks, not a complete accessibility certification. See [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing) and [CI setup](https://playwright.dev/docs/ci).


For verified OIDC sessions and the T07 evidence lifecycle, use [ACCESS.md](ACCESS.md). The synthetic local walkthrough above preserves its legacy API-key behavior; it is not enterprise authentication.

Verified OIDC sessions also expose Agent workflow on each review item. Set resource limits, start bounded drafting, reload saved progress after reconnect, and inspect the resulting unapproved revision before using the ordinary verified reviewer approval. See [WORKFLOWS.md](WORKFLOWS.md) for setup, cancellation and recovery.
