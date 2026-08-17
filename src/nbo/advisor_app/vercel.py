from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

from ..advisor_local import LocalAdvisorApi
from ..engine import NBOEngine
from . import create_app


def temporary_database_path() -> Path:
    """Return a writable database path for one Vercel function instance."""
    configured = os.environ.get("NBO_VERCEL_DATABASE_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "nbo-advisor-vercel.sqlite3"


def create_vercel_app():
    """Build the public, read-only Advisor Desk; jury routes are never registered."""
    backend = LocalAdvisorApi(
        NBOEngine(persist=True, database_path=temporary_database_path())
    )
    return create_app(
        {
            "ADVISOR_READ_ONLY": True,
            "JURY_MODE": False,
            "SECRET_KEY": os.environ.get("NBO_SECRET_KEY") or secrets.token_hex(32),
        },
        backend=backend,
    )
