# Ordered implementation backlog

The detailed `EvidenceDesk_Codex_Build_Plan.md` is the current milestone scope. Its M1 is workbook import/review/export; evidence lifecycle and enterprise access are M2. The historical outline below grouped those capabilities differently. See `IMPLEMENTATION_STATUS.md` for current validation and `WORKBOOKS.md` for the implemented M1 contract.

## M0 - initialization

Core, API, synthetic examples, tests, CI/container definitions and requirements. Record actual validation. Deliver source archive.

## M1 - real questionnaire workflow

Implement XLSX question/cell mapping and original-workbook export, source upload/parsing, owner queue, evidence revisions and approval invalidation. Add OIDC identities and document ACLs before real customer data. Gate: workbook round-trip, access revocation, approval and formula-safety tests.

## M2 - agentic RAG

Add PostgreSQL/pgvector hybrid search, embedding ingestion/versioning, reranker, LangGraph state/checkpoints, scoped MCP tools and two-provider gateway. Separate model-generated answers from cited source text. Gate: bounded execution, restart recovery, injection tests and held-out retrieval/answer results.

## M3 - evaluation and operations

Create 150-250 authorized or synthetic expert-reviewed cases: answerable/unanswerable, contradictions, expired evidence, editions, permissions and injections. Split dev/test and prevent optimizer leakage. Add Langfuse and Ragas/DeepEval, calibrate judges against humans, CI regression gates, load/failure tests, runbooks and prompt/version tracking. Gate: customer-agreed quality and operations report.

## M4 - optimization and deployment

Add routing, fallback, scoped caching, DSPy/GEPA experiments, pinned dependencies, security scans, staging CI/CD and rollback. Measure quality versus latency/cost. Gate: fallback does not silently relax evidence/policy requirements; no cross-tenant cache leakage.

## M5 - advanced learning extensions

Authenticated A2A evidence expert, allowlisted Tavily/Firecrawl ingestion, Kubernetes staging and optional LoRA classifier/reranker. Each requires an experiment against the simpler baseline. Gate: measured benefit or documented decision to keep the simpler approach.

## First next task

Milestone 1 XLSX import/review/export and **T01: React application foundation and API connection** are verified locally. The next task is **T02: Questionnaire dashboard and evidence entry**, followed by the browser workbook journey, evidence/access work and MCP/agent/AutoGen/A2A integrations. Use [NEXT_TASKS.md](NEXT_TASKS.md) as the current step-by-step execution queue; it includes dependencies and acceptance gates. The milestone outline above remains historical context.
