"""Measure two offline adapters on development cases; persist a provisional route."""
import json
from pathlib import Path
from app.providers import ExtractiveProvider
from app.provider_router import Peer, RoutedDraft
from scripts.release_evaluate import load_cases, run_case, summarize


class SingleQuoteProvider(ExtractiveProvider):
    model='extractive-single-quote-v1'
    def draft(self, question, chunks, timeout):
        return super().draft(question,chunks[:1],timeout)


def main():
    cases=load_cases('development')
    providers={'baseline':ExtractiveProvider(),'single_quote':SingleQuoteProvider()}
    metrics={name:summarize([run_case(case,'hybrid',provider) for case in cases]) for name,provider in providers.items()}
    # Prefer correctness and integrity before cost or latency. No held-out tuning.
    preferred=min(metrics,key=lambda name:(-metrics[name]['correct'],metrics[name]['unsupported_claims'],
        metrics[name]['unauthorized_evidence'],metrics[name]['cost_usd'],metrics[name]['p95_ms']))
    router=RoutedDraft([Peer(name,provider,'local','synthetic-only',0) for name,provider in providers.items()],
        preferred,region='local',privacy='synthetic-only',max_price=0)
    assert router.draft('Synthetic question',[],1)['claims']==[]
    report={'version':'offline-routing-comparison-v1','split':'development','metrics':metrics,
        'provisional_preferred':preferred,'selection_order':['correctness','unsupported claims','unauthorized evidence','cost','p95 latency'],
        'primary_workflow_adoption':False,'decision':'retain primary fixed adapter; offline routing is a separate experiment',
        'limitations':'Two deterministic extractive adapters, not independent paid model providers. Timings cover fixture services and are not provider SLAs. No real privacy/residency or live cost validation. Existing workflow budgets do not accept this experimental router.'}
    Path('evals/routing_results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if any(row['correct']!=len(cases) or row['unsupported_claims'] or row['unauthorized_evidence'] for row in metrics.values()):raise SystemExit(1)

if __name__=='__main__':main()
