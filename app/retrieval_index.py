"""Rebuildable retrieval index; authoritative access remains in the workflow store."""
import math
from pathlib import Path
import psycopg
from .workbooks import Problem


def fuse(lexical, vector, limit, method):
    if method=='lexical': return lexical[:limit]
    if method=='embedding': return vector[:limit]
    scores={}
    for ranking in [lexical,vector]:
        for position,identifier in enumerate(ranking,1):
            scores[identifier]=scores.get(identifier,0)+1/(60+position)
    return sorted(scores,key=lambda identifier:(-scores[identifier],identifier))[:limit]


class MemoryIndex:
    """Explicit deterministic fixture backend; never an automatic PostgreSQL fallback."""
    def replace(self,tenant,corpus,profile,chunks,vectors):
        self.key=(tenant,corpus,profile)
        self.rows=list(zip(chunks,vectors))
    def search(self,tenant,corpus,profile,query,vector,limit,method):
        from .core import terms
        if self.key!=(tenant,corpus,profile): raise Problem('index_scope','Index scope mismatch.',503)
        lexical=[]; semantic=[]
        for chunk,embedding in self.rows:
            overlap=len(terms(query)&terms(chunk['quote']))
            if overlap: lexical.append((overlap,chunk['chunk_id']))
            score=sum(a*b for a,b in zip(vector,embedding))/max(math.sqrt(sum(a*a for a in vector))*math.sqrt(sum(b*b for b in embedding)),1e-12)
            if score>=0.25: semantic.append((score,chunk['chunk_id']))
        lexical=[key for _,key in sorted(lexical,key=lambda row:(-row[0],row[1]))[:50]]
        semantic=[key for _,key in sorted(semantic,key=lambda row:(-row[0],row[1]))[:50]]
        return fuse(lexical,semantic,limit,method)


class PostgresIndex:
    def __init__(self,dsn): self.dsn=dsn
    def connect(self):
        return psycopg.connect(self.dsn,connect_timeout=5,options='-c statement_timeout=10000 -c lock_timeout=5000')
    def migrate(self):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(98201309)")
            db.execute((Path(__file__).parent/'postgres_migrations/001_retrieval.sql').read_text(encoding='utf-8-sig'))
    @staticmethod
    def vector(values): return '['+','.join(str(float(value)) for value in values)+']'
    def replace(self,tenant,corpus,profile,chunks,vectors):
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(tenant+corpus+profile,))
            db.execute('DELETE FROM retrieval_chunks WHERE tenant=%s AND corpus=%s AND profile=%s',(tenant,corpus,profile))
            with db.cursor() as cursor:
                cursor.executemany('INSERT INTO retrieval_chunks(tenant,corpus,profile,chunk_id,quote,embedding) VALUES(%s,%s,%s,%s,%s,%s::vector)',
                    [(tenant,corpus,profile,chunk['chunk_id'],chunk['quote'],self.vector(vector)) for chunk,vector in zip(chunks,vectors)])
    def search(self,tenant,corpus,profile,query,vector,limit,method):
        with self.connect() as db:
            scope=(tenant,corpus,profile)
            lexical=[row[0] for row in db.execute('''SELECT chunk_id FROM retrieval_chunks
                WHERE tenant=%s AND corpus=%s AND profile=%s AND lexical @@ plainto_tsquery('english',%s)
                ORDER BY ts_rank_cd(lexical,plainto_tsquery('english',%s)) DESC,chunk_id LIMIT 50''',(*scope,query,query))]
            value=self.vector(vector)
            semantic=[row[0] for row in db.execute('''SELECT chunk_id FROM retrieval_chunks
                WHERE tenant=%s AND corpus=%s AND profile=%s AND 1-(embedding <=> %s::vector)>=0.25
                ORDER BY embedding <=> %s::vector,chunk_id LIMIT 50''',(*scope,value,value))]
            return fuse(lexical,semantic,limit,method)
    def purge(self,tenant):
        with self.connect() as db:
            return db.execute('DELETE FROM retrieval_chunks WHERE tenant=%s',(tenant,)).rowcount
