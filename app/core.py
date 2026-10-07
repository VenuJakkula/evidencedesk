"""Deterministic, extractive baseline. This is not a live LLM or vector RAG engine."""
import csv
import io
import json
import re
import sqlite3
import time
import uuid
from datetime import date

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
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db
    def add_document(self, tenant, title, content, version, valid_until):
        date.fromisoformat(valid_until)
        identifier = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                       (identifier, tenant, title, content, version, valid_until))
        return identifier
    def draft(self, tenant, question):
        start = time.perf_counter()
        query = terms(question)
        with self.connect() as db:
            docs = db.execute("SELECT * FROM documents WHERE tenant=? AND valid_until>=?",
                              (tenant, date.today().isoformat())).fetchall()
        candidates = []
        for doc in docs:
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", doc["content"]):
                overlap = query & terms(sentence)
                if overlap:
                    candidates.append((len(overlap)/max(len(query),1), doc, sentence))
        candidates.sort(key=lambda row: row[0], reverse=True)
        selected = candidates[:3] if candidates and candidates[0][0] >= .34 else []
        evidence = [{"document_id": d["id"], "title": d["title"], "version": d["version"], "quote": s}
                    for _, d, s in selected]
        draft = "\n".join(e["quote"] for e in evidence) if evidence else "Insufficient approved evidence. Assign to a subject-matter expert."
        status = "needs_review" if evidence else "needs_evidence"
        identifier = str(uuid.uuid4())
        trace = {"trace_id": str(uuid.uuid4()), "retrieved_sentences": len(evidence),
                 "latency_ms": round((time.perf_counter()-start)*1000, 3),
                 "provider": "extractive-baseline", "llm_calls": 0, "cost_usd": 0,
                 "retrieval": "lexical-overlap", "workflow": ["retrieve", "extract", status]}
        with self.connect() as db:
            db.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)",
                       (identifier, tenant, question, draft, json.dumps(evidence), status, None, None, json.dumps(trace)))
        return self.get(tenant, identifier)
    def get(self, tenant, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM answers WHERE tenant=? AND id=?", (tenant, identifier)).fetchone()
        if row is None:
            raise KeyError(identifier)
        answer = dict(row)
        answer["evidence"] = json.loads(answer["evidence"])
        answer["trace"] = json.loads(answer["trace"])
        return answer
    def approve(self, tenant, identifier, reviewer, final):
        if not reviewer.strip() or not final.strip():
            raise ValueError("Reviewer and final answer are required")
        with self.connect() as db:
            result = db.execute("UPDATE answers SET status='approved', reviewer=?, final=? WHERE tenant=? AND id=? AND status='needs_review'",
                                (reviewer, final, tenant, identifier))
            if result.rowcount != 1:
                raise ValueError("Only an existing answer with evidence awaiting review can be approved")
        return self.get(tenant, identifier)
    def export(self, tenant):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM answers WHERE tenant=? AND status='approved' ORDER BY rowid", (tenant,)).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Question", "Approved answer", "Evidence", "Reviewer"])
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for row in rows:
            writer.writerow([safe(row[k]) for k in ("question", "final", "evidence", "reviewer")])
        return output.getvalue()
