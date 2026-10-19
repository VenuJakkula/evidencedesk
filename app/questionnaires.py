"""Persistent workbook workflow sharing the baseline answers and evidence service."""
import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone, date

from .access import Principal, actor, require, can_read
from .evidence import audit, record_dependencies, valid, visible_answer, synchronize_expiry, reviewer_valid
from .workbooks import Problem, inspect, workbook, safe_filename


def opaque():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(data):
    return hashlib.sha256(data).hexdigest()


class Questionnaires:
    def __init__(self, store):
        self.store = store

    def _questionnaire(self, db, tenant, identifier):
        require(db, tenant)
        synchronize_expiry(db, tenant)
        row = db.execute('SELECT * FROM questionnaires WHERE tenant=? AND id=?', (tenant, identifier)).fetchone()
        if row is None:
            raise Problem('not_found', 'Questionnaire not found.', 404)
        return row

    def _item(self, db, tenant, identifier):
        require(db, tenant)
        synchronize_expiry(db, tenant)
        row = db.execute('SELECT * FROM questionnaire_items WHERE tenant=? AND id=?', (tenant, identifier)).fetchone()
        if row is None:
            raise Problem('not_found', 'Questionnaire item not found.', 404)
        return row

    def create(self, tenant, data, filename, mapping, key):
        if not key or len(key) > 200:
            raise Problem('invalid_idempotency_key', 'Provide an Idempotency-Key of 1 to 200 characters.')
        preview = inspect(data, filename, mapping)
        canonical = json.dumps(mapping.model_dump(), sort_keys=True, separators=(',', ':'))
        payload = checksum(data + canonical.encode() + safe_filename(filename).encode())
        identifier, asset = opaque(), opaque()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db, tenant, 'author')
            existing = db.execute('SELECT * FROM questionnaires WHERE tenant=? AND idempotency_key=?', (tenant, key)).fetchone()
            if existing:
                if existing['payload_hash'] != payload:
                    raise Problem('idempotency_conflict', 'This key was used for a different workbook or mapping.', 409)
                identifier = existing['id']
            else:
                db.execute('INSERT INTO workbook_assets VALUES (?,?,?,?,?,?,?,?)',
                           (asset, tenant, safe_filename(filename), opaque(), checksum(data), len(data), data, now()))
                db.execute('INSERT INTO questionnaires VALUES (?,?,?,?,?,?,?,?)',
                           (identifier, tenant, asset, canonical, 'imported', now(), key, payload))
                for row in preview['rows']:
                    db.execute('INSERT INTO questionnaire_items (id,tenant,questionnaire_id,provenance,question) VALUES (?,?,?,?,?)',
                               (opaque(), tenant, identifier, json.dumps(row), row['question']))
        return self.get(tenant, identifier)

    def list(self, tenant, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise Problem('invalid_pagination', 'offset must be nonnegative and limit must be 1 to 100.')
        with self.store.connect() as db:
            require(db, tenant)
            synchronize_expiry(db, tenant)
            total = db.execute('SELECT COUNT(*) FROM questionnaires WHERE tenant=?', (tenant,)).fetchone()[0]
            rows = db.execute("""SELECT q.id, a.filename, q.status, q.created_at,
                (SELECT COUNT(*) FROM questionnaire_items i WHERE i.tenant=q.tenant AND i.questionnaire_id=q.id) AS total
                FROM questionnaires q JOIN workbook_assets a ON a.tenant=q.tenant AND a.id=q.asset_id
                WHERE q.tenant=? ORDER BY q.created_at DESC, q.id DESC LIMIT ? OFFSET ?""", (tenant, limit, offset)).fetchall()
            return {'items': [dict(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit,
                    'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def get(self, tenant, identifier):
        with self.store.connect() as db:
            row = dict(self._questionnaire(db, tenant, identifier))
            counts = db.execute('SELECT status,COUNT(*) AS count FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? GROUP BY status', (tenant, identifier)).fetchall()
        row.pop('payload_hash')
        row.pop('idempotency_key')
        row['mapping'] = json.loads(row['mapping'])
        row['counts'] = {r['status']: r['count'] for r in counts}
        row['total'] = sum(row['counts'].values())
        return row

    def _view(self, db, row):
        item = dict(row)
        item['provenance'] = json.loads(item['provenance'])
        revision = db.execute('SELECT * FROM answer_revisions WHERE tenant=? AND item_id=? AND revision=?',
                              (row['tenant'], row['id'], row['current_revision'])).fetchone()
        item['answer'] = dict(revision) if revision else None
        if revision:
            item['answer']['evidence'] = json.loads(revision['evidence'])
            approval = db.execute('SELECT * FROM questionnaire_approvals WHERE tenant=? AND revision_id=?', (row['tenant'], revision['id'])).fetchone()
            invalidation = db.execute('SELECT reason FROM approval_invalidations WHERE tenant=? AND revision_id=?', (str(row['tenant']),revision['id'])).fetchone()
            item['answer']['approval'] = dict(approval) if approval and not invalidation else None
            item['answer']['invalidation_reason'] = invalidation['reason'] if invalidation else None
        return item

    def _scoped_view(self, db, tenant, row):
        item = self._view(db, row)
        if isinstance(tenant, Principal) and item['answer']:
            item['answer'] = visible_answer(db, tenant, item['answer'])
            approval=item['answer'].get('approval')
            if approval and (not approval['identity_verified'] or not reviewer_valid(db,tenant,approval['reviewer'],item['answer']['evidence'])):
                item['answer']['approval']=None
                item['answer']['invalidation_reason']='reviewer_permission_revoked'
            if item['answer'].get('access_blocked') or item['answer'].get('stale_evidence') or item['answer'].get('invalidation_reason'):
                item['status'] = 'needs_evidence'
                item['answer']['approval'] = None
        return item

    def items(self, tenant, identifier, offset=0, limit=100):
        if not 0 <= offset or not 1 <= limit <= 200:
            raise Problem('invalid_pagination', 'offset must be nonnegative and limit must be 1 to 200.')
        with self.store.connect() as db:
            self._questionnaire(db, tenant, identifier)
            rows = db.execute('SELECT * FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? ORDER BY rowid LIMIT ? OFFSET ?', (tenant, identifier, limit, offset)).fetchall()
            total = db.execute('SELECT COUNT(*) FROM questionnaire_items WHERE tenant=? AND questionnaire_id=?', (tenant, identifier)).fetchone()[0]
            return {'items': [self._scoped_view(db, tenant, r) for r in rows], 'total': total, 'offset': offset, 'limit': limit,
                    'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def item(self, tenant, identifier):
        with self.store.connect() as db:
            return self._scoped_view(db, tenant, self._item(db, tenant, identifier))

    def _revision(self, db, tenant, item, text, evidence, creator, answer_id, model_version='extractive-baseline-v1', prompt_version='none'):
        record_dependencies(db, tenant, answer_id, evidence)
        revision = item['current_revision'] + 1
        identifier = opaque()
        db.execute('INSERT INTO answer_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, tenant, item['id'], revision, answer_id, text, json.dumps(evidence), creator, now(), model_version, prompt_version))
        db.execute('UPDATE questionnaire_items SET current_revision=?, status=? WHERE tenant=? AND id=?',
                   (revision, 'needs_review' if evidence else 'needs_evidence', tenant, item['id']))

    def draft(self, tenant, identifier, limit=100):
        if not 1 <= limit <= 200:
            raise Problem('invalid_batch', 'Draft batch limit must be 1 to 200.')
        with self.store.connect() as db:
            require(db, tenant, 'author')
            self._questionnaire(db, tenant, identifier)
            selected = db.execute('SELECT * FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? AND current_revision=0 ORDER BY rowid LIMIT ?', (tenant, identifier, limit)).fetchall()
        generated = 0
        for row in selected:
            # Baseline retrieval retains its own answer record; revision linking and CAS
            # happen in a writer transaction. A racing batch can leave an unlinked baseline
            # draft, but can never create a second current questionnaire revision.
            answer = self.store.draft(tenant, row['question'])
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                item = self._item(db, tenant, row['id'])
                if item['current_revision'] == 0:
                    require(db, tenant, 'author')
                    if isinstance(tenant, Principal) and answer['evidence'] and not valid(db,tenant,answer['evidence']):
                        raise Problem('evidence_changed','Evidence access changed; retry drafting.',409)
                    self._revision(db, tenant, item, answer['draft'], answer['evidence'], actor(tenant), answer['id'])
                    db.execute("UPDATE questionnaires SET status='in_review' WHERE tenant=? AND id=?", (tenant, identifier))
                    generated += 1
        with self.store.connect() as db:
            remaining = db.execute('SELECT COUNT(*) FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? AND current_revision=0', (tenant, identifier)).fetchone()[0]
        return {'drafted': generated, 'remaining': remaining, 'status': 'completed' if remaining == 0 else 'more_items'}

    def edit(self, tenant, identifier, text, expected_revision, owner=None):
        if not text.strip() or len(text) > 10000 or any(not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in text):
            raise Problem('invalid_answer', 'Answer must contain 1 to 10000 characters without XML control characters.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db, tenant, 'author')
            item = self._item(db, tenant, identifier)
            if item['current_revision'] != expected_revision:
                raise Problem('revision_conflict', 'Answer changed; reload the current revision.', 409)
            previous = db.execute('SELECT * FROM answer_revisions WHERE tenant=? AND item_id=? AND revision=?', (tenant, identifier, expected_revision)).fetchone()
            if previous is None:
                raise Problem('draft_required', 'Draft this item before editing.', 409)
            evidence = json.loads(previous['evidence'])
            if isinstance(tenant,Principal) and evidence and not all(entry.get('source_id') and can_read(db,tenant,entry['source_id']) for entry in evidence):
                raise Problem('source_access_denied','Redraft using authorized sources before editing this answer.',403)
            answer_id = opaque()
            trace = json.dumps({'provider': 'extractive-baseline', 'workflow': ['human_edit'], 'llm_calls': 0})
            db.execute('INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)',
                       (answer_id, tenant, item['question'], text, json.dumps(evidence), 'needs_review' if evidence else 'needs_evidence', None, None, trace))
            self._revision(db, tenant, item, text, evidence, actor(tenant), answer_id)
            if isinstance(tenant, Principal):
                audit(db,tenant,'answer.edited',identifier)
            db.execute("UPDATE questionnaires SET status='in_review' WHERE tenant=? AND id=?", (tenant, item['questionnaire_id']))
            if owner is not None:
                db.execute('UPDATE questionnaire_items SET owner=? WHERE tenant=? AND id=?', (owner, tenant, identifier))
        return self.item(tenant, identifier)

    def _evidence_valid(self, db, tenant, evidence):
        if isinstance(tenant, Principal):
            return valid(db,tenant,evidence)
        if not evidence:
            return False
        for entry in evidence:
            doc = db.execute('SELECT * FROM documents WHERE tenant=? AND id=?', (tenant, entry['document_id'])).fetchone()
            if not doc or doc['valid_until'] < date.today().isoformat() or doc['version'] != entry['version'] or entry['quote'] not in doc['content']:
                return False
        return True

    def approve(self, tenant, identifier, expected_revision, reviewer='', reason=''):
        if isinstance(tenant, Principal):
            reviewer = actor(tenant)
        if not reviewer.strip():
            raise Problem('invalid_reviewer', 'A local reviewer label is required.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db,tenant,'reviewer')
            item = self._item(db, tenant, identifier)
            if item['current_revision'] != expected_revision:
                raise Problem('revision_conflict', 'Approve only the current revision; reload this item.', 409)
            revision = db.execute('SELECT * FROM answer_revisions WHERE tenant=? AND item_id=? AND revision=?', (tenant, identifier, expected_revision)).fetchone()
            if not revision or not self._evidence_valid(db, tenant, json.loads(revision['evidence'])):
                raise Problem('stale_evidence', 'Current evidence is missing, changed or expired; approval is unavailable.', 409)
            if db.execute('SELECT 1 FROM approval_invalidations WHERE tenant=? AND revision_id=?',(str(tenant),revision['id'])).fetchone():
                raise Problem('refresh_required','Redraft an invalidated revision before approval.',409)
            if db.execute('SELECT 1 FROM questionnaire_approvals WHERE tenant=? AND revision_id=?', (tenant, revision['id'])).fetchone():
                raise Problem('already_approved', 'This revision is already approved.', 409)
            db.execute('INSERT INTO questionnaire_approvals VALUES (?,?,?,?,?,?,?,?)',
                       (opaque(), tenant, revision['id'], reviewer, int(isinstance(tenant,Principal)), 'approved', reason, now()))
            db.execute("UPDATE answers SET status='approved',final=?,reviewer=? WHERE tenant=? AND id=?", (revision['text'], reviewer, tenant, revision['answer_id']))
            db.execute("UPDATE questionnaire_items SET status='approved' WHERE tenant=? AND id=?", (tenant, identifier))
            pending = db.execute("SELECT COUNT(*) FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? AND status!='approved'", (tenant, item['questionnaire_id'])).fetchone()[0]
            db.execute('UPDATE questionnaires SET status=? WHERE tenant=? AND id=?', ('in_review' if pending else 'reviewed', tenant, item['questionnaire_id']))
            if isinstance(tenant,Principal):
                audit(db,tenant,'answer.approved',identifier,{'revision':expected_revision})
        return self.item(tenant, identifier)

    def redraft(self, tenant, identifier, expected_revision):
        with self.store.connect() as db:
            require(db,tenant,'author')
            item=self._item(db,tenant,identifier)
            if item['current_revision']!=expected_revision:
                raise Problem('revision_conflict','Reload the current revision.',409)
            question=item['question']
        answer=self.store.draft(tenant,question)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require(db,tenant,'author')
            item=self._item(db,tenant,identifier)
            if item['current_revision']!=expected_revision:
                raise Problem('revision_conflict','Reload the current revision.',409)
            if isinstance(tenant,Principal) and answer['evidence'] and not valid(db,tenant,answer['evidence']):
                raise Problem('evidence_changed','Evidence access changed.',409)
            self._revision(db,tenant,item,answer['draft'],answer['evidence'],actor(tenant),answer['id'])
            audit(db,tenant,'answer.redrafted',identifier)
        return self.item(tenant,identifier)

    def export_summary(self, tenant, identifier, export_id, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise Problem('invalid_pagination', 'offset must be nonnegative and limit must be 1 to 100.')
        with self.store.connect() as db:
            self._questionnaire(db, tenant, identifier)
            row = db.execute('SELECT manifest FROM questionnaire_exports WHERE tenant=? AND questionnaire_id=? AND id=?',
                             (tenant, identifier, export_id)).fetchone()
            if row is None:
                raise Problem('not_found', 'Export receipt not found.', 404)
            manifest = json.loads(row['manifest'])
        ids = manifest['unresolved_item_ids']
        # Historical exports keep their original manifests; their CSV remains authoritative for details.
        details_available = 'unresolved_items' in manifest
        unresolved = manifest.get('unresolved_items', [{'item_id': item_id, 'reason': 'details_unavailable',
            'sheet': None, 'answer_cell': None, 'question': None, 'owner': None} for item_id in ids])
        page = unresolved[offset:offset + limit]
        selected = len(manifest['selected_revisions'])
        return {'export_id': export_id, 'questionnaire_id': identifier, 'created_at': manifest['created_at'],
                'total': selected + len(ids), 'selected_count': selected, 'unresolved_count': len(ids),
                'items': page, 'offset': offset, 'limit': limit, 'details_available': details_available,
                'next_offset': offset + len(page) if offset + len(page) < len(ids) else None}

    def export(self, tenant, identifier):
        # Preserve the original bytes-only service contract for callers and fixtures.
        return self.export_result(tenant, identifier)[0]

    def export_result(self, tenant, identifier):
        # One writer snapshot prevents an edit/approval from racing the export record.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(db,tenant,'reviewer')
            questionnaire = self._questionnaire(db, tenant, identifier)
            asset = db.execute('SELECT * FROM workbook_assets WHERE tenant=? AND id=?', (tenant, questionnaire['asset_id'])).fetchone()
            original = bytes(asset['original'])
            if checksum(original) != asset['checksum']:
                raise Problem('source_checksum_mismatch', 'Source workbook integrity check failed.', 409)
            wb = workbook(original, asset['filename'])
            unresolved, selected = [], []
            try:
                rows = db.execute('SELECT * FROM questionnaire_items WHERE tenant=? AND questionnaire_id=? ORDER BY rowid', (tenant, identifier)).fetchall()
                for row in rows:
                    item = self._scoped_view(db, tenant, row)
                    revision, provenance = item['answer'], item['provenance']
                    reason = None
                    if not provenance['writable']:
                        reason = 'existing_answer_preserved'
                    elif not revision or not revision['approval']:
                        reason = 'current_revision_not_approved'
                    elif not self._evidence_valid(db, tenant, revision['evidence']):
                        reason = 'stale_evidence'
                    if reason:
                        unresolved.append({'item_id': item['id'], 'sheet': provenance['sheet'], 'answer_cell': provenance['answer_cell'], 'question': item['question'], 'owner': item['owner'], 'reason': reason})
                        continue
                    cell = wb[provenance['sheet']][provenance['answer_cell']]
                    cell.value = revision['text']
                    cell.data_type = 's'  # literal strings even when text begins with = + - @
                    selected.append({'item_id': item['id'], 'revision_id': revision['id'], 'revision': revision['revision'], 'sheet': provenance['sheet'], 'cell': provenance['answer_cell'], 'overwrite_existing': provenance['overwrite_existing']})
                stream = io.BytesIO()
                wb.save(stream)
                output = stream.getvalue()
            finally:
                wb.close()
            export_id = opaque()
            manifest = {'export_id': export_id, 'questionnaire_id': identifier, 'created_at': now(),
                        'source_sha256': asset['checksum'], 'output_sha256': checksum(output),
                        'selected_revisions': selected, 'unresolved_item_ids': [i['item_id'] for i in unresolved],
                        'unresolved_items': unresolved,
                        'reviewer_identity': 'verified OIDC claims' if isinstance(tenant,Principal) else 'caller-supplied local label; unverified', 'mode': 'extractive-baseline'}
            db.execute('INSERT INTO questionnaire_exports VALUES (?,?,?,?,?,?)', (export_id, tenant, identifier, json.dumps(manifest), output, now()))
            db.execute('UPDATE questionnaires SET status=? WHERE tenant=? AND id=?', ('partial_export' if unresolved else 'exported', tenant, identifier))
            if isinstance(tenant,Principal):
                audit(db,tenant,'questionnaire.exported',identifier,{'export_id':export_id,'selected':len(selected)})
        report = io.StringIO()
        fields = ['item_id', 'sheet', 'answer_cell', 'question', 'owner', 'reason']
        writer = csv.DictWriter(report, fieldnames=fields)
        writer.writeheader()
        for item in unresolved:
            writer.writerow({k: "'" + str(v) if str(v or '').lstrip().startswith(('=', '+', '-', '@')) else v for k, v in item.items()})
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('completed.xlsx', output)
            archive.writestr('manifest.json', json.dumps(manifest, indent=2))
            archive.writestr('unresolved-items.csv', report.getvalue())
        return bundle.getvalue(), manifest
