"""Server-derived identities and live database authorization; no token-provided roles."""
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
import jwt
from fastapi import HTTPException
from .workbooks import Problem

class Principal(str):
    def __new__(cls, tenant, issuer, subject):
        obj = str.__new__(cls, tenant)
        obj.issuer, obj.subject = issuer, subject
        return obj
    @property
    def identity(self):
        return f'{self.issuer}|{self.subject}'


def mode():
    value = os.getenv('EVIDENCEDESK_AUTH_MODE', 'local')
    if os.getenv('EVIDENCEDESK_DEPLOYMENT','local') != 'local' and value != 'oidc':
        raise HTTPException(503, 'Deployed instances require OIDC authentication')
    if value not in {'local', 'oidc'}:
        raise HTTPException(503, 'Invalid authentication configuration')
    return value

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_key_cache = {}
_key_lock = threading.Lock()

def public_keys():
    filename = os.getenv('EVIDENCEDESK_OIDC_JWKS_FILE')
    if filename:
        path = Path(filename)
        if path.stat().st_size > 65536:
            raise ValueError('JWKS size')
        data = json.loads(path.read_bytes())
    else:
        url = os.getenv('EVIDENCEDESK_OIDC_JWKS_URL', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Trusted HTTPS JWKS URL required')
        with _key_lock:
            entry = _key_cache.get(url)
            if entry and entry[0] > time.monotonic():
                return entry[1]
            with build_opener(NoRedirect).open(url, timeout=5) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('JWKS size')
            data = json.loads(raw)
            _key_cache[url] = (time.monotonic() + 300, data)
    if not isinstance(data, dict) or not isinstance(data.get('keys'), list) or not 1 <= len(data['keys']) <= 32:
        raise ValueError('Invalid JWKS')
    return data


def verify(token, tenant):
    issuer = os.getenv('EVIDENCEDESK_OIDC_ISSUER', '')
    audience = os.getenv('EVIDENCEDESK_OIDC_AUDIENCE', '')
    if not issuer.startswith('https://') or not audience:
        raise HTTPException(503, 'Configure OIDC issuer, API audience and trusted JWKS')
    if not token or len(token) > 16384:
        raise HTTPException(401, 'Invalid access token')
    try:
        header = jwt.get_unverified_header(token)
        if any(name in header for name in ('jku','x5u','jwk')):
            raise ValueError('Use only configured signing keys')
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or len(header['kid']) > 200:
            raise ValueError('Signing algorithm or key')
        keys = public_keys()['keys']
        matches = [key for key in keys if key.get('kid') == header['kid'] and key.get('kty') == 'RSA'
                   and key.get('use', 'sig') == 'sig' and key.get('alg', 'RS256') == 'RS256']
        if len(matches) != 1:
            raise ValueError('Signing key')
        key = jwt.PyJWK.from_dict(matches[0], algorithm='RS256').key
        if key.key_size < 2048:
            raise ValueError('Signing key strength')
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=issuer, audience=audience,
                            options={'require': ['exp', 'iat', 'iss', 'sub', 'aud']})
        if claims.get('iss') != issuer or not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 200:
            raise ValueError('Identity claims')
        claims['sub'].encode('utf-8')
        if header.get('typ') != 'at+jwt' and claims.get('token_use') != 'access':
            raise ValueError('Use API access tokens, not ID tokens')
        for field in ('exp', 'iat'):
            if type(claims[field]) not in (int, float):
                raise ValueError('Numeric dates required')
        if not tenant or len(tenant) > 100:
            raise ValueError('Tenant selection')
        return Principal(tenant, issuer, claims['sub'])
    except (OSError, TimeoutError) as exc:
        raise HTTPException(503, 'OIDC signing keys unavailable') from exc
    except Exception as exc:
        raise HTTPException(401, 'Invalid or expired access token') from exc


def roles(db, scope):
    if not isinstance(scope, Principal):
        if mode() == 'oidc':
            raise Problem('verified_identity_required', 'A verified identity is required.', 403)
        return {'author', 'reviewer', 'admin'}
    row = db.execute('SELECT roles,active FROM memberships WHERE tenant=? AND issuer=? AND subject=?',
                     (str(scope), scope.issuer, scope.subject)).fetchone()
    if not row or not row['active']:
        raise Problem('membership_required', 'Current tenant membership is required.', 403)
    return set(json.loads(row['roles']))


def require(db, scope, action='read'):
    current = roles(db, scope)
    allowed = {'read': {'author','reviewer','admin'}, 'author': {'author','admin'},
               'reviewer': {'reviewer','admin'}, 'admin': {'admin'}}[action]
    if not current & allowed:
        raise Problem('forbidden', f'The {action} permission is required.', 403)
    return current


def can_read(db, scope, source_id, write=False):
    current = require(db, scope)
    if 'admin' in current:
        return True
    if not isinstance(scope, Principal):
        return True
    row = db.execute('SELECT can_write FROM document_acl WHERE tenant=? AND source_id=? AND issuer=? AND subject=?',
                     (str(scope), source_id, scope.issuer, scope.subject)).fetchone()
    return bool(row and (not write or row['can_write']))


def actor(scope):
    return scope.identity if isinstance(scope, Principal) else 'local-api-key (unverified)'
