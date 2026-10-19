"""Offline public-key fixtures. Private keys/tokens exist only in a harness-owned temp directory."""
import json
import time
from pathlib import Path
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from app.core import Store

ISSUER='https://issuer.example.invalid'
AUDIENCE='evidencedesk-api'

def initialize(root):
    root=Path(root)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update({'kid':'fixture','use':'sig','alg':'RS256'})
    (root/'jwks.json').write_text(json.dumps({'keys':[public]}))
    tokens={subject:jwt.encode({'iss':ISSUER,'aud':AUDIENCE,'sub':subject,'iat':int(time.time()),'exp':int(time.time())+3600},key,algorithm='RS256',headers={'kid':'fixture','typ':'at+jwt'}) for subject in ['admin','author','reviewer','outsider','other']}
    (root/'oidc-fixture.json').write_text(json.dumps({'tokens':tokens,'issuer':ISSUER,'audience':AUDIENCE}))
    seed(root)

def seed(root):
    store=Store(Path(root)/'browser.db')
    with store.connect() as db:
        for subject,roles in [('admin',['admin']),('author',['author']),('reviewer',['reviewer']),('outsider',['author'])]:
            db.execute('INSERT OR REPLACE INTO memberships VALUES (?,?,?,?,1)',('enterprise',ISSUER,subject,json.dumps(roles)))
        db.execute('INSERT OR REPLACE INTO memberships VALUES (?,?,?,?,1)',('other-tenant',ISSUER,'other','["admin"]'))
