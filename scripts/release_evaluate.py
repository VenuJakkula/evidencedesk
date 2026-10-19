"""Split synthetic release gate. Held-out labels are never read by the optimizer."""
import argparse
import hashlib
import json
import math
import tempfile
import time
from datetime import date
from unittest.mock import patch
from pathlib import Path
from importlib.metadata import version
from app.access import Principal
from app.core import Store
from app.evidence import Evidence, valid
from app.retrieval import Foundation
from app.retrieval_index import MemoryIndex
from app.workflows import Workflows

ROOT = Path(__file__).resolve().parents[1]


def load_cases(split):
    if split not in {'development','validation','heldout'}: raise ValueError('Explicit split required')
    return json.loads((ROOT/'evals'/'release'/f'{split}.json').read_text(encoding='utf-8'))


def run_case(case, method, provider=None):
    with tempfile.TemporaryDirectory(prefix='evidencedesk-release-') as directory:
        store = Store(Path(directory)/'fixture.sqlite')
        owner = Principal('synthetic', 'https://synthetic.invalid', 'author')
        admin = Principal('synthetic', owner.issuer, 'admin')
        other = Principal('foreign', owner.issuer, 'foreign-admin')
        with store.connect() as db:
            for scope in [owner, admin, other]:
                db.execute('INSERT INTO memberships VALUES(?,?,?,?,1)',
                           (str(scope), scope.issuer, scope.subject, '["admin"]' if scope != owner or scope.subject != owner.subject else '["author"]'))
        evidence = Evidence(store)
        sources = {}
        for i, source in enumerate(case['sources']):
            creator = other if source.get('foreign') else admin
            created = evidence.create(creator, 'Synthetic '+str(i), source['text'], '1',
                source.get('valid_until', '2099-01-01'), source.get('metadata', {}))
            if source.get('approved', True):
                if source.get('valid_until', '2099-01-01') < date.today().isoformat():
                    class HistoricalDate(date):
                        @classmethod
                        def today(cls): return cls(2019,1,1)
                    with patch('app.evidence.date',HistoricalDate):
                        evidence.approve(creator, created['id'], created['current_version'])
                else: evidence.approve(creator, created['id'], created['current_version'])
            if source.get('visible', True) and not source.get('foreign'):
                evidence.acl(admin, created['id'], owner.subject)
            sources[i] = created['id']
        foundation = Foundation(store, MemoryIndex(),provider=provider)
        policy = Workflows(store, foundation)
        start = time.monotonic()
        result = foundation.run(owner, case['question'], method, 5, case['applicability'])
        hits = result['items']
        reasons = policy.assess(case['question'], hits, case['applicability'], foundation)
        trace = result['trace']
        answer = policy.abstain(reasons) if reasons else foundation.generate(
            case['question'], hits, case['applicability'], foundation.clock()+10, trace)
        with store.connect() as db:
            integrity = not answer['evidence'] or valid(db, owner, answer['evidence'])
        retrieved = {hit['source_id'] for hit in hits}
        gold = {sources[i] for i in case['gold_sources']}
        recall = len(gold & retrieved)/len(gold) if gold else None
        dcg = sum(1/math.log2(rank+2) for rank,hit in enumerate(hits) if hit['source_id'] in gold)
        ideal = sum(1/math.log2(rank+2) for rank in range(min(5,len(gold))))
        expected_abstention = case['reason'] is not None
        abstained = answer['status'] == 'needs_evidence'
        facts = all(fact in answer['draft'] for fact in case['expected_facts'])
        unauthorized = any(hit['source_id'] not in {sources[i] for i,s in enumerate(case['sources'])
            if s.get('visible', True) and not s.get('foreign') and s.get('approved', True) and s.get('valid_until','2099-01-01') >= date.today().isoformat()} for hit in hits)
        supported = answer['draft'] == '\n'.join(claim['text'] for claim in answer['claims']) if not abstained else True
        correct = abstained == expected_abstention and facts and (not expected_abstention or case['reason'] in answer['uncertainty'])
        return {'id':case['id'], 'kind':case['kind'], 'correct':correct,
            'abstained':abstained, 'expected_abstention':expected_abstention,
            'reason_correct':not expected_abstention or case['reason'] in answer['uncertainty'],
            'citation_integrity':bool(integrity), 'unsupported_claims':int(not supported),
            'unauthorized_evidence':int(unauthorized), 'recall_at_5':recall,
            'ndcg_at_5':dcg/ideal if ideal else None, 'latency_ms':round((time.monotonic()-start)*1000,3),
            'model_calls':trace['provider_calls'], 'cost_usd':0, 'automatic_approvals':0}


def summarize(rows):
    latencies = sorted(row['latency_ms'] for row in rows)
    gold = [row for row in rows if row['recall_at_5'] is not None]
    negatives = [row for row in rows if row['expected_abstention']]
    positives = [row for row in rows if not row['expected_abstention']]
    contradictions = [row for row in rows if row['kind'] == 'contradiction']
    return {'cases':len(rows), 'correct':sum(row['correct'] for row in rows),
        'citation_integrity':sum(row['citation_integrity'] for row in rows),
        'unsupported_claims':sum(row['unsupported_claims'] for row in rows),
        'unauthorized_evidence':sum(row['unauthorized_evidence'] for row in rows),
        'automatic_approvals':sum(row['automatic_approvals'] for row in rows),
        'recall_at_5':sum(row['recall_at_5'] for row in gold)/len(gold),
        'ndcg_at_5':sum(row['ndcg_at_5'] for row in gold)/len(gold), 'gold_cases':len(gold),
        'abstention_recall':sum(row['abstained'] for row in negatives)/len(negatives), 'unanswerable_cases':len(negatives),
        'answerable_coverage':sum(not row['abstained'] for row in positives)/len(positives), 'answerable_cases':len(positives),
        'contradiction_detection':sum(row['reason_correct'] for row in contradictions)/len(contradictions), 'contradiction_cases':len(contradictions),
        'p50_ms':latencies[len(rows)//2], 'p95_ms':latencies[math.ceil(.95*len(rows))-1],
        'model_calls':sum(row['model_calls'] for row in rows), 'cost_usd':0,
        'review_edit_rate':None, 'review_time_seconds':None}


def evaluate(split='heldout', method='hybrid'):
    cases = load_cases(split)
    rows = [run_case(case,method) for case in cases]
    metrics = summarize(rows)
    thresholds = json.loads((ROOT/'evals/release/thresholds.json').read_text(encoding='utf-8'))
    failures = [key for key,minimum in thresholds['minimum'].items() if metrics[key] < minimum]
    failures += [key for key,maximum in thresholds['maximum'].items() if metrics[key] > maximum]
    if metrics['correct'] != len(rows): failures.append('correct')
    if metrics['citation_integrity'] != len(rows): failures.append('citation_integrity')
    return {'version':'release-synthetic-v1', 'split':split, 'method':method,
        'dataset_sha256':hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest(),
        'versions':{name:version(name) for name in ['langgraph','langsmith']},
        'embedding':'fixture-hash64-synonyms-v1', 'provider':'extractive-claims-v1',
        'label_review':'synthetic author labels; human calibration pending',
        'metrics':metrics, 'failures':failures, 'results':rows,
        'limitations':'Deterministic extraction and policy evaluation; not a learned-model, full-workflow, human-review or production benchmark. Zero paid cost.'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['development','validation','heldout'],default='heldout')
    parser.add_argument('--method',choices=['lexical','embedding','hybrid'],default='hybrid')
    parser.add_argument('--output',default='evals/release_results.json')
    args=parser.parse_args()
    report=evaluate(args.split,args.method)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'split':args.split, 'metrics':report['metrics'],'failures':report['failures']}))
    if report['failures']: raise SystemExit(1)

if __name__ == '__main__': main()
