# Resume-gap and JD coverage

Status: I = initialized baseline, P = planned. No planned capability should be claimed as work experience until implemented and measured.

| Concept | Product implementation | Gate | Status |
|---|---|---|---|
| AI evaluation/output testing | Gold dataset, Ragas/DeepEval plus human-scored claims, retrieval and abstention tests | Held-out report and regression thresholds | I: three deterministic cases; P: real benchmark |
| Observability/Langfuse or LangSmith | Request/retrieval/tool/model spans, latency, tokens, cost, redacted errors | Diagnose seeded failures from traces | I: local metadata; P: telemetry backend |
| Guardrails/hallucination mitigation | Cite/verify claims, schema constraints, abstention, injection suite, tool allowlist | Adversarial and permission test report | I: extractive abstention/export gating; P: LLM safeguards |
| Unit/integration/production code | API, retrieval, authorization, workflow and export tests; type/lint/security checks | CI and fault-injection pass | I: core/API tests |
| Reliable agents/LangGraph | State graph, checkpointing, approval interrupts, retries, timeouts, idempotency | Kill/restart and duplicate-action tests | I: persistent review state; P: durable agent |
| Advanced RAG/embeddings/vector DB | PostgreSQL pgvector + lexical hybrid retrieval, reranking, chunking and metadata experiments | Recall@k/nDCG ablation benchmark | P |
| Model routing/fallback/caching/cost | LiteLLM gateway, two providers, explicit fallback policy, tenant/ACL/version-scoped cache | Simulated outage + quality/cost frontier | P |
| Docker/deployment | Non-root image, compose, health/readiness, staging release | Container smoke test and rollback | I: definitions; P: executed deployment |
| CI/CD | Tests/evals/image build, pinned dependencies, release promotion | Failed eval blocks release | I: CI definition; P: deployment pipeline |
| DSPy/GEPA | Optimize classification and cited answer drafting | Held-out improvement without data leakage | P |
| A2A | Separately deployed evidence-expert service; authenticated agent interoperability | Scoped requests, timeout and protocol tests | P: optional learning extension |
| Kubernetes | Stateless API/workers, managed DB, probes, secrets, resource limits and autoscaling | Staging load/failure/rollback exercise | P: later learning extension |
| Tavily/Firecrawl | Allowlisted public product-reference discovery with approval before ingestion | Provenance, crawling limits, stale-source tests | P: optional connector |
| Multi-agent architecture | Planner/retriever/verifier roles only where benchmark supports separation | Compare against simpler single-agent workflow | P |
| MCP/tool calling | Scoped evidence search and owner-assignment tools | Tool authorization, schema and replay tests | P |
| Multiple providers/models | Azure/OpenAI and Anthropic or Gemini behind adapters | Same held-out data across providers | P |
| Hugging Face/Transformers/PyTorch/fine-tuning | LoRA question classifier or reranker if baseline demonstrates need | Compare prompt-only and tuned model on held-out data | P: learning extension |
| Backend integrations | SharePoint/document store and customer ticketing connector | Revoked permission and upstream outage tests | P |
| Prompt engineering/software debugging | Versioned prompts, failure taxonomy, deterministic reproduction and debugging runbook | Reproduce and explain five failure classes | P |

A2A, Kubernetes, crawling and fine-tuning are advanced extensions, not prerequisites for the first paid pilot. MCP, LoRA and agents already appear in the resume; they remain in the plan to strengthen demonstrable depth.
