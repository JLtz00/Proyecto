from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .advisor_ui import AdvisorApiError
from .persistence import StateVersionConflict
from .schemas import CustomerEventRequest, FeedbackRequest, FunnelEventRequest, NBORequest
from .jury import executive_report
from .economics import simulate_economics
from .schemas import DemoJourneyRequest, EconomicSimulationRequest
from .simulation import demo_journey


class LocalAdvisorApi:
    """Backend local de la Mesa comercial, independiente de Uvicorn."""

    def __init__(self, engine: Any):
        if engine.store is None or engine.state_service is None:
            raise AdvisorApiError("El motor local requiere persistencia habilitada.")
        self.engine = engine
        self.store = engine.store

    @staticmethod
    def _json(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="json")

    @staticmethod
    def _wrap_error(exc: Exception) -> AdvisorApiError:
        if isinstance(exc, StateVersionConflict):
            return AdvisorApiError(str(exc), 409)
        if isinstance(exc, KeyError):
            return AdvisorApiError(f"Recurso inexistente: {exc.args[0]}", 404)
        if isinstance(exc, ValueError):
            return AdvisorApiError(str(exc), 422)
        return AdvisorApiError(str(exc))

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok", "api_version": "1.5.0",
            "model_version": self.engine.versions["model_version"],
            "rules_version": self.engine.versions["rules_version"],
            "decision_schema_version": self.engine.config["project"]["decision_schema_version"],
        }

    def metrics(self, source: str = "operational") -> dict[str, Any]:
        if source not in {"operational", "demo"}:
            raise AdvisorApiError("source debe ser operational o demo", 422)
        return executive_report(self.store.business_metrics(), source)

    def demo_journey(self, cliente_id: str = "CLI000001", motivo: str = "precio") -> dict[str, Any]:
        try:
            return self._json(demo_journey(
                self.engine, DemoJourneyRequest(cliente_id=cliente_id, motivo_rechazo=motivo)
            ))
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def economics(self, cliente_id: str, assumptions: dict[str, Any]) -> dict[str, Any]:
        try:
            request = EconomicSimulationRequest(cliente_id=cliente_id, assumptions=assumptions)
            return self._json(simulate_economics(self.engine, request))
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def recommend(self, cliente_id: str) -> dict[str, Any]:
        try:
            request = NBORequest(cliente_id=cliente_id.strip().upper())
            return self._json(self.engine.recommend(request.cliente_id))
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def customer_state(self, cliente_id: str) -> dict[str, Any]:
        try:
            return self._json(self.engine.state_service.get_state(cliente_id))
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def customer_events(self, cliente_id: str) -> list[dict[str, Any]]:
        if cliente_id not in self.engine.customer_index.index:
            raise AdvisorApiError(f"Cliente inexistente: {cliente_id}", 404)
        return self.store.list_customer_events(cliente_id)

    def save_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            action = None
            if payload["resultado_final"] == "rechazada":
                action = self.engine.post_rejection_action(
                    payload["decision_id"], payload["motivo_rechazo"],
                )
                payload = {**payload, "post_rejection_action": action.model_dump(mode="json")}
            feedback_id = self.store.save_feedback(payload)
            return {
                "feedback_id": feedback_id, "decision_id": payload["decision_id"],
                "status": "recorded",
                "post_rejection_action": action.model_dump(mode="json") if action else None,
            }
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def save_funnel_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            event_id = self.store.save_funnel_event(payload)
            return {"event_id": event_id, "decision_id": payload["decision_id"], "status": "recorded"}
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def activate_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = CustomerEventRequest(**payload)
            event, previous, current, changed, replay = self.engine.state_service.register_event(request)
            recommendation = None
            warning = None
            try:
                recommendation = self.engine.recommend(request.cliente_id)
            except RuntimeError as exc:
                warning = str(exc)
            return {
                "event": self._json(event), "previous_state": self._json(previous),
                "new_state": self._json(current), "changed_fields": changed,
                "mt_stage_change": f"{previous.mt_stage} -> {current.mt_stage}",
                "recommendation": self._json(recommendation) if recommendation else None,
                "warning": warning, "idempotent_replay": replay,
            }
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def workspace(self, cliente_id: str) -> dict[str, Any]:
        result = self.recommend(cliente_id)
        return self.workspace_for_decision(result["decision_id"])

    def workspace_for_decision(self, decision_id: str) -> dict[str, Any]:
        try:
            result = self.store.get_decision_payload(decision_id)
            cliente_id = str(result["cliente"]["cliente_id"])
            return {
                "result": result,
                "state": self.customer_state(cliente_id),
                "events": self.customer_events(cliente_id),
                "interaction": self.store.get_decision_interaction(decision_id),
            }
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def record_contact(self, decision_id: str) -> dict[str, Any]:
        """Traza displayed/contacted usando exclusivamente la decisión persistida."""
        try:
            decision = self.store.get_decision_payload(decision_id)
            top = decision["recommendation"]
            for event_type in ("displayed", "contacted"):
                request = FunnelEventRequest(
                    decision_id=decision_id,
                    event_type=event_type,
                    oferta_id=top["oferta_id"],
                    canal=top["canal"],
                    medio_probatorio="registro_plataforma" if event_type == "contacted" else None,
                    evidencia_referencia="advisor_dashboard" if event_type == "contacted" else None,
                )
                try:
                    self.save_funnel_event(request.model_dump())
                except AdvisorApiError as exc:
                    if exc.status_code != 422 or "ya fue registrado" not in str(exc):
                        raise
            return self.workspace_for_decision(decision_id)
        except Exception as exc:
            if isinstance(exc, AdvisorApiError):
                raise
            raise self._wrap_error(exc) from exc

    def record_feedback(self, decision_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Valida feedback sin aceptar identidad, oferta ni canal del formulario."""
        try:
            self.store.get_decision(decision_id)
            request = FeedbackRequest(decision_id=decision_id, **values)
            self.save_feedback(request.model_dump())
            return self.workspace_for_decision(decision_id)
        except Exception as exc:
            if isinstance(exc, AdvisorApiError):
                raise
            raise self._wrap_error(exc) from exc

    def activate_decision(self, decision_id: str, evidence_reference: str) -> dict[str, Any]:
        """Activa el Top 1 aceptado con identidad y versión tomadas de SQLite."""
        try:
            row = self.store.get_decision(decision_id)
            result = self.store.get_decision_payload(decision_id)
            cliente_id = str(row["cliente_id"])
            oferta_id = str(row["top_offer_id"])
            evidence = evidence_reference.strip()
            request = CustomerEventRequest(
                cliente_id=cliente_id,
                event_type="product_activated",
                effective_at=datetime.now(timezone.utc),
                source="advisor_dashboard",
                idempotency_key=f"advisor:{decision_id}:{oferta_id}:{evidence}",
                expected_state_version=int(row.get("state_version", result.get("state_version", 0))),
                oferta_id=oferta_id,
                decision_id=decision_id,
                evidence_type="registro_plataforma",
                evidence_reference=evidence,
            )
            response = self.activate_product(request.model_dump())
            recommendation = response.get("recommendation")
            if recommendation:
                return self.workspace_for_decision(recommendation["decision_id"])
            return self.workspace_for_decision(decision_id)
        except Exception as exc:
            if isinstance(exc, AdvisorApiError):
                raise
            raise self._wrap_error(exc) from exc
