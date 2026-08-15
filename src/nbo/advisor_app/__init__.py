from __future__ import annotations

import secrets
from typing import Any

from flask import Flask, request
from flask_wtf.csrf import CSRFProtect

from ..advisor_local import LocalAdvisorApi
from ..advisor_ui import (
    advisor_confidence, advisor_fit_level, advisor_fit_level_key, advisor_level,
    advisor_level_key, advisor_next_step, alternative_rows,
    confidence_summary, label_event, label_moment, label_objective, label_rejection,
    label_stage, label_urgency, money, percentage, service_summary,
)
from ..engine import NBOEngine


csrf = CSRFProtect()


def create_app(
    config: dict[str, Any] | None = None,
    backend: Any | None = None,
    jury_session: Any | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY=secrets.token_hex(32),
        WTF_CSRF_TIME_LIMIT=None,
        ADVISOR_BACKEND=None,
        ADVISOR_STARTUP_ERROR=None,
        JURY_MODE=False,
    )
    if config:
        app.config.update(config)

    if app.config["JURY_MODE"] and jury_session is None:
        from ..jury_session import JurySession
        jury_session = JurySession()
    if jury_session is not None:
        backend = jury_session.backend
        app.extensions["jury_session"] = jury_session
    elif backend is None:
        try:
            backend = LocalAdvisorApi(NBOEngine(persist=True))
        except Exception as exc:  # La pantalla y /health deben seguir disponibles.
            app.config["ADVISOR_STARTUP_ERROR"] = str(exc)
    app.extensions["advisor_backend"] = backend
    csrf.init_app(app)

    from .routes import advisor
    app.register_blueprint(advisor)
    if app.config["JURY_MODE"]:
        from .jury_routes import jury
        app.register_blueprint(jury)

    app.jinja_env.filters.update(
        money=money,
        percentage=percentage,
        stage_label=label_stage,
        objective_label=label_objective,
        rejection_label=label_rejection,
        event_label=label_event,
        moment_label=label_moment,
        urgency_label=label_urgency,
        advisor_level=advisor_level,
        advisor_level_key=advisor_level_key,
        advisor_fit_level=advisor_fit_level,
        advisor_fit_level_key=advisor_fit_level_key,
    )
    app.jinja_env.globals.update(
        alternative_rows=alternative_rows,
        confidence_summary=confidence_summary,
        advisor_confidence=advisor_confidence,
        advisor_next_step=advisor_next_step,
        service_summary=service_summary,
    )

    @app.after_request
    def secure_local_response(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith(("/ui/", "/jury")):
            response.headers["Vary"] = "HX-Request"
        return response

    return app
