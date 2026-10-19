# T13 evaluation, observability and deployment

T13 is **verified_local for the user-agreed local synthetic scope**. The user selected "Use local synthetic validation; keep external gates explicit". The 50 cases are synthetic author labels, not human-reviewed customer cases. Full M4/M5 completion and production readiness still require the external evidence listed below, including Docker/staging execution and human calibration. See VALIDATION.md for actual commands and results.

## Evaluation and release thresholds

`evals/release/` contains fixed development (20), validation (10), and held-out (20) cases across answerable, paraphrase, missing, contradictory, injected, denied, foreign-tenant, ambiguous-applicability, expired and pending evidence. Each case specifies applicability, source approval/access, gold sources, expected facts and abstention reason. Splits use different product identifiers, but their templates are closely related; they are not an independent generalization benchmark. Review the labels with a domain expert before pilot use and grow toward the detailed plan's 150–250 cases.

```powershell
.venv\Scripts\python.exe -m pip install -c requirements.lock -e '.[dev,autogen,a2a,operations,optimization]'
.venv\Scripts\python.exe -m scripts.release_evaluate --split validation --output evals/release_validation.json
.venv\Scripts\python.exe -m scripts.release_evaluate
.venv\Scripts\python.exe -m scripts.optimize_classifier
.venv\Scripts\python.exe -m scripts.routing_compare
.venv\Scripts\python.exe -m scripts.operations_check
```

The release evaluator executes the actual scoped retrieval, primary workflow assessment and structured claim generation services. It does not run a durable graph for every case; existing workflow and A2A tests cover that lifecycle separately. Reports include dataset SHA-256, SDK/model IDs, split, sample denominators, per-case results and measured wall latency. Compare only the same split/hash/provider/method and lifecycle scope.

Metrics have separate meanings:

| Metric | Definition |
|---|---|
| Recall@5 | Fraction of each case's gold source IDs retrieved; mean over cases with gold sources |
| nDCG@5 | Binary relevance by gold source ID with log2 rank discount, normalized by ideal gold ranking |
| Correct cases | Expected abstention/answerability and reason match; expected facts appear verbatim for positive cases |
| Citation integrity | No citations, or all emitted citations pass current authoritative version/permission validation |
| Unsupported claims | Non-abstained answer differs from the concatenation of exact validated claims |
| Abstention recall | Abstained unanswerable cases / labeled unanswerable cases |
| Answerable coverage | Non-abstained answerable cases / labeled answerable cases |
| Contradiction detection | Correct contradiction reason / labeled contradiction cases |
| p50/p95 | Upper median and nearest-rank 95th percentile of per-case service latency |
| Cost/model calls | Fixture paid cost (zero) and actual draft-adapter invocations; not vendor token usage |
| Review edits/time | Unmeasured, reported as null; collect actual reviewer observations before setting targets |

`thresholds.json` requires full citation integrity, every fixture correct, Recall/nDCG/abstention/coverage/contradiction metrics of 1.0 and zero unauthorized evidence, unsupported claims and automatic approvals. These are developer-defined synthetic regression thresholds, not buyer-agreed acceptance targets. Latency is measured but no hardware-independent performance threshold is asserted. CI exits nonzero on invariant/quality regressions. Do not lower gates to accommodate a changed prompt without a documented review. Human calibration and review acceptance targets remain open; no LLM judge or Ragas/DeepEval score is fabricated for deterministic exact extraction.

## Optimization and provider resilience

The optional DSPy 3.4.1 experiment compiles a real `LabeledFewShot(k=4)` program from development labels before loading validation/held-out cases. It then executes `Predict` with a rule-derived `DummyLM`. The fake model ignores demonstrations, so identical fixture scores establish framework/split mechanics, not optimized reasoning quality. Retain the fixed production baseline. No real LLM was called.

The full learning environment scan still reports DiskCache 5.6.3's pickle/cache-directory-write advisory (PYSEC-2026-2447 / GHSA-w8v5-vhqr-4h9v), with no fix version listed. Disk caching is disabled for this experiment, and DSPy/DiskCache are excluded from the runtime image. This does not erase the dependency finding; avoid importing untrusted caches and resolve or explicitly review the learning environment risk before broader use. The runtime lock has a separate clean scan.

`RoutedDraft` is a separate two-adapter experiment. `routing_compare` measures both extractive adapters on development cases and picks a provisional route by correctness, unsupported/unauthorized output, cost, then p95 latency. A fixed region/privacy/price contract rejects ineligible fallback peers. Only `provider_unavailable` triggers one alternative; invalid claims, policy and access errors do not. Failed peers cool down for ten seconds. Total caller timeout is bounded, with the same limits as cooperative provider adapters. Tests cover outage/cooldown and policy mismatch.

The router is deliberately **not wired into primary workflow accounting**: its two offline adapters are not two measured production model services. Primary workflow retry/idempotency and budget rules remain authoritative. Live two-provider routing, contracted price/residency validation and learned-model held-out optimization remain open M5 gates.

The opt-in `EVIDENCEDESK_CACHE=1` cache holds retrieval IDs only, at most 128 entries for 30 seconds. Keys include database namespace, tenant, verified issuer/subject, current ACL-visible corpus/version IDs, embedding profile, prompt/model, query and retrieval options. Every call re-authorizes the corpus and validates returned evidence before exposure. Permission removal, new versions, revocation and expiry change the authorized corpus or reject access. Answers/approvals are never cached. Entries are copied, bounded and not serialized into spawned workers; workers start empty. Tests cover user isolation, revocation, ACL/membership changes, version updates, TTL and eviction.

## Tracing and debugging

`EVIDENCEDESK_TRACE_FILE` enables local JSONL spans. Each HTTP response includes a server-generated `X-Request-ID`. Fixed span names cover HTTP, ingestion, retrieval, model, MCP/A2A tools and workflow work. Context propagates to spawned provider phases, with random job IDs linking the durable job ledger. Only allowlisted counts, reserved byte units/cost, phase/status, random IDs, duration and failure categories are recorded. No headers, tokens, URLs, questions, outputs, source text or tenant/subject names enter the payload. Framework auto-tracing remains disabled for graph/provider processes.

Remote LangSmith export uses explicit SDK `create_run`/`update_run` calls only when `EVIDENCEDESK_TRACE_EXPORT=langsmith` is set with an operator-approved endpoint/key. Inputs/outputs are empty and SDK hiding is enabled; runtime environment metadata is omitted. No remote account or export was exercised. Telemetry failures do not alter request results; this also means operators must monitor collector health separately. Local traces need protected storage, rotation, disk-space alerts and a retention policy. Parent/child IDs cross processes; a killed process may have no completed span, so consult the durable phase ledger for uncertain work.

| Failure category | First check |
|---|---|
| access | Verify issuer/audience/expiry, then live tenant membership and document ACL; never paste tokens into logs |
| validation | Inspect documented input bounds locally; source text is intentionally absent from traces |
| conflict | Reload current revision/evidence; do not replay approval or uncertain provider work blindly |
| deadline | Inspect job deadline, cancellation state, worker exit and phase ledger |
| provider | Check configured peer availability, retry/attempt ledger and budgets; no authorization-relaxing fallback |
| internal | Correlate request/job IDs with local process health and database integrity |

`/health` is liveness; `/ready` checks authentication configuration/JWKS availability and SQLite quick integrity. Responses contain generic states. Readiness does not validate an optional PostgreSQL index, live provider, reviewer membership or end-to-end task correctness. Seeded failure/privacy tests demonstrate local diagnosis without retaining sensitive input.

## Deployment, restore and rollback

`requirements.lock` pins the complete Python 3.12/Linux runtime dependency closure. The Dockerfile installs those pins then the app without dependency re-resolution, runs as UID 10001, and probes `/ready`. Pins do not include artifact hashes or an immutable base-image digest; capture/approve those in the target registry before production promotion. Optional development/learning extras are excluded from the runtime image. Regenerate intentionally with `python -m scripts.lock_runtime` after installing reviewed upgrades, then scan and test again.

`requirements.ci.lock` separately pins the Linux/Python 3.12 CI extras (145 packages), resolved with uv 0.13.1 using the command embedded in its header. This target includes dependencies that differ from the local Windows/Python 3.14 environment. A cross-target pip wheel-availability check passed for the 65 runtime pins; Linux installation/container execution remains a CI gate. The learning audit fails on new findings or unscanned packages while preserving the explicitly documented DiskCache advisory in its output; this is an engineering exception for offline learning only, not production risk acceptance.

CI installs runtime constraints, runs regressions/evaluations/restore tests, audits the runtime lock, builds the image, invokes `scripts.container_smoke`, and scans high/critical image findings using Trivy. No deployment credentials or automatic publishing are configured. The local container gate was not executed because Docker is absent. The smoke gate uses a unique synthetic container, non-root read-only runtime, bounded tmpfs, authenticated writes and restart; it is not a staging rollback demonstration.

`compose.staging.yaml` requires a tested immutable image, prepared staging data directory, issuer/audience and public JWKS file. It binds loopback for a separately configured TLS proxy, requires OIDC, disables local key/bootstrap and live providers, drops capabilities, limits resources and retains a writable data mount. Set data ownership for UID 10001 before starting. No secrets are committed. This is an API staging recipe; hosted frontend routing, proxy/TLS and PostgreSQL deployment still need target-environment configuration.

Proposed recovery targets are **RPO 60 minutes / RTO 30 minutes**, pending operator agreement and full-service rehearsal. `operations_check` restores a tiny synthetic SQLite backup, checks integrity, reapplies migrations, and verifies a post-backup candidate write disappears. Its timing measures database restore only. Its 80 requests at concurrency four exercise the in-process health route, not production workload capacity.

Before any approved staging promotion:

1. Quiesce writers/workers and save the current image reference and configuration. Back up the authoritative DB plus the `.workflow.sqlite` checkpoint/control sidecar consistently, retained original workbooks/evidence and protected configuration. The helper copies one SQLite file, not a cross-file atomic snapshot; use stopped services or a filesystem snapshot. The PostgreSQL retrieval index is derived and can be rebuilt from authoritative evidence.
2. Use `python -m scripts.access_admin backup SOURCE NEW_BACKUP` for each stopped SQLite file. Backups never overwrite an existing destination. Verify integrity and rehearse restore to new paths before deleting anything. Retention, off-host encryption and backup freshness alerts are operator responsibilities.
3. Test a copy with the candidate image, migrations, readiness, real scoped author/reviewer workflow, negative access checks and export preservation. Capture the candidate/previous image digests and measured timings. Add a realistic load profile before setting capacity/SLOs.
4. Exercise rollback: stop the candidate and workers, restore the known-good DB/control snapshot to new paths, switch to the saved image/configuration and restored data, restart, then verify identity, citations, pending review and export behavior. Do not run an older binary against unknown newer schema state. Account for writes after the backup using the agreed RPO; never silently discard customer changes.

Actual staging promotion/rollback, image scan results, real provider routing, human-reviewed evaluation and production recovery objectives remain recorded gates. The agreed local synthetic task is complete; full M4/M5 completion still requires that external evidence.

References checked for this implementation: [LangSmith create_run](https://reference.langchain.com/python/langsmith/client/Client/create_run), [DSPy optimizers](https://dspy.ai/3.4.1/diving-deeper/choosing-an-optimizer/), [Compose service controls](https://docs.docker.com/reference/compose-file/services/), [Trivy action 0.35.0](https://github.com/aquasecurity/trivy-action/releases/tag/0.35.0), [PyJWT 2.15.0](https://github.com/jpadilla/pyjwt/releases/tag/2.15.0), [multipart 0.0.32](https://github.com/Kludex/python-multipart/releases/tag/0.0.32).
