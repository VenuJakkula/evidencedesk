"""Operator-only bootstrap and SQLite backup/restore helpers; no web bootstrap endpoint."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
from app.core import Store
from app.access import Principal
from app.evidence import audit


def copy_database(source,destination):
    source=Path(source).resolve(strict=True); destination=Path(destination).resolve()
    if source==destination or destination.exists():
        raise ValueError('Choose a new destination; existing databases are never overwritten.')
    original=sqlite3.connect(f'{source.as_uri()}?mode=ro',uri=True)
    try:
        # Reserve the destination exclusively; a concurrent operator cannot make us overwrite it.
        with destination.open('xb'):
            pass
        target=sqlite3.connect(destination)
        try:
            with target:
                original.backup(target)
        finally:
            target.close()
    finally:
        original.close()
    return str(destination)


def bootstrap(path,tenant,issuer,subject):
    if not issuer.startswith('https://') or not tenant or not subject:
        raise ValueError('Use a tenant, HTTPS issuer and verified provider subject.')
    store=Store(path)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM memberships WHERE tenant=?',(tenant,)).fetchone():
            raise ValueError('Tenant already provisioned; use authenticated membership management.')
        db.execute('INSERT INTO memberships VALUES (?,?,?,?,1)',(tenant,issuer,subject,'["admin"]'))
        audit(db,Principal(tenant,issuer,subject),'tenant.operator_bootstrap',tenant)


def main():
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ['backup','restore']:
        command=commands.add_parser(name); command.add_argument('source'); command.add_argument('destination')
    command=commands.add_parser('bootstrap'); command.add_argument('database'); command.add_argument('tenant'); command.add_argument('issuer'); command.add_argument('subject')
    args=parser.parse_args()
    if args.command=='bootstrap':
        bootstrap(args.database,args.tenant,args.issuer,args.subject)
    else:
        copy_database(args.source,args.destination)
        if args.command=='restore':
            Store(args.destination)
    print('Completed without overwriting an existing database.')

if __name__=='__main__':
    main()
