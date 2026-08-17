from __future__ import annotations

from typing import Any, Callable

from flask import Blueprint, current_app, render_template, request

from ..advisor_ui import AdvisorApiError
from ..jury_session import JuryFlowError, JurySession


jury = Blueprint("jury", __name__, url_prefix="/jury")


def _session() -> JurySession:
    session = current_app.extensions.get("jury_session")
    if session is None:
        raise AdvisorApiError("Modo Jurado no disponible", 404)
    return session


def _render(context: dict[str, Any], status: int = 200):
    if request.headers.get("HX-Request", "").lower() == "true":
        return render_template("jury/partials/dashboard.html", **context), status
    return render_template("jury/index.html", **context), status


def _action(operation: Callable[[], dict[str, Any]]):
    try:
        return _render(operation())
    except JuryFlowError as exc:
        context = _session().context(str(exc))
        context["flow_error"] = str(exc)
        return _render(context, 409)


@jury.get("")
@jury.get("/")
def index():
    return _render(_session().context())


@jury.post("/scenario/reset")
def reset():
    return _action(_session().reset)


@jury.post("/scenario/start")
def start():
    return _action(_session().start)


@jury.post("/scenario/accept")
def accept():
    return _action(_session().accept)


@jury.post("/scenario/activate")
def activate():
    return _action(_session().activate)


@jury.post("/scenario/reject")
def reject():
    return _action(_session().reject)


@jury.post("/scenario/recalculate")
def recalculate():
    return _action(_session().recalculate)
