"""Regression coverage for Docker-assigned ports across container restart."""
import sys
from types import SimpleNamespace

from scripts import container_smoke


def test_restart_rediscovers_published_port(monkeypatch):
    endpoints = []
    commands = []
    ports = iter(['127.0.0.1:31001', '127.0.0.1:31002'])

    def command(*args):
        commands.append(args)
        if args[0] == 'port':
            return next(ports)
        if args[0] == 'exec':
            return '10001'
        return ''

    class Client:
        def __init__(self, *, base_url, timeout):
            endpoints.append(base_url)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, path):
            assert path == '/ready'
            return SimpleNamespace(status_code=200)

        def post(self, path, **kwargs):
            return SimpleNamespace(status_code=201 if 'headers' in kwargs else 401)

    processes = []
    monkeypatch.setattr(sys, 'argv', ['container_smoke'])
    monkeypatch.setattr(container_smoke, 'command', command)
    monkeypatch.setattr(container_smoke.httpx, 'Client', Client)
    monkeypatch.setattr(container_smoke.subprocess, 'run',
                        lambda args, **kwargs: processes.append(args))
    container_smoke.main()

    assert endpoints == ['http://127.0.0.1:31001', 'http://127.0.0.1:31002']
    assert [args[0] for args in commands] == ['port', 'exec', 'restart', 'port']
    assert processes[-1][:3] == ['docker', 'rm', '-f']
