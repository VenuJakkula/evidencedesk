# Bounded drafting workflow (T10)

T10 implements a real LangGraph state machine: **classify → retrieve → assess → draft → verify → human review**. Jobs are bound to an originating verified OIDC author, tenant, item revision, model/index/transport profile and immutable resource limits. The graph has durable SQLite checkpoints; jobs, phase results and provider-call reservations live in the authoritative workflow store. Human approval uses the existing questionnaire approval API and verified reviewer identity. Graph execution never approves an answer.

## Start and use

Install `.venv\Scripts\python.exe -m pip install -e '.[dev]'`. Configure OIDC and approved evidence using [ACCESS.md](ACCESS.md), and migrate/configure the PostgreSQL retrieval index using [RETRIEVAL.md](RETRIEVAL.md). The default provider is a deterministic fixture. Workflow jobs use the retrieval foundation regardless of the legacy `EVIDENCEDESK_DRAFT_ENGINE` setting.

In a verified session, open a questionnaire's review workspace and expand **Agent workflow** on an item. Set deadline, provider attempts, input/output budgets and authorized USD cost. Start bounded workflow advances at most 12 phases per browser action and stops at a retry needing your action, an owner task, a failure or human review. It refreshes the current unapproved revision in the ordinary answer editor. Inspect its claims/citations, then use **Approve revision** as a verified reviewer. Reload saved progress and choose **Finish reviewed workflow** to close the graph; that step requires the current approval record and current evidence/reviewer permissions.

Reviewers can see saved progress and make the ordinary review decision; they cannot start, advance or cancel author jobs. Only the originating author or a tenant admin can advance/cancel. The original author must still have author membership when work runs. Unsaved edits and other pending review mutations block starting/continuing workflows. Concurrent item changes cause CAS failure without publication. A newer revision supersedes the job's review target.

Closing the browser or aborting a fetch does not cancel server work. **Cancel workflow** writes a durable cancellation flag; local active workers are terminated before future publication. If a revision committed before cancellation, it remains in immutable history and requires its own explicit review. Reload saved progress after an uncertain response. Creation retries retain the same request key and fixed budget; definitive input failures allow correction. The backend also permits only one active job per item. Refresh/reconnect discovers saved jobs through the authenticated API.

## API and one-step execution

All endpoints require a verified OIDC Bearer session and selected tenant:

| Endpoint | Behavior |
|---|---|
| `POST /workflow-jobs` | Author/admin creates an immutable job or returns the same job for the same request key and inputs |
| `GET /workflow-jobs?item_id=…&limit=5` | Tenant-scoped recent jobs, limit 1–20; current source-derived answer redaction |
| `GET /workflow-jobs/{id}` | Saved phase/progress/budget and current review decision; no raw checkpoint or internal phase output |
| `POST /workflow-jobs/{id}/advance` | One durable graph phase, or completion after an existing verified human approval |
| `POST /workflow-jobs/{id}/cancel` | Originating author/admin stops pending work; does not delete or approve revisions |

Creation body example:

```json
{"item_id":"server-item-id","expected_revision":0,"request_key":"unique-request-id","options":{"deadline_seconds":120,"max_attempts":4,"max_refinements":1,"max_input_tokens":100000,"max_output_tokens":16000,"max_cost_usd":0,"method":"hybrid","applicability":{"product":"Synthetic"}}}
```

`expected_revision` includes zero for an imported undrafted item. The key is 1–100 characters and scoped to tenant/issuer/subject; reuse with different inputs fails. Options are strictly typed, unknown fields fail. Limits: deadline 5–300 seconds; provider attempts 1–6 across embedding/drafting; refinements 0–1; input units 100–1000000; output units 100–64000; authorized cost 0–100 USD. Retrieval method is lexical/embedding/hybrid; applicability uses bounded exact product/edition/deployment tags. There is an additional fixed 16-phase bound. No raw graph state, arbitrary tool, caller-supplied identity or approval boolean is accepted.

The service advances under a durable 35-second lease so concurrent runners cannot advance the same checkpoint. There is no unattended scheduler in T10: the browser drives bounded phases, and operators may advance one phase through the same verified service:

```powershell
# Supply EVIDENCEDESK_WORKFLOW_TOKEN through a secret environment mechanism.
# Use the same absolute EVIDENCEDESK_DB and tenant/OIDC/retrieval configuration as the API.
.venv\Scripts\python.exe -m scripts.workflow_step server-job-id
```

The CLI verifies a fresh access token and prints only progress IDs/status, not source text or tokens. The browser/API also reverify the session on each request. Leases are recoverable after their expiry following process failure.

## Durable recovery and external calls

Checkpoint thread IDs are server-generated hashes of tenant/job ID. LangGraph checkpoint state contains only job ID, phase route and sequence. Raw retrieved material resides in protected authoritative phase-ledger rows; public job views recheck current permissions and redact derived answers. Credentials and provider objects are never checkpointed. Serialization disables pickle fallback and restricts object restoration to LangGraph's Interrupt type. Framework tracing is explicitly disabled for graph execution and workers; no implicit external trace destination receives this data.

Completed phase results are reusable after restart. A phase result and its counters are committed before the next checkpoint. If a process dies between the durable phase commit and checkpoint write, replay reads the phase ledger rather than repeating the call. Publication atomically creates one unapproved answer/revision, its evidence dependencies, audit event and job publication receipt. A crash before the human-review interrupt can resume from that receipt without creating another revision. Existing verified human approval is rechecked in a writer transaction when completing review.

An external call reservation is persisted before worker launch. If a started external phase has no durable result after a crash, the job stops with `uncertain_step`; it is not replayed automatically. Reconcile gateway logs/billing before intentionally starting a new job. Known provider/index unavailability can be retried through an explicit advance, within the same persisted attempt/token/cost limits. Invalid claims/schemas, authorization/evidence changes, revision conflict, cancellation and exhausted budgets fail closed. There is no provider/backend fallback or automatic live-call retry.

## Budgets, deadlines and live provider opt-in

Input/output budgets are **conservative serialized UTF-8 byte units**, with 512 units of input protocol overhead, not measured vendor tokenizer usage. The service reserves input units and up to 8000 output units per draft attempt before exposure; failed/uncertain calls retain reservations. Structured output is checked against its reserved byte allowance. These local bounds do not prove semantic correctness or an actual invoice amount.

Retrieval and draft phases run in isolated spawned processes with a local hard cutoff of at most 20 seconds or the remaining persisted job deadline, whichever is smaller. The parent polls the separate durable cancellation flag and terminates the worker; a worker watchdog also bounds an orphan after a parent crash. PostgreSQL/gateway operations retain T09's timeouts. Cancelling a local HTTP connection cannot guarantee a remote gateway stops computing or billing; reservations remain charged against the job's authorization. Human review can wait past the generation deadline; no more model calls run during that wait.

The default fixture path makes no paid calls. Live gateway workflows require all of:

- `EVIDENCEDESK_MODEL_PROVIDER=gateway`, trusted HTTPS URL, secret key and full versioned model identities from T09.
- `EVIDENCEDESK_ALLOW_LIVE_WORKFLOWS=1`.
- Positive contracted worst-case price caps in `EVIDENCEDESK_WORKFLOW_EMBED_INPUT_USD_PER_1K`, `EVIDENCEDESK_WORKFLOW_DRAFT_INPUT_USD_PER_1K`, `EVIDENCEDESK_WORKFLOW_DRAFT_OUTPUT_USD_PER_1K`.
- A positive per-job `max_cost_usd` authorization sufficient for all reserved input/output units.

The gateway receives an `Idempotency-Key` and a `budget.max_output_tokens` request field. It must honor output limits/idempotency and price/residency contracts. Locally reserved cost is an upper-bound authorization based on configured caps; actual billed usage and vendor-internal LLM call counts remain unknown. Traces distinguish completed draft-adapter calls from LLM calls (zero for fixtures, unknown for a live gateway). Model/index/transport/price profile changes stop resumption instead of silently switching providers or relaxing policy. No live paid-provider run has been performed.

## Evidence and verification limits

Classification and evidence assessment are deterministic. Missing/weak evidence permits at most one retrieval refinement using query terms, without relaxing ACL/applicability. Conflicting encryption statements, ambiguous applicability and recognized instruction patterns become explicit owner tasks instead of confident answers. No owner identity is invented: the task shows the item's existing owner label or unassigned.

The model adapter must return strict structured extractive claims. Claim IDs/quotes are checked against authorized retrieved chunks; claims must equal their exact quotes and the answer must contain only those claims. Verification rechecks current source/version/hash/lifecycle/ACL and reviewer authority. This prevents invented citations and added prose; it is not a general semantic entailment verifier. Instruction/contradiction checks are conservative fixture checks, not complete detection of encoded attacks or arbitrary policy contradictions. Human review remains required. No external tool execution, email, delivery or approval is exposed to model output. Workflow publication is restricted to unapproved internal revisions.

## Storage, backup and validation

SQLite migration 003 adds immutable job inputs, phase/call ledgers and an active-item constraint. Checkpoints/cancellation live in `<absolute EVIDENCEDESK_DB>.workflow.sqlite`, separate from the store so cancellation can interrupt a provider holding its writer lock. Retention is operator-managed; phase rows may contain copied source text, and source tombstones remain retained under T07. These files require the same access controls as source evidence. No automatic purge is implemented.

Stop the API and all workers before backup/restore. Use the existing operator SQLite backup helper to copy both the authoritative store and its checkpoint file to new destinations, then restore the pair. Reconcile revocations before serving restored data as required by [ACCESS.md](ACCESS.md). A missing/stale checkpoint can replay only ledger-completed phases; incomplete external calls remain uncertain. The prototype uses synchronous SQLite and per-phase processes, not a scalable distributed queue or production failover claim.

Run `python -m pytest tests/test_workflows.py -q`; `npm.cmd --prefix frontend test`; and `python -m scripts.workbook_browser --oidc --workflow`. The workflow browser profile uses signed RSA tokens and an explicitly local memory index with deterministic providers; it leaves the original production-mode OIDC browser profile intact. CI also provisions PostgreSQL/pgvector for the real workflow/retrieval integration gates.

`python -m scripts.workflow_evaluate --output evals/workflow_results.json` records four synthetic answerable/missing/conflicting/instruction cases, statuses, citation support, reasons, attempts, conservative reservations, fixture cost and observed p50/p95 wall latency including process startup. It is a small invariant gate, not held-out learned-model quality or production performance. T11's framework comparison remains separate.

SDK compatibility checked against official [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupt behavior](https://docs.langchain.com/oss/python/langgraph/interrupts) and [SQLite checkpointer reference](https://reference.langchain.com/python/langgraph.checkpoint.sqlite) on 2026-10-13. Pinned versions: LangGraph 1.2.15, checkpoint 4.3.0, SQLite checkpointer 3.1.2.
