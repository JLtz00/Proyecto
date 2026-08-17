"""Vercel WSGI entry point for the public Advisor Desk."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nbo.advisor_app.vercel import create_vercel_app


app = create_vercel_app()
