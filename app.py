"""Vercel WSGI entry point for the public Advisor Desk."""

from nbo.advisor_app.vercel import create_vercel_app


app = create_vercel_app()
