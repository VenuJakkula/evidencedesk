"""Deterministic, extractive baseline. This is not a live LLM or vector RAG engine."""
import csv
import os
import io
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import date
from .access import Principal, actor, require
from .evidence import audit, record_dependencies, valid, visible_answer, synchronize_expiry, reviewer_valid

STOP = {"a", "an", "the", "is", "are", "do", "does", "you", "your", "we", "our", "and", "of", "to", "in", "for", "with", "have", "what"}
def terms(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, title TEXT NOT NULL,
              content TEXT NOT NULL, version TEXT NOT NULL, valid_until TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS answers (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, question TEXT NOT NULL,
              draft TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL,
              final TEXT, reviewer TEXT, trace TEXT NOT NULL);
            """)
            migration = Path(__file__).parent / 'migrations/001_questionnaires.sql'
            db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text() +
                             "\nINSERT OR IGNORE INTO schema_migrations VALUES (1,strftime('%Y-%m-%dT%H:%M:%fZ','now'));\nCOMMIT;")
            migration = Path(__file__).parent / 'migrations/002_access.sql'
            db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding='utf-8-sig') +
                             "\nINSERT OR IGNORE INTO schema_migrations VALUES (2,strftime('%Y-%m-%dT%H:%M:%fZ','now'));\nCOMMIT;")
            migration = Path(__file__).parent / 'migrations/003_workflows.sql'
            db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding='utf-8-sig') +
                             "\nINSERT OR IGNORE INTO schema_migrations VALUES (3,strftime('%Y-%m-%dT%H:%M:%fZ','now'));\nCOMMIT;")
            from .evidence import migrate_legacy
            migrate_legacy(db)
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()
    def add_document(self, tenant, title, content, version, valid_until):
        if isinstance(tenant, Principal):
            from .workbooks import Problem
            raise Problem('lifecycle_required', 'Use the evidence lifecycle endpoints in OIDC mode.', 403)
        date.fromisoformat(valid_until)
        identifier = str(uuid.uuid4())
        with self.connect() as db:
            require(db, tenant, 'author')
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                       (identifier, tenant, title, content, version, valid_until))
        return identifier
    def draft(self, tenant, question):
        start = time.perf_counter()
        foundation_result = None
        engine = os.getenv('EVIDENCEDESK_DRAFT_ENGINE','baseline')
        if engine not in {'baseline','foundation'}:
            from .workbooks import Problem
            raise Problem('draft_engine','Unsupported draft engine.',503)
        if engine == 'foundation':
            from .retrieval import configured
            foundation_result = configured(self).run(tenant,question,draft=True)
            evidence, draft, status = (foundation_result[name] for name in ('evidence','draft','status'))
        else:
            query = terms(question)
            with self.connect() as db:
                current = require(db, tenant, 'author')
                synchronize_expiry(db, tenant)
                if isinstance(tenant, Principal):
                    clause = '' if 'admin' in current else ' AND EXISTS (SELECT 1 FROM document_acl a WHERE a.tenant=v.tenant AND a.source_id=v.source_id AND a.issuer=? AND a.subject=?)'
                    params = [str(tenant), date.today().isoformat()] + ([] if 'admin' in current else [tenant.issuer, tenant.subject])
                    docs = db.execute("""SELECT v.id,s.title,v.content,v.label AS version,v.valid_until,v.source_id,v.content_hash
                        FROM evidence_versions v JOIN evidence_sources s ON s.tenant=v.tenant AND s.id=v.source_id
                        JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id
                        WHERE v.tenant=? AND v.valid_until>=? AND st.state='approved' AND s.deleted=0 AND s.current_version=v.id""" + clause, params).fetchall()
                else:
                    docs = db.execute("SELECT * FROM documents WHERE tenant=? AND valid_until>=?", (tenant, date.today().isoformat())).fetchall()
            candidates = []
            for doc in docs:
                for sentence in re.split(r"(?<=[.!?])\s+|\n+", doc["content"]):
                    overlap = query & terms(sentence)
                    if overlap:
                        candidates.append((len(overlap)/max(len(query),1), doc, sentence))
            candidates.sort(key=lambda row: row[0], reverse=True)
            selected = candidates[:3] if candidates and candidates[0][0] >= .34 else []
            evidence = [{"document_id": d["id"], "title": d["title"], "version": d["version"], "quote": s, **({"version_id": d["id"], "source_id": d["source_id"], "content_hash": d["content_hash"]} if isinstance(tenant, Principal) else {})}
                        for _, d, s in selected]
            draft = "\n".join(e["quote"] for e in evidence) if evidence else "Insufficient approved evidence. Assign to a subject-matter expert."
            status = "needs_review" if evidence else "needs_evidence"
        identifier = str(uuid.uuid4())
        trace = {"trace_id": str(uuid.uuid4()), "retrieved_sentences": len(evidence),
                 "latency_ms": round((time.perf_counter()-start)*1000, 3),
                 "provider": "extractive-baseline", "llm_calls": 0, "cost_usd": 0,
                 "retrieval": "lexical-overlap", "workflow": ["retrieve", "extract", status]}
        if foundation_result is not None:
            trace.update(foundation_result['trace'])
            trace['provider'] = foundation_result['trace']['model']
            trace['workflow'] = ['retrieve','validate_claims',status]
            trace['uncertainty'] = foundation_result['uncertainty']
            # A gateway can bill independently; no invented token/cost estimates.
            if os.getenv('EVIDENCEDESK_MODEL_PROVIDER','fixture') == 'gateway':
                trace['llm_calls'] = foundation_result['trace']['provider_calls']
                trace['cost_usd'] = None
        with self.connect() as db:
            if isinstance(tenant, Principal):
                db.execute('BEGIN IMMEDIATE')
                require(db, tenant, 'author')
                if evidence and not valid(db, tenant, evidence):
                    from .workbooks import Problem
                    raise Problem('evidence_changed', 'Evidence access changed; retry drafting.', 409)
            db.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)",
                       (identifier, tenant, question, draft, json.dumps(evidence), status, None, None, json.dumps(trace)))
            record_dependencies(db, tenant, identifier, evidence)
            if isinstance(tenant, Principal):
                audit(db, tenant, 'answer.drafted', identifier)
        return self.get(tenant, identifier)
    def get(self, tenant, identifier):
        with self.connect() as db:
            require(db, tenant)
            synchronize_expiry(db, tenant)
            row = db.execute("SELECT * FROM answers WHERE tenant=? AND id=?", (tenant, identifier)).fetchone()
        if row is None:
            raise KeyError(identifier)
        answer = dict(row)
        answer["evidence"] = json.loads(answer["evidence"])
        answer["trace"] = json.loads(answer["trace"])
        with self.connect() as db:
            require(db, tenant)
            return visible_answer(db, tenant, answer)
    def approve(self, tenant, identifier, reviewer, final):
        if isinstance(tenant, Principal):
            reviewer = actor(tenant)
        if not reviewer.strip() or not final.strip():
            raise ValueError("Reviewer and final answer are required")
        with self.connect() as db:
            if isinstance(tenant, Principal):
                db.execute('BEGIN IMMEDIATE')
            require(db, tenant, 'reviewer')
            if isinstance(tenant, Principal):
                row = db.execute('SELECT evidence FROM answers WHERE tenant=? AND id=?', (str(tenant),identifier)).fetchone()
                if not row or not valid(db, tenant, json.loads(row['evidence'])):
                    from .workbooks import Problem
                    raise Problem('stale_evidence','Authorized current evidence is required.',409)
            result = db.execute("UPDATE answers SET status='approved', reviewer=?, final=? WHERE tenant=? AND id=? AND status='needs_review'",
                                (reviewer, final, tenant, identifier))
            if result.rowcount != 1:
                raise ValueError("Only an existing answer with evidence awaiting review can be approved")
            if isinstance(tenant, Principal):
                audit(db, tenant, 'answer.approved', identifier)
        return self.get(tenant, identifier)
    def export(self, tenant):
        with self.connect() as db:
            if isinstance(tenant, Principal):
                db.execute('BEGIN IMMEDIATE')
            require(db, tenant, 'reviewer')
            if isinstance(tenant, Principal):
                synchronize_expiry(db, tenant)
            rows = db.execute("SELECT * FROM answers WHERE tenant=? AND status='approved' ORDER BY rowid", (tenant,)).fetchall()
            if isinstance(tenant, Principal):
                rows = [row for row in rows if valid(db, tenant, json.loads(row['evidence'])) and reviewer_valid(db,tenant,row['reviewer'],json.loads(row['evidence']))]
                audit(db, tenant, 'answers.exported', str(tenant), {'selected':len(rows)})
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Question", "Approved answer", "Evidence", "Reviewer"])
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for row in rows:
            writer.writerow([safe(row[k]) for k in ("question", "final", "evidence", "reviewer")])
        return output.getvalue()
