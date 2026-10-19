CREATE TABLE IF NOT EXISTS workflow_jobs (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL,
 item_id TEXT NOT NULL, question TEXT NOT NULL, expected_revision INTEGER NOT NULL,
 request_key TEXT NOT NULL, payload_hash TEXT NOT NULL, options TEXT NOT NULL, profile TEXT NOT NULL,
 created_at REAL NOT NULL, deadline REAL NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
 sequence INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 retrievals INTEGER NOT NULL DEFAULT 0, input_units INTEGER NOT NULL DEFAULT 0,
 output_units INTEGER NOT NULL DEFAULT 0, reserved_cost TEXT NOT NULL DEFAULT '0',
 published_revision INTEGER, published_answer_id TEXT, failure_code TEXT,
 lease_owner TEXT, lease_until REAL, UNIQUE(tenant,id), UNIQUE(tenant,issuer,subject,request_key),
 FOREIGN KEY(tenant,item_id) REFERENCES questionnaire_items(tenant,id));
CREATE UNIQUE INDEX IF NOT EXISTS workflow_one_active ON workflow_jobs(tenant,item_id)
 WHERE status IN ('queued','running','retryable','awaiting_review');
CREATE TABLE IF NOT EXISTS workflow_steps (
 tenant TEXT NOT NULL, job_id TEXT NOT NULL, sequence INTEGER NOT NULL, phase TEXT NOT NULL,
 status TEXT NOT NULL, output TEXT, started_at REAL NOT NULL, finished_at REAL,
 PRIMARY KEY(tenant,job_id,sequence), FOREIGN KEY(tenant,job_id) REFERENCES workflow_jobs(tenant,id));
CREATE TABLE IF NOT EXISTS workflow_calls (
 tenant TEXT NOT NULL, job_id TEXT NOT NULL, attempt INTEGER NOT NULL, kind TEXT NOT NULL,
 input_hash TEXT NOT NULL, input_units INTEGER NOT NULL, output_units INTEGER NOT NULL,
 reserved_cost TEXT NOT NULL, status TEXT NOT NULL,
 PRIMARY KEY(tenant,job_id,attempt), FOREIGN KEY(tenant,job_id) REFERENCES workflow_jobs(tenant,id));
CREATE TRIGGER IF NOT EXISTS workflow_immutable_inputs BEFORE UPDATE OF
 id,tenant,issuer,subject,item_id,question,expected_revision,request_key,payload_hash,options,profile,created_at,deadline ON workflow_jobs
 BEGIN SELECT RAISE(ABORT,'Workflow inputs are immutable'); END;
