import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.access import Principal, verify
from app.core import Store
from app.evidence import Evidence
from app.main import app, store as api_store
from app.questionnaires import Questionnaires
from app.workbooks import Mapping, Problem
from scripts.access_admin import copy_database
from scripts.sample_workbooks import template

@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_AUTH_MODE','oidc')
    monkeypatch.setenv('EVIDENCEDESK_OIDC_ISSUER','https://issuer.example.invalid')
    monkeypatch.setenv('EVIDENCEDESK_OIDC_AUDIENCE','evidencedesk-api')
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())); public.update(kid='test',alg='RS256',use='sig')
    path=tmp_path/'jwks.json'; path.write_text(json.dumps({'keys':[public]})); monkeypatch.setenv('EVIDENCEDESK_OIDC_JWKS_FILE',str(path))
    store=Store(tmp_path/'db.sqlite'); monkeypatch.setenv('EVIDENCEDESK_DB',store.path); api_store.cache_clear()
    with store.connect() as db:
        for subject,roles in [('admin',['admin']),('author',['author']),('reviewer',['reviewer']),('outsider',['author'])]:
            db.execute('INSERT INTO memberships VALUES (?,?,?,?,1)',('a','https://issuer.example.invalid',subject,json.dumps(roles)))
        db.execute('INSERT INTO memberships VALUES (?,?,?,?,1)',('b','https://issuer.example.invalid','other','["admin"]'))
    def token(subject='admin',**changes):
        typ=changes.pop('_typ','at+jwt'); remove=changes.pop('_remove',[]); extra_headers=changes.pop('_headers',{})
        claims={'iss':'https://issuer.example.invalid','aud':'evidencedesk-api','sub':subject,'iat':int(time.time()),'exp':int(time.time())+3600}; claims.update(changes)
        for field in remove: claims.pop(field,None)
        return jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test','typ':typ,**extra_headers})
    def scope(subject='admin',tenant='a'):
        return verify(token(subject),tenant)
    yield store,Evidence(store),Questionnaires(store),token,scope
    api_store.cache_clear()

def approved(environment):
    store,evidence,questionnaires,token,scope=environment
    source=evidence.create(scope('author'),'Policy','Customer data is encrypted at rest using AES-256.','1','2099-01-01',{'product':'Synthetic'})
    evidence.acl(scope(),source['id'],'reviewer')
    evidence.approve(scope('reviewer'),source['id'],source['current_version'])
    data,mapping=template(); questionnaire=questionnaires.create(scope('author'),data,'security.xlsx',Mapping.model_validate(mapping),'key')
    questionnaires.draft(scope('author'),questionnaire['id'])
    item=questionnaires.items(scope('reviewer'),questionnaire['id'])['items'][0]
    questionnaires.approve(scope('reviewer'),item['id'],1,'spoofed name')
    return source,questionnaire,item

@pytest.mark.parametrize('claim,value',[('iss','https://wrong.invalid'),('aud','wrong-api'),('exp',0),('iat',9999999999),('sub','')])
def test_oidc_rejects_wrong_claims(environment,claim,value):
    _,_,_,token,_=environment
    with pytest.raises(HTTPException) as exc:
        verify(token(**{claim:value}),'a')
    assert exc.value.status_code==401

def test_signature_algorithm_id_token_and_unsigned_rejected(environment):
    _,_,_,token,_=environment
    for bad in [token()[:-8]+'abcdefgh',jwt.encode({'iss':'https://issuer.example.invalid','sub':'admin','aud':'evidencedesk-api','exp':time.time()+50,'iat':time.time()},'secret'*20,algorithm='HS256')]:
        with pytest.raises(HTTPException): verify(bad,'a')

def test_pending_acl_role_and_verified_reviewer(environment):
    store,evidence,questionnaires,token,scope=environment
    source=evidence.create(scope('author'),'Private policy','Customer data is encrypted at rest using AES-256.','1','2099-01-01')
    assert store.draft(scope('author'),'Is customer data encrypted at rest?')['evidence']==[]
    with pytest.raises(Problem): evidence.get(scope('outsider'),source['id'])
    assert evidence.list(scope('outsider'))['total']==0
    with pytest.raises(Problem): evidence.approve(scope('author'),source['id'],source['current_version'])
    evidence.acl(scope(),source['id'],'reviewer'); evidence.approve(scope('reviewer'),source['id'],source['current_version'])
    assert store.draft(scope('outsider'),'Is customer data encrypted at rest?')['evidence']==[]
    answer=store.draft(scope('author'),'Is customer data encrypted at rest?')
    assert answer['evidence'][0]['content_hash'] and answer['evidence'][0]['version_id']==source['current_version']
    with pytest.raises(Problem): store.approve(scope('author'),answer['id'],'fake','Yes')
    data,mapping=template(); q=questionnaires.create(scope('author'),data,'security.xlsx',Mapping.model_validate(mapping),'q')
    questionnaires.draft(scope('author'),q['id']); item=questionnaires.items(scope('reviewer'),q['id'])['items'][0]
    result=questionnaires.approve(scope('reviewer'),item['id'],1,'fake name')
    assert result['answer']['approval']['identity_verified']==1
    assert result['answer']['approval']['reviewer'].endswith('|reviewer')
    with pytest.raises(Problem): questionnaires.export(scope('author'),q['id'])
    with pytest.raises(Problem): questionnaires.get(scope('other','b'),q['id'])

@pytest.mark.parametrize('action',['update','revoke','delete','acl','membership'])
def test_invalidation_and_redacted_reads(environment,action):
    store,evidence,q,token,scope=environment
    source,questionnaire,item=approved(environment)
    if action=='update': evidence.version(scope('author'),source['id'],source['current_version'],'Customer data is encrypted at rest using AES-128.','2','2099-01-01')
    elif action=='revoke': evidence.revoke(scope(),source['id'])
    elif action=='delete': evidence.revoke(scope(),source['id'],True)
    elif action=='acl': evidence.acl(scope(),source['id'],'reviewer',remove=True)
    else: evidence.membership(scope(),'reviewer',['reviewer'],False)
    if action=='membership':
        with pytest.raises(Problem): q.items(scope('reviewer'),questionnaire['id'])
    else:
        current=q.item(scope('reviewer'),item['id'])
        assert current['answer']['approval'] is None and current['status']=='needs_evidence'
        if action=='acl':
            assert not current['answer']['evidence'] and 'AES-256' not in current['answer']['text']
    bundle=q.export(scope(),questionnaire['id'])
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert json.loads(archive.read('manifest.json'))['selected_revisions']==[]
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM approval_invalidations').fetchone()[0]>0
        assert db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]>0

def test_redraft_replaces_snapshot_and_needs_approval(environment):
    store,evidence,q,_,scope=environment
    source,questionnaire,item=approved(environment)
    new=evidence.version(scope('author'),source['id'],source['current_version'],'Customer data is encrypted at rest using AES-128.','2','2099-01-01')
    evidence.approve(scope('reviewer'),source['id'],new['current_version'])
    result=q.redraft(scope('author'),item['id'],1)
    assert result['current_revision']==2 and result['answer']['approval'] is None
    assert result['answer']['evidence'][0]['version_id']==new['current_version']
    assert 'AES-128' in result['answer']['text']
    q.approve(scope('reviewer'),item['id'],2,'fake')
    with pytest.raises(sqlite3.IntegrityError),store.connect() as db:
        db.execute('UPDATE evidence_versions SET content=? WHERE id=?',('tampered',new['current_version']))
    with pytest.raises(sqlite3.IntegrityError),store.connect() as db:
        db.execute('DELETE FROM audit_events')

def test_signed_http_membership_and_bootstrap_disable(environment,monkeypatch):
    store,evidence,q,token,scope=environment
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND','1'); monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY','1')
    with TestClient(app,client=('127.0.0.1',1)) as client:
        assert client.get('/session',headers={'X-API-Key':'anything'}).status_code==401
        headers={'Authorization':'Bearer '+token('author'),'X-Tenant-ID':'a'}
        assert client.get('/session',headers=headers).json()['subject']=='author'
        assert client.get('/session',headers={**headers,'X-Tenant-ID':'b'}).status_code==403
        assert client.post('/local/session-key',headers={'X-Local-Session':'true'}).status_code==404
        assert client.post('/local/api-key',headers={'X-Local-Key-Recovery':'true'}).status_code==404
        assert client.post('/documents',headers=headers,json={'title':'Bad bypass','content':'text','version':'1','valid_until':'2099-01-01'}).status_code==403
        upload=client.post('/evidence/upload',headers=headers,files={'file':('policy.txt',b'Customer data is encrypted at rest using AES-256.')},data={'metadata':json.dumps({'title':'Uploaded policy','version':'1','valid_until':'2099-01-01'})})
        assert upload.status_code==201,upload.text
        source=upload.json(); assert source['versions'][0]['state']=='pending'
        assert client.post('/evidence/'+source['id']+'/approve',headers=headers,json={'version_id':source['current_version']}).status_code==403

def test_migration_backup_restore_and_revocation_preserved(environment,tmp_path):
    store,evidence,q,token,scope=environment
    source,questionnaire,item=approved(environment)
    evidence.membership(scope(),'reviewer',['reviewer'],False)
    path=tmp_path/'backup.sqlite'; copy_database(store.path,path)
    restored=Store(path)
    assert Questionnaires(restored).get(scope(),questionnaire['id'])['total']==5
    with pytest.raises(Problem): Questionnaires(restored).get(scope('reviewer'),questionnaire['id'])
    with restored.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]>0
    with pytest.raises(ValueError): copy_database(store.path,path)


def test_id_token_missing_claims_and_plain_service_scope_rejected(environment):
    store,_,_,token,_=environment
    for bad in [token(_typ='JWT'),token(_remove=['exp']),token(_remove=['iat']),token(nbf=int(time.time())+3600)]:
        with pytest.raises(HTTPException): verify(bad,'a')
    with pytest.raises(Problem): store.draft('a','Question')


def test_expiry_invalidates_on_read_and_prevents_export(environment,monkeypatch):
    from datetime import date
    store,evidence,q,_,scope=environment
    source,questionnaire,item=approved(environment)
    class Future(date):
        @classmethod
        def today(cls): return cls(2100,1,1)
    monkeypatch.setattr('app.evidence.date',Future)
    current=q.item(scope('reviewer'),item['id'])
    assert current['answer']['approval'] is None and current['status']=='needs_evidence'
    with zipfile.ZipFile(io.BytesIO(q.export(scope(),questionnaire['id']))) as archive:
        assert json.loads(archive.read('manifest.json'))['selected_revisions']==[]


def test_legacy_migration_preserves_bytes_but_requires_enterprise_review(tmp_path,monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_AUTH_MODE','local')
    store=Store(tmp_path/'old.db')
    identifier=store.add_document('a','Old source','Customer data is encrypted at rest using AES-256.','1','2099-01-01')
    answer=store.draft('a','Is customer data encrypted at rest?')
    before=store.get('a',answer['id'])
    migrated=Store(store.path)
    with migrated.connect() as db:
        version=db.execute('SELECT * FROM evidence_versions WHERE legacy_document_id=?',(identifier,)).fetchone()
        assert version['content']=='Customer data is encrypted at rest using AES-256.'
        assert db.execute('SELECT state FROM evidence_states WHERE version_id=?',(version['id'],)).fetchone()[0]=='pending'
    assert migrated.get('a',answer['id'])['draft']==before['draft']


def test_token_roles_and_key_urls_do_not_override_server_policy(environment):
    store,evidence,_,token,_=environment
    outsider=verify(token('outsider',roles=['admin'],tenant='a'),'a')
    with pytest.raises(Problem): evidence.membership(outsider,'author',['admin'])
    with pytest.raises(HTTPException): verify(token(_headers={'jku':'https://evil.invalid/keys'}),'a')


def test_legacy_approval_reviewer_revocation_and_snapshot_integrity(environment):
    store,evidence,_,_,scope=environment
    source,_,_=approved(environment)
    answer=store.draft(scope('author'),'Is customer data encrypted at rest?')
    store.approve(scope('reviewer'),answer['id'],'spoof','Approved current evidence.')
    entry=dict(answer['evidence'][0]);entry['source_id']='another-source'
    from app.evidence import valid
    with store.connect() as db:
        assert not valid(db,scope(),[entry])
    evidence.membership(scope(),'reviewer',['author'],True)
    assert 'Approved current evidence.' not in store.export(scope())


def test_deployment_cannot_use_local_key_recovery(monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_DEPLOYMENT','production')
    monkeypatch.setenv('EVIDENCEDESK_AUTH_MODE','local')
    monkeypatch.setenv('EVIDENCEDESK_API_KEY','synthetic-secret')
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND','1')
    with TestClient(app,client=('127.0.0.1',1)) as client:
        response=client.post('/local/session-key',headers={'X-Local-Session':'true'})
        assert response.status_code==503 and 'api_key' not in response.json()
        assert client.get('/session',headers={'X-API-Key':'synthetic-secret'}).status_code==503


def test_edit_cannot_inherit_unauthorized_source_snapshot(environment):
    store,evidence,q,_,scope=environment
    source,questionnaire,item=approved(environment)
    evidence.acl(scope(),source['id'],'author',remove=True)
    with pytest.raises(Problem) as exc:
        q.edit(scope('author'),item['id'],'User-supplied text',1)
    assert exc.value.code=='source_access_denied'
    replacement=q.redraft(scope('author'),item['id'],1)
    assert replacement['current_revision']==2 and replacement['answer']['evidence']==[]


def test_text_upload_controls_and_sizes_are_rejected_without_persisting(environment):
    store,evidence,_,token,scope=environment
    with pytest.raises(Problem): evidence.create(scope(),'Policy','Customer data encrypted at rest.\x01','1','2099-01-01')
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+token(),'X-Tenant-ID':'a'}
        metadata=json.dumps({'title':'Policy','version':'1','valid_until':'2099-01-01'})
        for filename,content,status in [('bad.bin',b'data',422),('bad.txt',b'\xff',422),('large.txt',b'a'*100001,413)]:
            response=client.post('/evidence/upload',headers=headers,files={'file':(filename,content)},data={'metadata':metadata})
            assert response.status_code==status
        assert client.get('/evidence',headers=headers).json()['total']==0
