"""Advance one durable workflow phase using a fresh verified operator-supplied token."""
import argparse
import json
import os
from app.access import mode, verify
from app.core import Store
from app.workflows import Workflows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('job_id');args=parser.parse_args()
    token=os.getenv('EVIDENCEDESK_WORKFLOW_TOKEN','')
    if mode()!='oidc' or not token: raise SystemExit('Configure OIDC and EVIDENCEDESK_WORKFLOW_TOKEN')
    scope=verify(token,os.getenv('EVIDENCEDESK_TENANT','demo'))
    store=Store(os.getenv('EVIDENCEDESK_DB','evidencedesk.db'))
    job=Workflows(store).advance(scope,args.job_id)
    print(json.dumps({key:job[key] for key in ['id','status','phase','published_revision','review_decision','failure_code']}))

if __name__=='__main__': main()
