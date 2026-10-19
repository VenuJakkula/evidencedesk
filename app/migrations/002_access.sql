CREATE TABLE IF NOT EXISTS memberships (
 tenant TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL,
 roles TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 PRIMARY KEY(tenant,issuer,subject));
CREATE TABLE IF NOT EXISTS evidence_sources (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, title TEXT NOT NULL,
 current_version TEXT, deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 UNIQUE(tenant,id));
CREATE TABLE IF NOT EXISTS evidence_versions (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, source_id TEXT NOT NULL, label TEXT NOT NULL,
 content TEXT NOT NULL, content_hash TEXT NOT NULL, valid_until TEXT NOT NULL, metadata TEXT NOT NULL,
 legacy_document_id TEXT, creator TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(tenant,id), UNIQUE(tenant,source_id,label),
 FOREIGN KEY(tenant,source_id) REFERENCES evidence_sources(tenant,id));
CREATE TABLE IF NOT EXISTS evidence_states (
 tenant TEXT NOT NULL, version_id TEXT NOT NULL, state TEXT NOT NULL,
 reviewer TEXT, reviewed_at TEXT, PRIMARY KEY(tenant,version_id),
 FOREIGN KEY(tenant,version_id) REFERENCES evidence_versions(tenant,id));
CREATE TABLE IF NOT EXISTS document_acl (
 tenant TEXT NOT NULL, source_id TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL,
 can_write INTEGER NOT NULL DEFAULT 0 CHECK(can_write IN (0,1)),
 PRIMARY KEY(tenant,source_id,issuer,subject),
 FOREIGN KEY(tenant,source_id) REFERENCES evidence_sources(tenant,id));
CREATE TABLE IF NOT EXISTS answer_dependencies (
 tenant TEXT NOT NULL, answer_id TEXT NOT NULL, version_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 PRIMARY KEY(tenant,answer_id,version_id),
 FOREIGN KEY(tenant,answer_id) REFERENCES answers(tenant,id),
 FOREIGN KEY(tenant,version_id) REFERENCES evidence_versions(tenant,id));
CREATE TABLE IF NOT EXISTS approval_invalidations (
 tenant TEXT NOT NULL, revision_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant,revision_id),
 FOREIGN KEY(tenant,revision_id) REFERENCES answer_revisions(tenant,id));
CREATE TABLE IF NOT EXISTS audit_events (
 id TEXT PRIMARY KEY, tenant TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
 resource_id TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_evidence_version_update BEFORE UPDATE ON evidence_versions
 BEGIN SELECT RAISE(ABORT,'Evidence versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_evidence_version_delete BEFORE DELETE ON evidence_versions
 BEGIN SELECT RAISE(ABORT,'Use evidence tombstones; versions are retained'); END;
CREATE TRIGGER IF NOT EXISTS immutable_audit_update BEFORE UPDATE ON audit_events
 BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_audit_delete BEFORE DELETE ON audit_events
 BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_dependency_update BEFORE UPDATE ON answer_dependencies
 BEGIN SELECT RAISE(ABORT,'Dependencies are immutable'); END;
CREATE INDEX IF NOT EXISTS dependency_version ON answer_dependencies(tenant,version_id);
