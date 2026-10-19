# Scoped MCP integration (T08)

EvidenceDesk exposes an actual MCP server through the official Python SDK, pinned to `mcp==2.3.0`. It uses **stdio**: one trusted local host launches one server process for one OIDC identity and selected tenant. It opens no network listener. HTTP transport, OAuth discovery/login and hosted MCP deployment are not implemented.

Install from the repository root with `.venv\Scripts\python.exe -m pip install -e '.[dev]'`. Configure the issuer, API audience, public JWKS and database as described in [ACCESS.md](ACCESS.md). Provision current tenant membership and evidence ACLs through that guide. Obtain an API access token through your identity provider; local API keys are not accepted.

For PowerShell, configure the server process environment (keep the token out of committed files and command arguments):

```powershell
$env:EVIDENCEDESK_AUTH_MODE='oidc'
$env:EVIDENCEDESK_TENANT='your-tenant'
$env:EVIDENCEDESK_DB='C:\path\to\evidencedesk.db'
# Set EVIDENCEDESK_OIDC_ISSUER, EVIDENCEDESK_OIDC_AUDIENCE and trusted JWKS.
# Supply EVIDENCEDESK_MCP_TOKEN through your host's secret environment mechanism.
.venv\Scripts\python.exe -m scripts.mcp_client
```

The demonstration launches `.venv\Scripts\python.exe -m app.mcp_server`, discovers all four tools, invokes `search_evidence`, and prints only names/counts. An MCP host uses that same executable, module arguments, working directory and environment. Stdout is reserved for MCP messages. Do not launch this process with a shared admin token for unrelated callers. Tokens stay process-bound; restart with a fresh token after expiry. Signature, expiry, issuer/audience and current membership are checked on each invocation; roles and ACLs come from the database. No token or tenant tool argument can replace the host-bound principal. The SDK ignores unknown argument fields; declared fields are validated, and extra identity fields do not affect scope.

| Tool | Input | Behavior |
|---|---|---|
| `search_evidence` | `query`: 1–5000 characters; `limit`: integer 1–50, default 10 | Lexical sentence overlap over current approved, unexpired, nondeleted versions and live ACL/reviewer permissions; exact quotes capped at 2000 characters with immutable version/hash provenance |
| `get_questionnaire` | `questionnaire_id`: 1–100 characters | Tenant-scoped summary through existing service |
| `get_questionnaire_items` | same ID; `offset`: integer 0–100000, default 0; `limit`: integer 1–50, default 20 | Bounded page through existing service; inaccessible source-derived answer text/citations are redacted |
| `submit_draft` | `item_id`: 1–100 characters; `text`: 1–10000 characters; `expected_revision`: positive integer | Author/admin only; edits an existing draft with CAS, creates a new unapproved revision and retains its citation snapshots. Does not accept new citations, owner changes or reviewer identity. Missing initial draft and stale revisions fail. |

Success returns structured JSON. Tool errors set MCP `isError`; callers must inspect it before using results. Missing/cross-tenant IDs, revoked identity/access, invalid input and stale revision do not succeed. No evidence approval, answer approval, export, membership mutation or evidence mutation tools are exposed. Source content is untrusted data; the adapter never executes instructions in evidence. Model-generated edits can contain unsupported claims and still require separate human review.

Tests: `.venv\Scripts\python.exe -m pytest tests/test_mcp.py -q` exercises SDK client/server protocol exchanges and a real subprocess stdio client with ephemeral RSA tokens and public JWKS. The normal CI pytest step includes these cases. Live IdP/MCP-host integration remains unverified; the signed local fixture uses the actual verifier. Search scans at most 100 ACL-visible current approved versions in stable ID order and returns `scan_truncated=true` when further versions exist; this bounded baseline can omit matches beyond that window. Search is deterministic lexical extraction, not the hybrid retrieval or agent workflow planned for T09/T10.

SDK compatibility was checked against the [official repository](https://github.com/modelcontextprotocol/python-sdk), [server API](https://py.sdk.modelcontextprotocol.io/api/mcp/server/mcpserver/server/) and [client transport documentation](https://py.sdk.modelcontextprotocol.io/client/transports/) on 2026-10-13, then verified using the installed pinned SDK.

T09 integration: setting `EVIDENCEDESK_DRAFT_ENGINE=foundation` routes `search_evidence` through the scoped hybrid foundation (limit at most 20); see [RETRIEVAL.md](RETRIEVAL.md). Baseline stdio identity, CAS and approval exclusions remain in force.
