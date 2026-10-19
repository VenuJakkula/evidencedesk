"""Real Docker smoke gate. Never runs against a user's existing container or volume."""
import argparse
import json
import os
import secrets
import subprocess
import time
import uuid
import httpx


def command(*args):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,timeout=120).stdout.strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',default='evidencedesk:ci');args=parser.parse_args()
    name='evidencedesk-smoke-'+uuid.uuid4().hex
    key=secrets.token_urlsafe(32)
    env=dict(os.environ,EVIDENCEDESK_API_KEY=key)
    try:
        subprocess.run(['docker','run','-d','--name',name,'--read-only','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
            '--tmpfs','/data:rw,nosuid,size=64m,uid=10001,gid=10001',
            '-p','127.0.0.1::8000','-e','EVIDENCEDESK_API_KEY',args.image],env=env,
            check=True,capture_output=True,text=True,timeout=120)
        endpoint='http://'+command('port',name,'8000/tcp').splitlines()[0]
        with httpx.Client(base_url=endpoint,timeout=5) as http:
            for _ in range(60):
                try:
                    if http.get('/ready').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.5)
            else:raise RuntimeError('Container not ready')
            assert http.post('/documents',json={}).status_code==401
            body={'title':'Synthetic','content':'Synthetic data is encrypted.','version':'1','valid_until':'2099-01-01'}
            assert http.post('/documents',headers={'X-API-Key':key},json=body).status_code==201
            assert command('exec',name,'id','-u')=='10001'
        command('restart',name)
        with httpx.Client(base_url=endpoint,timeout=5) as http:
            for _ in range(60):
                try:
                    if http.get('/ready').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.5)
            else:raise RuntimeError('Restart not ready')
        print(json.dumps({'container_smoke':'passed','non_root':True,'read_only':True,
            'authenticated_write':True,'restart':'passed','staging_rollback':'not exercised'}))
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)

if __name__=='__main__':main()
