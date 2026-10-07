"""Run from project root: python -m scripts.demo"""
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from app.core import Store
with TemporaryDirectory() as directory:
    store = Store(Path(directory)/"demo.db")
    store.add_document("demo", "Encryption policy", "Customer data is encrypted at rest using AES-256. Transport encryption uses TLS 1.2 or higher.", "1.0", "2099-01-01")
    answer = store.draft("demo", "How is customer data encrypted at rest?")
    print(json.dumps(answer, indent=2))
    store.approve("demo", answer["id"], "demo-reviewer", answer["draft"])
    print(store.export("demo"))
