# Retrieval and provider foundation (T09)

T09 adds PostgreSQL full-text search, pgvector cosine retrieval, reciprocal-rank hybrid fusion and an optional lexical reranking experiment. The questionnaire/evidence store remains authoritative SQLite; PostgreSQL is a **rebuildable derived index**, not a second permission authority. Existing baseline drafting remains the default. T10's LangGraph workflow, durable checkpoints and iterative agent behavior are not implemented here.

## Start PostgreSQL and enable retrieval

Install dependencies with `.venv\Scripts\python.exe -m pip install -e '.[dev]'`. Use PostgreSQL with the vector extension, or the separate local Compose file:

```powershell
# Set EVIDENCEDESK_RETRIEVAL_PASSWORD using your secret environment mechanism.
docker compose -f compose.retrieval.yaml up -d
# Set EVIDENCEDESK_RETRIEVAL_DSN to the database URL (loopback port 5433).
.venv\Scripts\python.exe -m scripts.retrieval_admin migrate
$env:EVIDENCEDESK_AUTH_MODE='oidc'
$env:EVIDENCEDESK_RETRIEVAL_BACKEND='postgres'
$env:EVIDENCEDESK_MODEL_PROVIDER='fixture'
$env:EVIDENCEDESK_DRAFT_ENGINE='foundation'
```

Configure issuer, audience, public JWKS, memberships and source ACLs using [ACCESS.md](ACCESS.md). Only current approved, unexpired, nondeleted evidence with a currently authorized reviewer and the caller's ACL reaches an embedding/draft provider. Applicability filtering happens before embedding/indexing. Missing or mismatched metadata fails an explicitly requested filter. With conflicting product/edition/deployment tags and no corresponding selection, drafting abstains.

Migrations are operator-run, idempotent and advisory-lock protected. The app role should have only SELECT/INSERT/DELETE permissions on the derived chunks; extension/schema creation needs a separate migration role. Database credentials belong only to trusted backend operators. The index stores authorized source quotes; protect it with the same storage/network controls as the source store.

The opt-in `foundation` engine integrates with existing answer and questionnaire drafting. It persists unapproved answers with version dependencies, validates evidence again at commit, and preserves the existing approval/export safeguards. The existing UI needs no new authentication flow. MCP `search_evidence` uses the foundation when this engine is enabled (maximum limit 20); baseline MCP behavior remains documented in [MCP.md](MCP.md).

## Ordinary API

Use OIDC Bearer plus `X-Tenant-ID` on both endpoints:

- `POST /retrieval/search`: reads bounded authorized chunks.
- `POST /retrieval/preview`: author/admin-only, unpersisted structured draft preview.

JSON input: `query` (1–5000 characters), `method` (`lexical`, `embedding`, `hybrid`, default hybrid), `limit` (integer 1–20, default 5), `applicability` (optional exact `product`, `edition`, `deployment` strings, each at most 300 characters), `rerank` (boolean, default false). Extra fields are rejected. Example:

```json
{"query":"Is customer data encrypted?","method":"hybrid","limit":5,"applicability":{"product":"Synthetic"},"rerank":true}
```

Chunks include immutable source/version/hash provenance, exact character offsets and line/section locations. Plain-text imports have `page: null`; no PDF page location is invented. Chunking splits exact nonempty lines into spans of at most 1000 characters, retaining section headings. Source text is untrusted data. A small instruction-pattern check and encryption-conflict fixture check cause abstention; these are conservative synthetic checks, not a general injection detector or policy contradiction engine.

## Versioning and limits

Embedding model identity, dimensions and chunking configuration form the index profile. Chunk IDs bind tenant, immutable version/hash, offsets and profile. The authorized corpus fingerprint binds the chunk set. Queries select tenant + exact corpus + exact profile, and the app accepts only chunk IDs from the current authorized snapshot. Old index rows cannot resurrect revoked or superseded evidence. Different model spaces are never searched together. This schema supports 64-dimensional embeddings; a different dimension requires a new schema/profile, not implicit truncation.

Each call checks up to 100 applicable approved versions, 200000 source characters and 500 chunks; excess fails with `corpus_budget` rather than silently omitting sources. Results contain at most 20 chunks. Lexical/vector candidate rankings each contain at most 50 chunks; hybrid uses reciprocal rank fusion with constant 60. Vector candidates require cosine similarity >=0.25 (an experimental fixture threshold). Retrieval uses exact pgvector search on this small bounded corpus; no approximate HNSW recall claim is made. Optional reranking uses lexical overlap over at most 20 candidates and is an experiment, not a trained reranker.

The 20-second cooperative deadline is checked between phases and after provider return. Gateway calls have <=10-second socket timeouts; PostgreSQL has 5-second connect/lock timeouts and 10-second statement timeouts. A blocking injected adapter can exceed the cooperative deadline before rejection; hard cancellation/checkpoint recovery belongs to T10. Calls do not retry or fall back to another backend/provider. An authoritative writer transaction spans provider exposure, which serializes access changes and can reduce write concurrency; this bounded prototype is not a scalable ingestion architecture.

All three retrieval methods currently embed/rebuild the corpus per call; lexical ablation compares rankings, not provider cost. Chunks are rebuilt atomically for the selected corpus/profile per call. Old corpora remain inaccessible to scoped queries but retain copied text until an operator purges the tenant:

```powershell
.venv\Scripts\python.exe -m scripts.retrieval_admin purge --tenant your-tenant
```

Purge removes only derived chunks; immutable authoritative evidence history is retained under T07 rules. Reindex uses the same retrieval path and current authorized source versions. There is no background retention scheduler or shared answer cache. The memory backend is explicitly selected for local fixtures, rejected for nonlocal deployment, and never used as a PostgreSQL error fallback.

## Provider contract

`EmbeddingProvider` and `DraftProvider` are injected interfaces. Default fixture hash vectors include a tiny fixed synonym dictionary; they are not learned semantic embeddings. `ExtractiveProvider` returns structured exact quotes. `ScriptedProvider` tests hallucination, invalid schemas and errors without paid requests.

An optional `gateway` adapter calls a deployment-owned HTTPS service. Configure `EVIDENCEDESK_PROVIDER_URL`, server-secret `EVIDENCEDESK_PROVIDER_KEY`, full versioned `EVIDENCEDESK_EMBEDDING_MODEL` and `EVIDENCEDESK_DRAFT_MODEL`. This is a gateway contract, not an OpenAI/Anthropic SDK integration. It rejects redirects and bounds responses at 1 MiB. Live gateway/model/residency configuration remains operator responsibility and has not been exercised against a paid provider.

- `/embed`: POST `{model,texts}`; response `{vectors}` with one finite, nonzero 64-dimensional vector per input.
- `/draft`: POST `{model,question,evidence,prompt_version}`; response `{applicability,answer,claims,uncertainty}`.
- Each claim has `{text,chunk_id,quote}`. Quotes must be substrings of authorized retrieved chunks; claim text must equal its quote, and answer must equal the newline-joined claims. Arbitrary paraphrases or added prose are rejected. This enforces extractive citation support, not semantic entailment for free-form answers.
- Uncertainty reasons are restricted to `missing_evidence`, `conflicting_evidence`, `applicability_unspecified`, `provider_uncertainty`. No self-reported confidence score can approve an answer. Empty/uncertain drafts abstain.

The gateway receives only the current authorized applicable corpus for embedding and retrieved chunks for drafting. Traces keep hashes, configuration identities, counts and uncertainty codes rather than prompts/source text/keys. Gateway billing is unknown (`cost_usd: null`) rather than invented. No token-budget or paid-call guarantee is claimed; choose the fixture adapter until explicit live credentials/budgets are configured.

## Validation and ablation

Run `python -m pytest tests/test_retrieval.py -q`. Set `EVIDENCEDESK_TEST_RETRIEVAL_DSN` for the real PostgreSQL/pgvector integration gate; without it, that one test skips explicitly. CI provisions pinned `pgvector/pgvector:0.8.7-pg18` and runs the gate. Run `python -m scripts.retrieval_evaluate` (memory fixture) or `python -m scripts.retrieval_evaluate --postgres` for a four-case versioned ablation, including the lexical reranking experiment. Recall@3 is the fraction with the one gold source in the top three; nDCG@3 uses reciprocal log2(rank+1), with one relevant source per case. This hand-authored synthetic set validates adapters; it is not held-out evidence of semantic retrieval quality or production readiness.

Implementation references checked on 2026-10-13: [pgvector exact/cosine and hybrid search](https://github.com/pgvector/pgvector), [PostgreSQL text search controls](https://www.postgresql.org/docs/current/textsearch-controls.html), [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html). Psycopg is pinned to 3.3.6; migrations are packaged with the application.

Local validation used PostgreSQL 18.0 and pgvector 0.8.7 with all 121 backend tests passing. Both backend ablation outputs are recorded in [retrieval_ablation.json](../evals/retrieval_ablation.json); full validation and limitations are in [VALIDATION.md](../VALIDATION.md).
