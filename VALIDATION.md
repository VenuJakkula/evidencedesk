# Validation on 2026-10-07

Executed locally using Python 3.12:

- `python -m pytest -q`: 8 passed. One upstream Starlette/httpx deprecation warning.
- `python -m scripts.evaluate`: 3 synthetic regression cases, zero failures.
- `python -m scripts.demo`: evidence -> draft -> approval -> CSV completed.

Tested FastAPI 0.142.2, Uvicorn 0.54.0, httpx 0.28.1, pytest 9.1.1. Dependency ranges are specified; a complete locked environment remains a deployment task.

Docker executable is unavailable in the initialization environment. Image build, Compose, GitHub-hosted CI and cloud/Kubernetes deployment were not executed. No live LLMs or external services were called by the application. No benchmark, production reliability or commercial validation is claimed.

## Windows baseline check on 2026-10-07

Using the local Python 3.14 virtual environment, pytest reported 2 passed and 6 failed. The six core tests failed during temporary-directory cleanup with WinError 32 because SQLite database files remained open. This issue is preserved in the initial baseline for a follow-up fix. One Starlette/httpx deprecation warning was also reported.
