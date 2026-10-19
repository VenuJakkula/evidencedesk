CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS answers_tenant_id ON answers(tenant,id);
CREATE TABLE IF NOT EXISTS workbook_assets (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, filename TEXT NOT NULL,
 storage_key TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, size INTEGER NOT NULL,
 original BLOB NOT NULL, created_at TEXT NOT NULL, UNIQUE(tenant,id));
CREATE TRIGGER IF NOT EXISTS immutable_workbook BEFORE UPDATE ON workbook_assets
 BEGIN SELECT RAISE(ABORT,'Workbook originals are immutable'); END;
CREATE TABLE IF NOT EXISTS questionnaires (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, asset_id TEXT NOT NULL,
 mapping TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 UNIQUE(tenant,id), UNIQUE(tenant,idempotency_key),
 FOREIGN KEY(tenant,asset_id) REFERENCES workbook_assets(tenant,id));
CREATE TABLE IF NOT EXISTS questionnaire_items (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, questionnaire_id TEXT NOT NULL,
 provenance TEXT NOT NULL, question TEXT NOT NULL, owner TEXT,
 current_revision INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'imported',
 UNIQUE(tenant,id), FOREIGN KEY(tenant,questionnaire_id) REFERENCES questionnaires(tenant,id));
CREATE TABLE IF NOT EXISTS answer_revisions (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, item_id TEXT NOT NULL, revision INTEGER NOT NULL,
 answer_id TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT NOT NULL, creator TEXT NOT NULL,
 created_at TEXT NOT NULL, model_version TEXT NOT NULL, prompt_version TEXT NOT NULL,
 UNIQUE(tenant,item_id,revision), UNIQUE(tenant,id),
 FOREIGN KEY(tenant,item_id) REFERENCES questionnaire_items(tenant,id),
 FOREIGN KEY(tenant,answer_id) REFERENCES answers(tenant,id));
CREATE TRIGGER IF NOT EXISTS revision_tenant BEFORE INSERT ON answer_revisions
 WHEN NOT EXISTS(SELECT 1 FROM answers WHERE id=NEW.answer_id AND tenant=NEW.tenant)
 BEGIN SELECT RAISE(ABORT,'Answer tenant mismatch'); END;
CREATE TRIGGER IF NOT EXISTS immutable_revision BEFORE UPDATE ON answer_revisions
 BEGIN SELECT RAISE(ABORT,'Answer revisions are immutable'); END;
CREATE TABLE IF NOT EXISTS questionnaire_approvals (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision_id TEXT NOT NULL,
 reviewer TEXT NOT NULL, identity_verified INTEGER NOT NULL DEFAULT 0,
 decision TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(tenant,revision_id), FOREIGN KEY(tenant,revision_id) REFERENCES answer_revisions(tenant,id));
CREATE TABLE IF NOT EXISTS questionnaire_exports (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, questionnaire_id TEXT NOT NULL,
 manifest TEXT NOT NULL, output BLOB NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(tenant,questionnaire_id) REFERENCES questionnaires(tenant,id));
CREATE TRIGGER IF NOT EXISTS immutable_approval BEFORE UPDATE ON questionnaire_approvals
 BEGIN SELECT RAISE(ABORT,'Approvals are immutable'); END;
CREATE INDEX IF NOT EXISTS questionnaire_item_order ON questionnaire_items(tenant,questionnaire_id);
