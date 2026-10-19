"""Reproducible same-case AutoGen / primary LangGraph comparison; offline only."""
import argparse
import asyncio
import importlib.metadata
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.evidence import valid
from app.experiments.autogen_drafting import run_experiment
from app.retrieval import Foundation
from app.retrieval_index import MemoryIndex
from scripts.workflow_evaluate import CASES, create_fixture


def compare():
    failures = []
    rows = []
    with tempfile.TemporaryDirectory(prefix='evidencedesk-autogen-eval-') as directory:
        # Baseline runs actual durable graph + child processes, with identical fixtures.
        baseline_file = Path(directory)/'langgraph.json'
        env = dict(os.environ, LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false',
                   AUTOGEN_DISABLE_RUNTIME_TRACING='true')
        subprocess.run([sys.executable, '-m', 'scripts.workflow_evaluate', '--output', str(baseline_file)],
                       check=True, capture_output=True, text=True, timeout=150, env=env)
        baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
        failures.extend('langgraph:'+name for name in baseline['failures'])
        for name, texts, expected in CASES:
            store, scope, questionnaires, item = create_fixture(directory, 'autogen-'+name, texts)
            started = time.monotonic()
            candidate = asyncio.run(run_experiment(Foundation(store, MemoryIndex()), scope, item['id'], 0))
            latency = round((time.monotonic()-started)*1000, 2)
            answer = candidate['answer']
            with store.connect() as db:
                citation_ok = not answer['evidence'] or valid(db, scope, answer['evidence'])
            unsupported = int(bool(answer['evidence']) and answer['draft'] != '\n'.join(hit['quote'] for hit in answer['evidence']))
            gold_ok = name != 'answerable' or ('AES-256' in answer['draft'] and bool(answer['evidence']))
            reason_ok = name == 'answerable' or candidate['reason'] == {
                'missing':'missing_evidence', 'conflict':'conflicting_evidence',
                'injection':'suspicious_source_instructions'}[name]
            actual = questionnaires.item(scope, item['id'])
            unchanged = actual['current_revision'] == 0 and actual['answer'] is None
            if (candidate['status'] != expected or not citation_ok or unsupported or not gold_ok
                    or not reason_ok or not unchanged or candidate['automatically_approved']):
                failures.append('autogen:'+name)
            row = {key:candidate[key] for key in ('status','reason','model_client_calls','llm_calls',
                    'embedding_calls','draft_provider_calls','cost_usd','automatically_approved','published','roles')}
            row.update(case=name, latency_ms=latency, citations=len(answer['evidence']),
                       citation_integrity=citation_ok, unsupported_claims=unsupported,
                       fixture_answer_correct=gold_ok, reason_correct=reason_ok,
                       input_units=candidate['input_units'], output_units=candidate['output_units'],
                       questionnaire_unchanged=unchanged)
            rows.append(row)
    baseline_rows = baseline['results']
    summaries = {}
    for label, results in [('langgraph', baseline_rows), ('autogen', rows)]:
        latencies = sorted(row['latency_ms'] for row in results)
        summaries[label] = {
            'cases':len(results), 'citation_integrity_cases':sum(row['citation_integrity'] for row in results),
            'unsupported_claims':sum(row['unsupported_claims'] for row in results),
            'automatic_approvals':sum(row['automatically_approved'] for row in results),
            'p50_latency_ms':round(statistics.median(latencies),2),
            'p95_latency_ms':latencies[math.ceil(.95*len(latencies))-1],
            'model_client_calls':sum(row['model_client_calls'] for row in results),
            'llm_calls':sum(row['llm_calls'] for row in results),
            'embedding_calls':sum(row['embedding_calls'] for row in results),
            'draft_provider_calls':sum(row['draft_provider_calls'] for row in results),
            'cost_usd':sum(row['cost_usd'] for row in results)}
    return {'version':'synthetic-autogen-comparison-v1', 'failures':failures,
        'provider':'deterministic offline replay and extractive fixtures',
        'versions':{name:importlib.metadata.version(name) for name in
                    ('autogen-core','autogen-agentchat','autogen-ext','langgraph')},
        'decision':'retain_langgraph_primary; autogen_learning_only',
        'decision_reason':'Same fixture correctness; ephemeral AutoGen lacks the durable publication, recovery and human-review lifecycle already enforced by T10. No learned-model benefit measured. AutoGen is in maintenance mode.',
        'summaries':summaries, 'results':{'langgraph':baseline_rows, 'autogen':rows},
        'limitations':'Four synthetic exact-extraction cases, not held-out learned-model quality. AutoGen replay selects tools; backend fixtures write/verify. Zero real LLM calls and paid cost. LangGraph latency includes durable checkpoints, unapproved publication and spawned workers; AutoGen returns an in-memory candidate with cooperative fixture deadlines, so timings are not equivalent production work. Byte units are not vendor tokenizer usage. No live providers or semantic-entailment claim.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='evals/autogen_comparison.json')
    args = parser.parse_args()
    report = compare()
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output':args.output,'failures':report['failures'],
                      'summaries':report['summaries'],'decision':report['decision']}, sort_keys=True))
    if report['failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
