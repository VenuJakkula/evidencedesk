"""Reset only the database explicitly owned by the browser harness."""
import json
import sys
from pathlib import Path
from app.core import Store


def reset(directory):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir() or not root.name.startswith('evidencedesk-browser-'):
        raise ValueError('Expected a harness-owned temporary browser directory.')
    marker = root / '.browser-fixture.json'
    if json.loads(marker.read_text()) != {'database': 'browser.db', 'purpose': 'synthetic-browser-tests'}:
        raise ValueError('Missing browser-test ownership marker.')
    database = root / 'browser.db'
    if database.resolve().parent != root:
        raise ValueError('Browser database must stay inside the harness directory.')
    # Only this verified harness-owned file is replaced; application databases are never reset.
    database.unlink(missing_ok=True)
    for suffix in ('.workflow.sqlite','.workflow.sqlite-wal','.workflow.sqlite-shm'):
        checkpoint=Path(str(database)+suffix)
        if checkpoint.resolve().parent != root: raise ValueError('Checkpoint must stay inside the harness directory.')
        checkpoint.unlink(missing_ok=True)
    Store(database)
    fixture = root / 'oidc-fixture.json'
    if fixture.exists():
        from .oidc_fixture import seed
        seed(root)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python -m scripts.browser_fixture <owned temporary directory>')
    reset(sys.argv[1])
