from __future__ import annotations

from typing import Any

from .advisor_ui import AdvisorApiError
from .challenge_metrics import compute_challenge_metrics
from .persistence import StateVersionConflict
from .schemas import CustomerEventRequest
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
            return self._json(self.engine.recommend(cliente_id))
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def challenge_kpis(self, sample_size: int = 500, seed: int = 42) -> dict[str, Any]:
        try:
            return compute_challenge_metrics(self.engine, sample_size=sample_size, seed=seed)
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def what_if(self, cliente_id: str, scoring_overrides: dict[str, float]) -> dict[str, Any]:
        try:
            customer = self.engine.customer_index.loc[cliente_id]
            base = self.engine.recommend_override(customer)
            saved_scoring = dict(self.engine.scoring)
            override = {**saved_scoring, **{k: float(v) for k, v in scoring_overrides.items()}}
            self.engine.scoring = override
            try:
                simulated = self.engine.recommend_override(customer)
            finally:
                self.engine.scoring = saved_scoring
            return {
                "base": self._json(base),
                "simulated": self._json(simulated),
                "scoring_used": override,
                "scoring_default": saved_scoring,
            }
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
