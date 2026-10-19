# AutoGen learning experiment (T11)

The isolated experiment runs actual AutoGen 0.7.5 `AssistantAgent` researcher, writer and verifier roles in a three-turn `RoundRobinGroupChat`. `ReplayChatCompletionClient` supplies deterministic tool selections; shared backend services retrieve, draft and validate exact extractive claims. These are real framework executions with fake models, not learned-model quality measurements.

## Reproduce

```powershell
.venv\Scripts\python.exe -m pip install -e '.[dev,autogen]'
.venv\Scripts\python.exe -m pytest tests/test_autogen.py -q
.venv\Scripts\python.exe -m scripts.autogen_compare
```

The comparison regenerates `evals/autogen_comparison.json` from identical answerable, missing-evidence, conflicting-evidence and prompt-injection fixtures used by T10. It records citation integrity, unsupported claims, answer/reason checks, wall latency, framework model-client calls, embedding/draft adapter calls and cost separately. CI installs the optional AutoGen dependencies, runs the tests and reruns the comparison.

## Scope and controls

Each tool binds the originating verified author, tenant, item and expected revision; model arguments cannot change that scope. Authorization, source validity and revisions are rechecked between phases. Only finite offline memory/embedding/drafting fixtures are accepted. The experiment returns an in-memory candidate and leaves questionnaire revisions unchanged. It cannot publish, approve or export.

Execution has three turns, one tool call per turn, input/output byte-unit bounds and a deadline of at most 30 seconds. Deadline and caller cancellation signal tool futures before awaiting framework shutdown. This is cooperative cancellation for finite local fixtures; live providers are rejected. There is no durable resume or production worker lifecycle. The primary LangGraph workflow retains those responsibilities.

## Decision and limitations

Retain LangGraph as primary; keep AutoGen for learning. Both frameworks use the same deterministic assessment and extractive validation, so matching fixture results do not establish an advantage from agent reasoning. AutoGen uses three replay model-client calls per case and zero actual LLM calls. Fixture paid cost is zero. LangGraph timing includes checkpoint persistence, worker processes and unapproved publication; AutoGen timing covers an ephemeral candidate, so the latency difference is not an equivalent production comparison. Four cases are not a held-out quality benchmark. Injection and contradiction checks remain conservative; human review is required.

On 2026-10-19 Microsoft's official repository still describes AutoGen as being in maintenance mode and recommends Microsoft Agent Framework for new projects. This task intentionally uses AutoGen to satisfy its learning goal, without adopting it as a second production engine.

Official references checked:

- [Microsoft AutoGen repository and maintenance guidance](https://github.com/microsoft/autogen)
- [AgentChat teams API](https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.teams.html)
- [Replay model client API](https://microsoft.github.io/autogen/stable/reference/python/autogen_ext.models.replay.html)

See VALIDATION.md for actual checks and the generated comparison for installed versions and measured results. No live providers or hosted CI execution are claimed.

## Local comparison recorded 2026-10-19

| Metric (four cases per framework) | LangGraph | AutoGen |
|---|---:|---:|
| Citation integrity cases | 4/4 | 4/4 |
| Unsupported claims / automatic approvals | 0 / 0 | 0 / 0 |
| Replay model-client calls | 0 | 12 |
| Real LLM calls / fixture cost USD | 0 / 0 | 0 / 0 |
| Embedding / draft adapter calls | 3 / 1 | 3 / 1 |
| p50 wall latency ms | 8370.40 | 100.67 |
| p95 nearest-rank wall latency ms | 15441.54 | 116.37 |

Zero comparison failures. Timings include different lifecycle work as explained above; no production speedup conclusion is supported.
