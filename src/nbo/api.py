from __future__ import annotations

from functools import lru_cache

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query

from .config import load_config
from .engine import ArtifactUnavailable, NBOEngine
from .economics import simulate_economics
from .llm_renderer import render_playbook
from .jury import executive_report
from .persistence import DecisionStore, StateVersionConflict
from .schemas import (
    BatchRequest, DemoJourneyRequest, DemoJourneyResponse, EconomicSimulationRequest,
    CustomerEventRequest, CustomerEventResponse, CustomerState, CustomerStateEvent, LearningReadiness,
    EconomicSimulationResponse, FeedbackRequest, FeedbackResponse, FunnelEventRequest,
    NBORequest, NBOResult, PlaybookRenderRequest, PlaybookRenderResponse,
    SimulationRequest, SimulationResponse,
)
from .simulation import demo_journey, simulate


app = FastAPI(title="Movistar Next Best Offer API", version="1.5.0")


@lru_cache(maxsize=1)
def get_engine() -> NBOEngine:
    return NBOEngine()


@lru_cache(maxsize=1)
def get_store() -> DecisionStore:
    return DecisionStore(load_config()["project"]["database_path"])


def _engine_or_503() -> NBOEngine:
    try:
        return get_engine()
    except ArtifactUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    try:
        engine = get_engine()
        return {
            "status": "ok", "api_version": app.version,
            "model_version": engine.versions["model_version"],
            "rules_version": engine.versions["rules_version"],
            "decision_schema_version": engine.config["project"]["decision_schema_version"],
        }
    except ArtifactUnavailable as exc:
        return {"status": "degraded", "detail": str(exc)}


@app.post("/api/v1/nbo/recommend", response_model=NBOResult)
def recommend(request: NBORequest) -> NBOResult:
    try:
        return _engine_or_503().recommend(request.cliente_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Cliente inexistente: {request.cliente_id}") from exc


@app.post("/api/v1/nbo/batch", response_model=list[NBOResult])
def batch(request: BatchRequest) -> list[NBOResult]:
    engine = _engine_or_503()
    ids = request.cliente_ids if request.cliente_ids is not None else engine.customers["cliente_id"].head(request.limit).tolist()
    missing = [client_id for client_id in ids if client_id not in engine.customer_index.index]
    if missing:
        raise HTTPException(status_code=404, detail={"clientes_inexistentes": missing[:20]})
    return engine.recommend_many(ids)


@app.post("/api/v1/nbo/feedback", status_code=201, response_model=FeedbackResponse)
def feedback(request: FeedbackRequest) -> FeedbackResponse:
    try:
        payload = request.model_dump()
        action = None
        if request.resultado_final == "rechazada":
            action = _engine_or_503().post_rejection_action(request.decision_id, request.motivo_rechazo)
            payload["post_rejection_action"] = action.model_dump()
        feedback_id = get_store().save_feedback(payload)
        return FeedbackResponse(
            feedback_id=feedback_id, decision_id=request.decision_id,
            status="recorded", post_rejection_action=action,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Decision inexistente: {request.decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/nbo/metrics")
def metrics(source: str = Query(default="operational", pattern="^(operational|demo)$")) -> dict:
    return executive_report(get_store().business_metrics(), source)


@app.get("/api/v1/nbo/executive-report")
def executive_metrics(source: str = Query(default="operational", pattern="^(operational|demo)$")) -> dict:
    return executive_report(get_store().business_metrics(), source)


@app.post("/api/v1/nbo/customer-events", status_code=201, response_model=CustomerEventResponse)
def customer_event(request: CustomerEventRequest) -> CustomerEventResponse:
    engine = _engine_or_503()
    if engine.state_service is None:
        raise HTTPException(status_code=503, detail="El estado operacional requiere persistencia")
    try:
        event, previous, current, changed, replay = engine.state_service.register_event(request)
        recommendation = None
        warning = None
        try:
            recommendation = engine.recommend(request.cliente_id)
        except RuntimeError as exc:
            warning = str(exc)
        return CustomerEventResponse(
            event=event, previous_state=previous, new_state=current, changed_fields=changed,
            mt_stage_change=f"{previous.mt_stage} -> {current.mt_stage}",
            recommendation=recommendation, warning=warning, idempotent_replay=replay,
        )
    except StateVersionConflict as exc:
        engine.store.record_customer_event_rejection(
            request.cliente_id, request.idempotency_key, "version_conflict", str(exc),
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        label = "Cliente, oferta, decision o evento inexistente"
        raise HTTPException(status_code=404, detail=f"{label}: {exc.args[0]}") from exc
    except ValueError as exc:
        engine.store.record_customer_event_rejection(
            request.cliente_id, request.idempotency_key, "incoherent", str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/nbo/customer-state/{cliente_id}", response_model=CustomerState)
def customer_state(cliente_id: str, as_of: datetime | None = Query(default=None)) -> CustomerState:
    engine = _engine_or_503()
    if engine.state_service is None:
        raise HTTPException(status_code=503, detail="El estado operacional requiere persistencia")
    try:
        return engine.state_service.get_state(cliente_id, as_of)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Cliente inexistente: {cliente_id}") from exc


@app.get("/api/v1/nbo/customer-state/{cliente_id}/events", response_model=list[CustomerStateEvent])
def customer_state_events(cliente_id: str) -> list[CustomerStateEvent]:
    engine = _engine_or_503()
    if cliente_id not in engine.customer_index.index:
        raise HTTPException(status_code=404, detail=f"Cliente inexistente: {cliente_id}")
    return [CustomerStateEvent(**item) for item in get_store().list_customer_events(cliente_id)]


@app.get("/api/v1/nbo/learning/readiness", response_model=LearningReadiness)
def learning_readiness() -> LearningReadiness:
    engine = _engine_or_503()
    thresholds = engine.config.get("learning", {}).get("readiness_thresholds", {
        "feedback": 500, "customers": 250, "channels": 3, "offers": 10,
    })
    trained_at = engine.metadata.get("trained_at") or engine.metadata.get("created_at")
    return LearningReadiness(**get_store().learning_readiness(thresholds, trained_at))


@app.post("/api/v1/nbo/events", status_code=201)
def funnel_event(request: FunnelEventRequest) -> dict:
    try:
        event_id = get_store().save_funnel_event(request.model_dump())
        return {"event_id": event_id, "decision_id": request.decision_id, "status": "recorded"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Decision inexistente: {request.decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/nbo/decisions/{decision_id}")
def decision_detail(decision_id: str) -> dict:
    try:
        return get_store().get_decision_payload(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Decision inexistente: {decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/nbo/simulate", response_model=SimulationResponse)
def simulate_scenario(request: SimulationRequest) -> SimulationResponse:
    try:
        return simulate(_engine_or_503(), request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Cliente u oferta inexistente: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/nbo/demo/journey", response_model=DemoJourneyResponse)
def journey(request: DemoJourneyRequest) -> DemoJourneyResponse:
    try:
        return demo_journey(_engine_or_503(), request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Cliente inexistente: {request.cliente_id}") from exc


@app.post("/api/v1/nbo/economics/simulate", response_model=EconomicSimulationResponse)
def economics(request: EconomicSimulationRequest) -> EconomicSimulationResponse:
    try:
        return simulate_economics(_engine_or_503(), request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Cliente inexistente: {request.cliente_id}") from exc


@app.post("/api/v1/nbo/playbook/render", response_model=PlaybookRenderResponse)
def render(request: PlaybookRenderRequest) -> PlaybookRenderResponse:
    try:
        decision = get_store().get_decision_payload(request.decision_id)
        return render_playbook(decision, request.tone, load_config(), get_store())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Decision inexistente: {request.decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
