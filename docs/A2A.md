# A2A evidence expert (T12)

The optional integration uses the official `a2a-sdk[http-server]==1.1.5` and A2A 1.0 JSON-RPC. An independently addressable evidence expert serves discovery at `/.well-known/agent-card.json` and RPC at `/a2a`. A separate questionnaire HTTP service invokes it through the SDK client and injects verified evidence into the existing LangGraph workflow.

## Reproduce locally

```powershell
.venv\Scripts\python.exe -m pip install -e '.[dev,autogen,a2a]'
.venv\Scripts\python.exe -m pytest tests/test_a2a.py -q
.venv\Scripts\python.exe -m scripts.a2a_demo
```

The demo creates a temporary synthetic database and signed OIDC fixtures, starts two separate loopback processes, discovers the expert, submits and polls a real A2A task, validates its evidence artifact, and reaches human review. It then explicitly approves through the existing reviewer service and completes the workflow. Both processes and temporary files are cleaned up. No real provider calls are made.

For manual operation, configure the OIDC settings in ACCESS.md, an existing database with tenant membership and approved evidence, and the A2A settings in `.env.example`. In separate terminals run `python -m app.a2a_expert` and `python -m app.a2a_questionnaire`. Both require `Authorization: Bearer <author access token>` and `X-Tenant-ID` headers. The client sends `A2A-Version: 1.0`. Questionnaire endpoints are `POST /workflow-jobs`, `GET /workflow-jobs/{id}`, and `POST /workflow-jobs/{id}/advance` or `/cancel`; the create payload matches the primary workflow API. Advance each saved phase until human review. Reviewer approval remains in the existing questionnaire API; neither agent exposes approval or export.

## Trust and lifecycle

Both services independently verify the originating author's OIDC token and live membership. The token stays in process memory and is forwarded only to the configured expert origin; discovery cannot redirect credentials. This learning setup uses the same issuer/audience and shared authoritative SQLite store. It does not implement cross-organization token exchange, separate databases or service-account impersonation. Standalone servers bind loopback; any hosted TLS/proxy setup remains operator work.

The expert returns only current ACL-visible approved evidence with exact chunk/version/hash/quote provenance. Access is checked before research, before storing a result and again on reads. The client compares artifacts against its authoritative corpus, and the primary workflow repeats citation and revision checks before publishing an unapproved answer. Missing, revoked or altered evidence fails closed. Human review remains mandatory.

Task IDs and results persist in `a2a_tasks`, scoped by tenant, issuer and subject. Repeating a message ID with the same payload returns the original task; a changed payload is rejected. At most two transport attempts occur within the client deadline. Cancellation and timeouts prevent late results from becoming successful artifacts. Expert restart marks unfinished tasks failed rather than replaying uncertain work.

## Bounds and limitations

The expert is a single process per database: startup recovery assumes exclusive ownership of its task table. It accepts at most eight active tasks and 1,000 retained tasks, a 32 KiB HTTP body, and a ten-second research deadline. There is no retention administration; use a disposable synthetic database for repeated experiments. Client responses are bounded to 256 KiB; compressed responses and redirects are rejected. Streaming, push notifications, task listing and extended cards are unsupported.

Research uses finite offline retrieval adapters. Cancelling an asyncio wrapper cannot forcibly stop a running worker thread; late thread results are discarded. If a primary workflow worker is killed, remote work can run until its bounded expert deadline. No paid-provider, hosted CI, live IdP, TLS deployment or cross-language interoperability result is claimed. No frontend behavior changes.

## Compatibility references

Checked on 2026-10-19 before completing this integration:

- [Official Python SDK](https://github.com/a2aproject/a2a-python) implements A2A 1.0.
- [Official 1.0 migration guide](https://a2aproject.github.io/a2a-python/docs/migrations/v1_0/) documents protobuf messages, supported interfaces, route factories and version headers used here.
- [Pinned SDK release 1.1.5](https://github.com/a2aproject/a2a-python/releases/tag/v1.1.5).

The optional dependency group pins the tested protobuf and Google API dependencies as well. See VALIDATION.md for actual local checks.
