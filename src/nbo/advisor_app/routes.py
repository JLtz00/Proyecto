from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from pydantic import ValidationError

from ..advisor_ui import AdvisorApiError


advisor = Blueprint("advisor", __name__)


def _backend() -> Any:
    backend = current_app.extensions.get("advisor_backend")
    if backend is None:
        raise AdvisorApiError(
            current_app.config.get("ADVISOR_STARTUP_ERROR") or "Motor no disponible", 503,
        )
    return backend


def _is_htmx() -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _render_workspace(context: dict[str, Any], *, toast: str | None = None, status: int = 200):
    if _is_htmx():
        return render_template("partials/workspace.html", context=context, toast=toast), status
    cliente_id = context["result"]["cliente"]["cliente_id"]
    return render_template(
        "index.html", context=context, cliente_id=cliente_id, toast=toast, health=_health(),
    ), status


def _error(message: str, status: int):
    template = "partials/error.html" if _is_htmx() else "index.html"
    return render_template(template, error=message, health=_health()), status


def _health() -> dict[str, Any]:
    try:
        return _backend().health()
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)}


@advisor.get("/")
def index():
    cliente_id = request.args.get("cliente_id", "").strip().upper()
    context = None
    error = None
    status = 200
    if cliente_id:
        try:
            context = _backend().workspace(cliente_id)
        except AdvisorApiError as exc:
            error, status = str(exc), exc.status_code or 503
    return render_template(
        "index.html", context=context, cliente_id=cliente_id, error=error, health=_health(),
    ), status


@advisor.get("/ui/clientes/<cliente_id>/workspace")
def customer_workspace(cliente_id: str):
    try:
        context = _backend().workspace(cliente_id.strip().upper())
        return _render_workspace(context)
    except AdvisorApiError as exc:
        return _error(str(exc), exc.status_code or 503)


@advisor.get("/ui/clientes/workspace")
def customer_search():
    cliente_id = request.args.get("cliente_id", "").strip().upper()
    if not cliente_id:
        return _error("Ingresa un identificador de cliente.", 422)
    try:
        return _render_workspace(_backend().workspace(cliente_id))
    except AdvisorApiError as exc:
        return _error(str(exc), exc.status_code or 503)


@advisor.post("/ui/decisiones/<decision_id>/contacto")
def contact(decision_id: str):
    context = _backend().record_contact(decision_id)
    return _render_workspace(context, toast="Contacto iniciado y trazado.")


@advisor.post("/ui/decisiones/<decision_id>/feedback")
def feedback(decision_id: str):
    values: dict[str, Any] = {
        "resultado_final": request.form.get("resultado_final", ""),
        "medio_probatorio": request.form.get("medio_probatorio", ""),
        "rebate_usado": request.form.get("rebate_usado") == "true",
    }
    if request.form.get("motivo_rechazo"):
        values["motivo_rechazo"] = request.form["motivo_rechazo"]
    if request.form.get("resultado_rebate"):
        values["resultado_rebate"] = request.form["resultado_rebate"]
    context = _backend().record_feedback(decision_id, values)
    outcome = values["resultado_final"]
    message = (
        "Aceptación registrada. La activación continúa pendiente."
        if outcome == "aceptada" else "Resultado registrado en el historial comercial."
    )
    return _render_workspace(context, toast=message)


@advisor.post("/ui/decisiones/<decision_id>/activacion")
def activation(decision_id: str):
    context = _backend().activate_decision(
        decision_id, request.form.get("evidence_reference", ""),
    )
    return _render_workspace(
        context, toast="Producto activado. La siguiente mejor acción fue recalculada.",
    )


@advisor.post("/ui/clientes/<cliente_id>/recalcular")
def recalculate(cliente_id: str):
    context = _backend().workspace(cliente_id.strip().upper())
    return _render_workspace(context, toast="Siguiente mejor acción recalculada.")


@advisor.get("/health")
def health():
    payload = _health()
    return jsonify(payload), 200 if payload.get("status") == "ok" else 503


@advisor.app_errorhandler(CSRFError)
def csrf_error(exc: CSRFError):
    return _error("La sesión del formulario expiró. Recarga la página e inténtalo otra vez.", 400)


@advisor.app_errorhandler(ValidationError)
def validation_error(exc: ValidationError):
    messages = "; ".join(error["msg"] for error in exc.errors())
    return _error(messages, 422)


@advisor.app_errorhandler(AdvisorApiError)
def advisor_error(exc: AdvisorApiError):
    return _error(str(exc), exc.status_code or 503)
