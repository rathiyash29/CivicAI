"""
Composition root for the CivicAI API.

Start it with either of:

    uvicorn backend.app:app --reload        (from the repo root)
    uvicorn app:app --reload                (from backend/)

This module does not reimplement any route. It takes the application that
Member 1's `main.py` already builds and makes sure Member 2's intelligence
router is mounted under /intelligence.

Mounting is idempotent: `main.py` also calls `mount_intelligence` so that the
older `uvicorn main:app` command keeps working, and calling it twice will not
register the routes twice.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend import main  # noqa: E402  (needs the repo root on sys.path)


def create_app():
    """Return the fully-composed application."""
    app = main.app
    main.mount_intelligence(app)
    return app


app = create_app()
