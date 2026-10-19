"""Small versioned retrieval ablation, not a semantic-model quality benchmark."""
import argparse
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from app.access import Principal
from app.core import Store
from app.evidence import Evidence
from app.retrieval import Foundation
from app.retrieval_index import MemoryIndex, PostgresIndex

CASES=[('encrypted','Encryption'),('ciphered','Encryption'),('TLS','Transport'),('recover','Recovery')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--postgres',action='store_true');args=parser.parse_args()
    if args.postgres and not os.getenv('EVIDENCEDESK_TEST_RETRIEVAL_DSN'): raise SystemExit('Configure EVIDENCEDESK_TEST_RETRIEVAL_DSN')
    tenant='retrieval-eval-'+uuid.uuid4().hex
    os.environ['EVIDENCEDESK_AUTH_MODE']='oidc'
    with tempfile.TemporaryDirectory(prefix='evidencedesk-retrieval-eval-') as directory:
        store=Store(Path(directory)/'eval.sqlite')
        scope=Principal(tenant,'https://synthetic.invalid','admin')
        with store.connect() as db: db.execute('INSERT INTO memberships VALUES(?,?,?,?,1)',(tenant,scope.issuer,scope.subject,'["admin"]'))
        evidence=Evidence(store);sources={}
        for title,text in [('Encryption','Data is encrypted.'),('Transport','Transport uses TLS.'),('Recovery','Backups recover data.')]:
            source=evidence.create(scope,title,text,'1','2099-01-01',{'product':'Synthetic'})
            evidence.approve(scope,source['id'],source['current_version']);sources[title]=source['id']
        index=PostgresIndex(os.environ['EVIDENCEDESK_TEST_RETRIEVAL_DSN']) if args.postgres else MemoryIndex()
        if args.postgres: index.migrate()
        service=Foundation(store,index)
        report={'version':'synthetic-retrieval-ablation-v1','cases':len(CASES),'backend':'postgres-pgvector' if args.postgres else 'memory-fixture','embedding_model':service.embedding.model,'chunking':'lines-exact-1000-v1','metrics':{}}
        try:
            for method in ['lexical','embedding','hybrid','hybrid_rerank']:
                recall=0;ndcg=0
                for question,title in CASES:
                    hits=service.run(scope,question,'hybrid' if method=='hybrid_rerank' else method,limit=3,rerank=method=='hybrid_rerank')['items']
                    rank=next((i for i,hit in enumerate(hits,1) if hit['source_id']==sources[title]),None)
                    recall+=rank is not None
                    ndcg+=1/math.log2(rank+1) if rank else 0
                report['metrics'][method]={'recall_at_3':recall/len(CASES),'ndcg_at_3':round(ndcg/len(CASES),4),'denominator':len(CASES)}
            print(json.dumps(report,sort_keys=True))
        finally:
            if args.postgres: index.purge(tenant)

if __name__=='__main__': main()
