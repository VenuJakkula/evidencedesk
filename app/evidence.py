"""Immutable text versions, live ACL filtering, snapshots and append-only audit events."""
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from .access import Principal, actor, can_read, require
from .workbooks import Problem
from .observability import traced


def timestamp():
    return datetime.now(timezone.utc).isoformat()

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def audit(db, scope, action, resource, details=None):
    db.execute('INSERT INTO audit_events VALUES (?,?,?,?,?,?,?)',
               (str(uuid.uuid4()), str(scope), actor(scope), action, resource, json.dumps(details or {}), timestamp()))


def migrate_legacy(db):
    # Existing content is preserved as a pending immutable snapshot, never auto-approved for enterprise use.
    rows = db.execute('SELECT * FROM documents WHERE id NOT IN (SELECT legacy_document_id FROM evidence_versions WHERE legacy_document_id IS NOT NULL)').fetchall()
    for row in rows:
        db.execute('INSERT OR IGNORE INTO evidence_sources VALUES (?,?,?,?,?,?)',
                   (row['id'], row['tenant'], row['title'], row['id'], 0, timestamp()))
        db.execute('INSERT OR IGNORE INTO evidence_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (row['id'], row['tenant'], row['id'], row['version'], row['content'], digest(row['content']), row['valid_until'],
                    json.dumps({'origin': 'legacy-migration'}), row['id'], 'legacy (unverified)', timestamp()))
        db.execute('INSERT OR IGNORE INTO evidence_states VALUES (?,?,?,?,?)', (row['tenant'], row['id'], 'pending', None, None))
    for answer in db.execute('SELECT id,tenant,evidence FROM answers').fetchall():
        entries=json.loads(answer['evidence'])
        if not isinstance(entries,list): continue
        for entry in entries:
            version=db.execute('SELECT id,content_hash,content,label FROM evidence_versions WHERE tenant=? AND legacy_document_id=?',(answer['tenant'],entry.get('document_id',''))).fetchone()
            if version and entry.get('version')==version['label'] and entry.get('quote') and entry['quote'] in version['content']:
                db.execute('INSERT OR IGNORE INTO answer_dependencies VALUES (?,?,?,?)',(answer['tenant'],answer['id'],version['id'],version['content_hash']))



def invalidate_answers(db, tenant, answer_ids, reason):
    for answer_id in answer_ids:
        rows = db.execute('SELECT id FROM answer_revisions WHERE tenant=? AND answer_id=?', (str(tenant), answer_id)).fetchall()
        for row in rows:
            db.execute('INSERT OR IGNORE INTO approval_invalidations VALUES (?,?,?,?)', (str(tenant), row['id'], reason, timestamp()))
            db.execute("UPDATE questionnaire_items SET status='needs_evidence' WHERE tenant=? AND id IN (SELECT item_id FROM answer_revisions WHERE id=? AND revision=current_revision)", (str(tenant), row['id']))
        db.execute("UPDATE answers SET status='needs_evidence' WHERE tenant=? AND id=?", (str(tenant), answer_id))


def invalidate_versions(db, scope, version_ids, reason):
    for version_id in version_ids:
        ids = [row[0] for row in db.execute('SELECT answer_id FROM answer_dependencies WHERE tenant=? AND version_id=?', (str(scope), version_id))]
        invalidate_answers(db, scope, ids, reason)
    if version_ids:
        audit(db, scope, 'evidence.invalidated', version_ids[0], {'reason': reason, 'versions': len(version_ids)})


def synchronize_expiry(db, scope):
    if not isinstance(scope, Principal):
        return
    ids=[row[0] for row in db.execute("SELECT v.id FROM evidence_versions v JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id WHERE v.tenant=? AND v.valid_until<? AND st.state='approved'",(str(scope),date.today().isoformat()))]
    for identifier in ids:
        db.execute("UPDATE evidence_states SET state='expired' WHERE tenant=? AND version_id=?",(str(scope),identifier))
    invalidate_versions(db,scope,ids,'source_expired')


def record_dependencies(db, scope, answer_id, evidence):
    for entry in evidence:
        if entry.get('version_id'):
            db.execute('INSERT OR IGNORE INTO answer_dependencies VALUES (?,?,?,?)',
                       (str(scope), answer_id, entry['version_id'], entry['content_hash']))


def reviewer_valid(db, scope, identity, evidence):
    if not identity or '|' not in identity:
        return False
    issuer,subject=identity.split('|',1)
    reviewer=Principal(str(scope),issuer,subject)
    try:
        require(db,reviewer,'reviewer')
        return all(can_read(db,reviewer,entry.get('source_id','')) for entry in evidence)
    except Problem:
        return False


def global_valid(db, scope, entry):
    row = db.execute('''SELECT v.*, s.current_version, s.deleted, st.state,st.reviewer FROM evidence_versions v
        JOIN evidence_sources s ON s.tenant=v.tenant AND s.id=v.source_id
        JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id WHERE v.tenant=? AND v.id=?''',
                     (str(scope), entry.get('version_id', ''))).fetchone()
    if not row:
        return False
    return (row['source_id']==entry.get('source_id') and row['id']==entry.get('document_id') and row['label']==entry.get('version')
            and reviewer_valid(db,scope,row['reviewer'],[{'source_id':row['source_id']}])
            and not row['deleted'] and row['current_version'] == row['id'] and row['state'] == 'approved'
            and row['valid_until'] >= date.today().isoformat() and row['content_hash'] == entry.get('content_hash')
            and digest(row['content']) == row['content_hash'] and entry.get('quote', '') in row['content']
            and bool(entry.get('quote')))


def valid(db, scope, evidence):
    require(db, scope)
    return bool(evidence) and all(global_valid(db, scope, entry) and can_read(db, scope, entry.get('source_id', '')) for entry in evidence)


def visible_answer(db, scope, answer):
    if not isinstance(scope, Principal):
        return answer
    evidence = answer['evidence']
    accessible = bool(evidence) and all(entry.get('version_id') and can_read(db, scope, entry.get('source_id', '')) for entry in evidence)
    if not accessible:
        answer = {**answer, 'text': '[Evidence access unavailable. Redraft using authorized sources.]', 'draft': '[Evidence access unavailable. Redraft using authorized sources.]',
                  'final': None, 'evidence': [], 'approval': None, 'access_blocked': True, 'status': 'needs_evidence'}
    elif not valid(db, scope, evidence) or (answer.get('status')=='approved' and not reviewer_valid(db,scope,answer.get('reviewer'),evidence)):
        answer = {**answer, 'approval': None, 'status': 'needs_evidence', 'stale_evidence': True}
    return answer


class Evidence:
    def __init__(self, store):
        self.store = store
    def _source(self, db, scope, identifier, write=False):
        require(db, scope, 'author' if write else 'read')
        row = db.execute('SELECT * FROM evidence_sources WHERE tenant=? AND id=?', (str(scope), identifier)).fetchone()
        if not row or row['deleted'] or not can_read(db, scope, identifier, write):
            raise Problem('not_found', 'Evidence source not found.', 404)
        return row
    def _body(self, title, content, label, valid_until, metadata):
        try:
            date.fromisoformat(valid_until)
        except ValueError as exc:
            raise Problem('invalid_expiry', 'Use an ISO expiry date.') from exc
        if not title.strip() or len(title) > 300 or not content.strip() or len(content) > 100000 or not label.strip() or len(label) > 100:
            raise Problem('invalid_evidence', 'Provide title, text (at most 100000 characters), and version label.')
        for text in [title,content,label,*metadata.values()]:
            if not isinstance(text,str) or any(not (char in '\t\n\r' or 0x20<=ord(char)<=0xD7FF or 0xE000<=ord(char)<=0xFFFD or 0x10000<=ord(char)<=0x10FFFF) for char in text):
                raise Problem('invalid_evidence','Use valid Unicode text without XML control characters.')
        if set(metadata) - {'product','edition','deployment','provenance','filename'} or any(not isinstance(value,str) or len(value)>300 for value in metadata.values()):
            raise Problem('invalid_metadata', 'Use bounded product, edition, deployment and provenance text.')
    def _version(self, db, scope, source, title, content, label, valid_until, metadata):
        self._body(title, content, label, valid_until, metadata)
        identifier = str(uuid.uuid4())
        if db.execute('SELECT 1 FROM evidence_versions WHERE tenant=? AND source_id=? AND label=?', (str(scope),source,label)).fetchone():
            raise Problem('version_conflict', 'Use a new immutable version label.', 409)
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?)', (identifier, str(scope), title, content, label, valid_until))
        db.execute('INSERT INTO evidence_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier,str(scope),source,label,content,digest(content),valid_until,json.dumps(metadata),identifier,actor(scope),timestamp()))
        db.execute('INSERT INTO evidence_states VALUES (?,?,?,?,?)', (str(scope),identifier,'pending',None,None))
        db.execute('UPDATE evidence_sources SET current_version=? WHERE tenant=? AND id=?', (identifier,str(scope),source))
        audit(db,scope,'evidence.version_created',identifier,{'source_id':source,'sha256':digest(content)})
        return identifier
    @traced('ingestion')
    def create(self, scope, title, content, version, valid_until, metadata=None):
        if not isinstance(scope, Principal):
            raise Problem('verified_identity_required','Evidence lifecycle requires OIDC mode.',403)
        identifier = str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'author')
            db.execute('INSERT INTO evidence_sources VALUES (?,?,?,?,?,?)', (identifier,str(scope),title,None,0,timestamp()))
            db.execute('INSERT INTO document_acl VALUES (?,?,?,?,?)', (str(scope),identifier,scope.issuer,scope.subject,1))
            self._version(db,scope,identifier,title,content,version,valid_until,metadata or {})
        return self.get(scope,identifier)
    def version(self, scope, identifier, expected_version, content, version, valid_until, metadata=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); source=self._source(db,scope,identifier,True)
            if source['current_version'] != expected_version:
                raise Problem('version_conflict','Reload the current source version.',409)
            old=source['current_version']
            self._version(db,scope,identifier,source['title'],content,version,valid_until,metadata or {})
            db.execute("UPDATE evidence_states SET state='superseded' WHERE tenant=? AND version_id=?", (str(scope),old))
            invalidate_versions(db,scope,[old],'source_updated')
        return self.get(scope,identifier)
    def get(self, scope, identifier):
        with self.store.connect() as db:
            source=self._source(db,scope,identifier)
            rows=db.execute('''SELECT v.id,v.label,v.content,v.content_hash,v.valid_until,v.metadata,v.created_at,st.state,st.reviewer
                FROM evidence_versions v JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id
                WHERE v.tenant=? AND v.source_id=? ORDER BY v.rowid DESC LIMIT 100''', (str(scope),identifier)).fetchall()
            return {**dict(source),'can_write':bool(require(db,scope) & {'author','admin'}) and can_read(db,scope,identifier,True),'versions':[{**dict(row),'metadata':json.loads(row['metadata']), 'state':'expired' if row['valid_until']<date.today().isoformat() else row['state']} for row in rows]}
    def list(self, scope, offset=0, limit=20):
        if offset<0 or not 1<=limit<=100:
            raise Problem('invalid_pagination','Use nonnegative offset and limit 1-100.')
        with self.store.connect() as db:
            current=require(db,scope)
            if not isinstance(scope, Principal):
                raise Problem('verified_identity_required','Evidence lifecycle requires OIDC mode.',403)
            clause='s.tenant=? AND s.deleted=0'
            params=[str(scope)]
            if 'admin' not in current:
                clause+=' AND EXISTS (SELECT 1 FROM document_acl a WHERE a.tenant=s.tenant AND a.source_id=s.id AND a.issuer=? AND a.subject=?)'
                params += [scope.issuer,scope.subject]
            total=db.execute(f'SELECT COUNT(*) FROM evidence_sources s WHERE {clause}',params).fetchone()[0]
            rows=db.execute(f'''SELECT s.id,s.title,s.current_version,v.label,v.valid_until,st.state FROM evidence_sources s
                JOIN evidence_versions v ON v.tenant=s.tenant AND v.id=s.current_version
                JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id WHERE {clause} ORDER BY s.rowid DESC LIMIT ? OFFSET ?''',params+[limit,offset]).fetchall()
            return {'items':[{**dict(row),'state':'expired' if row['valid_until']<date.today().isoformat() else row['state']} for row in rows],
                    'total':total,'offset':offset,'limit':limit,'next_offset':offset+len(rows) if offset+len(rows)<total else None}
    def approve(self, scope, identifier, version_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'reviewer'); source=self._source(db,scope,identifier)
            row=db.execute('SELECT * FROM evidence_versions WHERE tenant=? AND id=? AND source_id=?',(str(scope),version_id,identifier)).fetchone()
            if not row or source['current_version']!=version_id or row['valid_until']<date.today().isoformat():
                raise Problem('stale_evidence','Approve a current unexpired version.',409)
            state=db.execute('SELECT state FROM evidence_states WHERE tenant=? AND version_id=?',(str(scope),version_id)).fetchone()[0]
            if state!='pending':
                raise Problem('invalid_evidence_state','Only pending evidence can be approved.',409)
            db.execute("UPDATE evidence_states SET state='approved',reviewer=?,reviewed_at=? WHERE tenant=? AND version_id=?",(actor(scope),timestamp(),str(scope),version_id))
            audit(db,scope,'evidence.approved',version_id)
        return self.get(scope,identifier)
    def revoke(self, scope, identifier, delete=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'admin'); source=self._source(db,scope,identifier)
            ids=[row[0] for row in db.execute('SELECT id FROM evidence_versions WHERE tenant=? AND source_id=?',(str(scope),identifier))]
            db.execute('UPDATE evidence_states SET state=? WHERE tenant=? AND version_id IN (SELECT id FROM evidence_versions WHERE source_id=? AND tenant=?)',('deleted' if delete else 'revoked',str(scope),identifier,str(scope)))
            if delete:
                db.execute('UPDATE evidence_sources SET deleted=1 WHERE tenant=? AND id=?',(str(scope),identifier))
            invalidate_versions(db,scope,ids,'source_deleted' if delete else 'source_revoked')
            audit(db,scope,'evidence.deleted' if delete else 'evidence.revoked',identifier)
        return {'id':identifier,'state':'deleted' if delete else 'revoked'}
    def acl(self, scope, identifier, subject, can_write=False, remove=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'admin'); self._source(db,scope,identifier)
            if remove:
                db.execute('DELETE FROM document_acl WHERE tenant=? AND source_id=? AND issuer=? AND subject=?',(str(scope),identifier,scope.issuer,subject))
                ids=[row[0] for row in db.execute('SELECT id FROM evidence_versions WHERE tenant=? AND source_id=?',(str(scope),identifier))]
                invalidate_versions(db,scope,ids,'permission_revoked')
                db.execute("UPDATE evidence_states SET state='pending' WHERE tenant=? AND version_id IN (SELECT id FROM evidence_versions WHERE tenant=? AND source_id=?) AND reviewer=?",(str(scope),str(scope),identifier,f'{scope.issuer}|{subject}'))
            else:
                if not db.execute('SELECT 1 FROM memberships WHERE tenant=? AND issuer=? AND subject=? AND active=1',(str(scope),scope.issuer,subject)).fetchone():
                    raise Problem('membership_required','Grant only to an active tenant member.',403)
                db.execute('INSERT INTO document_acl VALUES (?,?,?,?,?) ON CONFLICT(tenant,source_id,issuer,subject) DO UPDATE SET can_write=excluded.can_write',(str(scope),identifier,scope.issuer,subject,int(can_write)))
            audit(db,scope,'acl.revoked' if remove else 'acl.granted',identifier,{'subject':subject,'write':can_write})
        return {'id':identifier,'subject':subject,'access':'revoked' if remove else 'granted'}
    def membership(self, scope, subject, roles, active=True):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'admin')
            if subject==scope.subject and (not active or 'admin' not in roles):
                admins=[row for row in db.execute('SELECT subject,roles FROM memberships WHERE tenant=? AND issuer=? AND active=1',(str(scope),scope.issuer)) if 'admin' in json.loads(row['roles'])]
                if len(admins)<=1:
                    raise Problem('last_admin','Keep at least one active tenant admin.',409)
            db.execute('INSERT INTO memberships VALUES (?,?,?,?,?) ON CONFLICT(tenant,issuer,subject) DO UPDATE SET roles=excluded.roles,active=excluded.active',(str(scope),scope.issuer,subject,json.dumps(sorted(set(roles))),int(active)))
            if not active or 'reviewer' not in roles and 'admin' not in roles:
                identity=f'{scope.issuer}|{subject}'
                version_ids=[row[0] for row in db.execute("SELECT version_id FROM evidence_states WHERE tenant=? AND reviewer=? AND state='approved'",(str(scope),identity))]
                db.execute("UPDATE evidence_states SET state='pending' WHERE tenant=? AND reviewer=? AND state='approved'",(str(scope),identity))
                invalidate_versions(db,scope,version_ids,'reviewer_permission_revoked')
                ids=[row[0] for row in db.execute('SELECT r.answer_id FROM answer_revisions r JOIN questionnaire_approvals a ON a.tenant=r.tenant AND a.revision_id=r.id WHERE r.tenant=? AND a.reviewer=?',(str(scope),identity))]
                ids += [row[0] for row in db.execute('SELECT id FROM answers WHERE tenant=? AND reviewer=?',(str(scope),identity))]
                invalidate_answers(db,scope,ids,'reviewer_permission_revoked')
            audit(db,scope,'membership.changed',subject,{'roles':roles,'active':active})
        return {'subject':subject,'roles':roles,'active':active}
    def expire(self, scope):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,scope,'admin')
            ids=[row[0] for row in db.execute("SELECT v.id FROM evidence_versions v JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id WHERE v.tenant=? AND v.valid_until<? AND st.state='approved'",(str(scope),date.today().isoformat()))]
            for identifier in ids:
                db.execute("UPDATE evidence_states SET state='expired' WHERE tenant=? AND version_id=?",(str(scope),identifier))
            invalidate_versions(db,scope,ids,'source_expired')
            return {'expired':len(ids)}
