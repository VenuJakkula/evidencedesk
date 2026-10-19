"""Operator-only migration/purge for the disposable PostgreSQL retrieval index."""
import argparse
import os
from app.retrieval_index import PostgresIndex

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['migrate','purge'])
    parser.add_argument('--tenant')
    args=parser.parse_args()
    dsn=os.getenv('EVIDENCEDESK_RETRIEVAL_DSN','')
    if not dsn: raise SystemExit('Configure EVIDENCEDESK_RETRIEVAL_DSN')
    index=PostgresIndex(dsn)
    if args.action=='migrate':
        index.migrate();print('Retrieval schema migrated')
    else:
        if not args.tenant: raise SystemExit('purge requires an explicit --tenant')
        print('Purged derived chunks:',index.purge(args.tenant))

if __name__=='__main__': main()
