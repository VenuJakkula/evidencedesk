"""Actual DSPy few-shot compilation with a deterministic offline LM, no paid calls."""
import json
import os
import time
from pathlib import Path
from importlib.metadata import version
from scripts.release_evaluate import load_cases


def observation(case):
    return json.dumps({'question':case['question'],'sources':case['sources'],
                       'applicability':case['applicability']},sort_keys=True)


def fixture_label(text):
    data=json.loads(text)
    sources=[source for source in data['sources'] if source.get('visible',True)
        and not source.get('foreign') and source.get('approved',True)
        and source.get('valid_until','2099-01-01') >= '2026-10-19'
        and all(source.get('metadata',{}).get(key)==value for key,value in data['applicability'].items())]
    content=' '.join(source['text'].lower() for source in sources)
    if not sources:return 'missing_evidence'
    if 'ignore previous instructions' in content:return 'suspicious_source_instructions'
    if any(len({source.get('metadata',{}).get(key) for source in sources})>1 for key in ['product','edition','deployment'] if key not in data['applicability']):return 'applicability_unspecified'
    if 'not encrypted' in content and any('encrypted' in source['text'] and 'not encrypted' not in source['text'] for source in sources):return 'conflicting_evidence'
    return 'answerable'


def main():
    os.environ['DSPY_CACHEDIR']=str(Path('output/dspy-cache').resolve())
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
    os.environ['LANGSMITH_TRACING']='false'
    import dspy
    from dspy.utils import DummyLM
    dspy.configure_cache(enable_disk_cache=False,enable_memory_cache=False)
    development=load_cases('development')
    train=[dspy.Example(observation=observation(case),label=case['reason'] or 'answerable').with_inputs('observation') for case in development]
    baseline=dspy.Predict('observation -> label')
    compiled=dspy.LabeledFewShot(k=4).compile(baseline,trainset=train)
    # Compilation ends before either validation or held-out labels are loaded.
    reports={}
    for split in ['validation','heldout']:
        cases=load_cases(split)
        reports[split]={}
        for name,program in [('fixed',baseline),('fewshot',compiled)]:
            correct=0;calls=0;start=time.monotonic()
            for case in cases:
                text=observation(case)
                # Derive the fixture response from input only, never from test labels.
                lm=DummyLM([{'label':fixture_label(text)}])
                with dspy.context(lm=lm,disable_history=True):
                    prediction=program(observation=text)
                calls+=1
                correct+=prediction.label==(case['reason'] or 'answerable')
            reports[split][name]={'correct':correct,'cases':len(cases),'fixture_model_calls':calls,
                'latency_ms':round((time.monotonic()-start)*1000,3),'paid_cost_usd':0}
    report={'version':'dspy-offline-classification-v1','dspy':version('dspy'),
        'optimizer':'LabeledFewShot(k=4)','training_cases':len(train),
        'compiled_demos':len(compiled.demos),'splits':reports,
        'decision':'retain fixed baseline; no measured learned-model benefit',
        'limitations':'Actual DSPy optimizer and Predict execution with rule-derived DummyLM outputs. Demos do not alter this fake model. Tests compilation and split discipline only, not prompt optimization quality. Synthetic near-duplicate splits, no human calibration, no paid calls.'}
    Path('evals/optimization_results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if any(values['fewshot']['correct']<values['fixed']['correct'] for values in reports.values()):raise SystemExit(1)

if __name__=='__main__':main()
