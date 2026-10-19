"""Keep a single documented learning-only finding visible; fail on any new finding."""
import json
import subprocess
import sys
from pathlib import Path


def main():
    output=Path('evals/learning_audit.json')
    result=subprocess.run([sys.executable,'-m','pip_audit','--no-deps','--disable-pip',
        '-r','requirements.ci.lock','--format','json','--output',str(output)],check=False)
    if result.returncode not in (0,1) or not output.exists():raise SystemExit(1)
    report=json.loads(output.read_text(encoding='utf-8'))
    unexpected=[];known=[]
    for dependency in report['dependencies']:
        if dependency.get('skip_reason'):unexpected.append({'package':dependency['name'],'reason':'unscanned'})
        for finding in dependency.get('vulns',[]):
            item={'package':dependency['name'],'id':finding['id']}
            aliases={finding['id'],*finding.get('aliases',[])}
            if dependency['name']=='diskcache' and 'GHSA-w8v5-vhqr-4h9v' in aliases:
                known.append(item)
            else:unexpected.append(item)
    print(json.dumps({'documented_learning_only_findings':known,'unexpected_findings':unexpected,
        'runtime_exclusion':'DSPy/DiskCache are not in requirements.lock; experiment disk cache disabled',
        'review_required_before_broader_use':bool(known)}))
    if unexpected:raise SystemExit(1)

if __name__=='__main__':main()
