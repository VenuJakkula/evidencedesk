CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS retrieval_migrations(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS retrieval_chunks (
 tenant text NOT NULL, corpus text NOT NULL, profile text NOT NULL, chunk_id text NOT NULL,
 quote text NOT NULL, embedding vector(64) NOT NULL,
 lexical tsvector GENERATED ALWAYS AS (to_tsvector('english',quote)) STORED,
 PRIMARY KEY(tenant,corpus,profile,chunk_id)
);
CREATE INDEX IF NOT EXISTS retrieval_chunks_scope ON retrieval_chunks(tenant,corpus,profile);
CREATE INDEX IF NOT EXISTS retrieval_chunks_lexical ON retrieval_chunks USING gin(lexical);
INSERT INTO retrieval_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
