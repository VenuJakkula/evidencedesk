# T07 evidence lifecycle and verified access

T07 is an additive local implementation gate. OIDC access-token verification, database memberships, document ACLs and immutable evidence are implemented. Live identity-provider login/configuration, hosted TLS and deployment are separately unverified. The React app accepts a provider-issued API access token in memory; automatic SSO redirects/token refresh are not implemented.

## Authentication configuration

Install backend dependencies from the updated pyproject.toml. Set these server variables:

```text
EVIDENCEDESK_AUTH_MODE=oidc
EVIDENCEDESK_DEPLOYMENT=production
EVIDENCEDESK_OIDC_ISSUER=https://your-trusted-issuer.example/
EVIDENCEDESK_OIDC_AUDIENCE=your-api-audience
EVIDENCEDESK_OIDC_JWKS_URL=https://your-trusted-issuer.example/keys
EVIDENCEDESK_DB=your-database-path
```

For controlled offline public-key verification, EVIDENCEDESK_OIDC_JWKS_FILE can replace JWKS_URL. It contains only public signing keys and is read from trusted server configuration. Production keys/issuer/API audience must come from your own IdP; the example.invalid fixture is test-only. Store secret/provider configuration outside committed files, restrict filesystem/database/backup access, and terminate deployed browser traffic with HTTPS. Never put credentials in VITE_* variables, URLs, audit metadata or logs.

Verification accepts RS256 keys of at least 2048 bits, a configured issuer/API audience, required exp/iat/sub/iss/aud claims, current expiry/not-before and a signing kid. Tokens must be API access tokens (at+jwt type or token_use=access); ID tokens, unsigned/HMAC tokens, token-supplied key URLs and role/tenant assertions are not authentication policy. JWKS reads are bounded to 64 KiB/32 keys, five-second network timeouts and a five-minute public-key cache. Remote JWKS uses only the configured HTTPS URL and rejects redirects. No discovery URL is accepted from a token. Token/claim/parser errors do not expose token text or key-file paths.

Requests use Authorization: Bearer <access token> and X-Tenant-ID. Tenant selection is checked against current active database membership, not a token role/tenant claim. Memberships and ACLs are rechecked in services on each operation; mutation/export checks run within the database transaction. There are no permission/retrieval caches. Reviewer attribution comes from verified issuer/subject, ignoring any client reviewer label.

Local synthetic mode remains available with AUTH_MODE=local and DEPLOYMENT=local. Non-local deployment configuration requires OIDC. Both local key-recovery/bootstrap routes return no key in OIDC mode even when old opt-in flags remain set. The deployed frontend omits local bootstrap controls.

## Bootstrap and roles

Stop writers and back up the database before upgrading. Provision the first admin from an operator shell, using the exact provider issuer and subject:

```powershell
.\.venv\Scripts\python.exe -m scripts.access_admin bootstrap your.db your-tenant https://your-trusted-issuer.example/ your-provider-subject
```

This creates an admin only for an unprovisioned tenant and records an audit event. There is no public first-admin endpoint. Further membership changes require a current admin through PUT /memberships with subject, roles and active. An admin cannot remove the last active admin through that API.

| Role | Allowed operations |
|---|---|
| author | Tenant-scoped reads, authorized evidence creation/version writes, workbook import, draft/redraft and edits |
| reviewer | Tenant-scoped reads, authorized evidence approval, current answer approval and export |
| admin | All tenant operations, membership/ACL management, evidence revocation/deletion and audit reads |

Admins can read all evidence in their own tenant. Other users need a source ACL; creation grants the author read/write access. A role alone does not grant document access. Grant only to an active member of the same tenant. Grant/revoke endpoints accept subjects in JSON so opaque provider subject strings need not be put in URLs.

## Evidence lifecycle and APIs

POST /evidence creates a source and pending immutable text version with title/content/version/valid_until and optional product, edition, deployment and provenance metadata. JSON text is limited to 100,000 characters. POST /evidence/upload accepts a UTF-8 .txt file plus metadata JSON, with 100,000 file bytes and a 200,000-byte request cap. UTF-8 BOM is removed; the hash covers the decoded text. Binary/PDF/DOCX parsing is not implemented; the plain-text phase remains explicit. URLs in provenance are recorded as text and are not opened.

GET /evidence is ACL-filtered and paginated (default 20, maximum 100). GET /evidence/{id} returns authorized source/history, capped at 100 versions. Every immutable version stores a content hash, expiry, metadata, creator and timestamp. Version updates cannot replace payloads: POST /evidence/{id}/versions requires expected_version and a new version label. The old version is superseded, the new one pending, and dependent approvals invalidated. Database triggers reject updates/deletes of version payloads.

POST /evidence/{id}/approve approves only the current pending unexpired version and records the verified reviewer. Pending, superseded, revoked, deleted and expired evidence cannot support drafts. Retrieval filters tenant, current state, expiry and ACL before using text.

An admin can POST /evidence/{id}/revoke, DELETE /evidence/{id}, or change source ACLs with PUT/DELETE /evidence/{id}/acl. Deletion is a logical tombstone: the source disappears from accessible APIs, but payload/history/dependency/audit records are retained. This is not physical erasure or a regulatory retention system. No automatic purge is scheduled; operators must establish retention for database copies, backups and downloaded exports before real-data deployment.

## Dependency and review invalidation

Every generated/edited answer records source version IDs and content hashes. Snapshots validate source/version/document identity, quote membership, hash, source approval, current reviewer authority, expiry and the caller's current ACL. Historical legacy documents migrate as pending immutable versions; old content/answers are preserved, but old unversioned snapshots are not eligible in OIDC mode until redrafted. Recoverable historical dependencies are linked without rewriting immutable answer/revision data.

Source update, revoke/delete, ACL revocation and reviewer membership/role removal invalidate dependent approvals. Immutable approval records remain; separate invalidation records prevent their reuse. Expiry is enforced on retrieval/review/export; lazy synchronization marks expired approvals unusable on authenticated reads, and POST /evidence/expire allows an admin maintenance sweep. Adding a grant or restoring source approval never restores an invalidated answer approval automatically.

Unauthorized citations and derived answer text are redacted. Saved local buffers are cleared when a reload marks the answer access-blocked; 401/403 invalidates the frontend session and removes its workspace. Previously delivered/downloaded data cannot be recalled.

POST /questionnaire-items/{id}/redraft with expected_revision creates an unapproved new revision using only current approved accessible sources. It is an author/admin action. The browser shows invalidation and exposes Redraft from current evidence. Current verified reviewer approval is required again. Edited-after-approval and preserved-destination rules remain.

New exports recheck current membership, reviewer authority, ACL and evidence under the export transaction. Old export receipts describe historical results; they contain no source quotes and remain tenant-scoped. No stored artifact re-download endpoint bypasses current export checks. Legacy /answers and CSV /export are also guarded in OIDC mode; /documents cannot bypass the evidence approval lifecycle there.

## Audit and backup/restore

GET /audit is admin-only and bounded/paginated. Append-only events record actor/action/resource/time and minimal hashes/counts/role changes. They exclude JWTs, document text and quoted answers. SQL triggers reject audit mutation/deletion; this is not infrastructure tamper-proof auditing. Privileged database/filesystem operators remain trusted.

The migration adds memberships, versions/states/ACLs, answer dependencies, approval invalidations and audit tables. Existing documents/answers/workbooks remain. Back up before migration; there is no destructive downgrade.

```powershell
.\.venv\Scripts\python.exe -m scripts.access_admin backup your.db backup-new.db
.\.venv\Scripts\python.exe -m scripts.access_admin restore backup-new.db restored-new.db
```

The helper uses SQLite's backup API and refuses to overwrite an existing destination. Restore to a separate file while writers are stopped, verify integrity/foreign keys, review membership/ACL/revocation state, then configure the application to use it. An older backup can resurrect old permissions; quarantine a restored database until later revocations have been reapplied. The local restore exercise verifies that a backup containing revocation retains that denial, evidence/workbook history and audit records after restore/restart. RPO/RTO and encrypted operational backups remain deployment responsibilities.

## Frontend configuration and local verification

Set non-secret VITE_AUTH_MODE=oidc and VITE_DEFAULT_TENANT for the frontend; restart/rebuild it. Connect using the provider access token. The Evidence tab exposes version upload/approval/history and admin membership/ACL controls. Review uses verified identity and role-aware controls, with backend authorization as the authority.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
.\.venv\Scripts\python.exe -m scripts.workbook_browser
.\.venv\Scripts\python.exe -m scripts.workbook_browser --oidc
```

The OIDC browser profile generates an ephemeral RSA key, public JWKS and short-lived signed access tokens in a marked temporary directory. The actual verifier runs unchanged against that public key; no test-auth bypass is enabled. Tokens/private signing material are not committed. CI runs both profiles with Chromium. Live IdP configuration and hosted staging deployment are separate unverified dependencies.

References: [PyJWT verification usage](https://pyjwt.readthedocs.io/en/latest/usage.html), [OpenID Connect Core](https://www.openid.net/specs/openid-connect-core-1_0.html).

T10 adds a separate durable workflow checkpoint file beside the authoritative database. Stop workers and back up/restore both files together; reconcile current revocations before serving restored state. See [workflow recovery/storage](WORKFLOWS.md).
