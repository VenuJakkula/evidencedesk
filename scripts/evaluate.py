"""Small synthetic regression gate, not a commercial-quality benchmark."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from app.core import Store
cases = json.loads((Path(__file__).resolve().parents[1]/"evals/cases.json").read_text())
with TemporaryDirectory() as directory:
    store = Store(Path(directory)/"eval.db")
    store.add_document("demo", "Policy", "Customer data is encrypted at rest using AES-256. Transport encryption uses TLS 1.2 or higher.", "1", "2099-01-01")
    failures = []
    for case in cases:
        answer = store.draft("demo", case["question"])
        if answer["status"] != case["status"] or case["expected"] not in answer["draft"]:
            failures.append(case["question"])
    print(json.dumps({"cases": len(cases), "failures": failures, "provider": "extractive-baseline"}))
    if failures:
        raise SystemExit(1)
