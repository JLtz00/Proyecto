from __future__ import annotations

import uuid

import numpy as np
import pandas as pd

from .features import mt_stage
from .schemas import (
    DemoJourneyRequest, DemoJourneyResponse, SimulationAction, SimulationRequest, SimulationResponse,
)


def _derive_mt_eligibility(customer: pd.Series) -> None:
    if bool(customer.get("es_movistar_total")):
        customer["elegible_mt"] = False
        return
    customer["elegible_mt"] = bool(
        customer.get("tiene_movil")
        and customer.get("tipo_cliente") == "postpago"
        and customer.get("tiene_internet_hogar")
    )


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _apply_acquisition(customer: pd.Series, catalog: pd.DataFrame, offer_id: str) -> None:
    match = catalog.loc[catalog["oferta_id"].eq(offer_id)]
    if match.empty:
        raise KeyError(offer_id)
    offer = match.iloc[0]
    kind = str(offer["tipo_oferta"])
    if kind == "movistar_total":
        customer["es_movistar_total"] = True
        customer["tiene_movil"] = True
        customer["tiene_hogar"] = True
        customer["tiene_internet_hogar"] = True
        customer["tipo_cliente"] = "postpago"
    elif kind == "plan_movil":
        customer["tiene_movil"] = True
        customer["tipo_cliente"] = "postpago"
        customer["plan_actual_id"] = offer_id
    elif kind == "plan_hogar":
        customer["tiene_hogar"] = True
        customer["oferta_hogar_id"] = offer_id
        if "internet" in str(offer.get("descripcion_bundle", "")).lower():
            customer["tiene_internet_hogar"] = True
    _derive_mt_eligibility(customer)


def simulate(engine, request: SimulationRequest) -> SimulationResponse:
    if request.cliente_id not in engine.customer_index.index:
        raise KeyError(request.cliente_id)
    original = engine.customer_index.loc[request.cliente_id].copy()
    customer = original.copy()
    base = engine.recommend_override(original)
    rejected: dict[str, pd.Timestamp] = {}
    fatigue_delta = 0.0
    reference = pd.Timestamp(engine.config["features"]["as_of_date"])
    explicit_eligibility = False
    for action in request.actions:
        if action.action == "set_data_consumption":
            value = float(action.value)
            if value < 0:
                raise ValueError("El consumo no puede ser negativo")
            customer["consumo_datos_gb_prom"] = value
        elif action.action == "set_monthly_budget":
            value = float(action.value)
            if value <= 0:
                raise ValueError("El presupuesto debe ser mayor que cero")
            customer["monto_facturado_prom"] = value
        elif action.action == "set_mt_eligibility":
            explicit_eligibility = True
            customer["elegible_mt"] = bool(action.value)
        elif action.action == "acquire_offer":
            _apply_acquisition(customer, engine.catalog, str(action.oferta_id))
            explicit_eligibility = False
        elif action.action == "reject_offer":
            if not engine.catalog["oferta_id"].eq(action.oferta_id).any():
                raise KeyError(str(action.oferta_id))
            rejected[str(action.oferta_id)] = reference
        elif action.action == "add_commercial_fatigue":
            fatigue_delta += max(float(action.value), 0.0)
        elif action.action == "set_preferred_channel":
            channel = str(action.value)
            if channel not in {"Digital", "Tienda", "Call In", "Call Out"}:
                raise ValueError("Canal preferido inválido")
            customer["canal_mas_usado"] = channel
    if not explicit_eligibility and not bool(customer.get("es_movistar_total")):
        _derive_mt_eligibility(customer)
    simulated = engine.recommend_override(customer, rejected, reference, fatigue_delta)
    changed = {
        key: {"before": _plain(original.get(key)), "after": _plain(customer.get(key))}
        for key in customer.index
        if original.get(key) != customer.get(key)
    }
    base_offer = base.recommendation.oferta_id
    simulated_offer = simulated.recommendation.oferta_id
    recommendation_change = (
        f"Cambió de {base_offer} a {simulated_offer}: {simulated.commercial_strategy.rationale}"
        if base_offer != simulated_offer else
        f"Se mantiene {base_offer}; continúa siendo la mejor oferta elegible bajo el escenario."
    )
    return SimulationResponse(
        simulation_id=str(uuid.uuid4()), persisted=False, applied_actions=request.actions,
        changed_fields=changed, stage_change=f"{mt_stage(original)} -> {mt_stage(customer)}",
        recommendation_change=recommendation_change, base=base, simulated=simulated,
    )


def demo_journey(engine, request: DemoJourneyRequest) -> DemoJourneyResponse:
    if request.cliente_id not in engine.customer_index.index:
        raise KeyError(request.cliente_id)
    customer = engine.customer_index.loc[request.cliente_id].copy()
    initial = engine.recommend_override(customer)
    before_stage = mt_stage(customer)
    after_acceptance = engine.recommend_override(customer)
    activation_applied = before_stage in {"falta_internet_hogar", "falta_movil_postpago"}
    if activation_applied:
        _apply_acquisition(customer, engine.catalog, initial.recommendation.oferta_id)
        after_activation = engine.recommend_override(customer)
    else:
        after_activation = None
    rejected_result = after_activation or initial
    offer_id = rejected_result.recommendation.oferta_id
    rejection_date = pd.Timestamp(engine.config["features"]["as_of_date"])
    candidates = engine.recommend_override(customer, {offer_id: rejection_date})
    recovery = engine.recovery_for_override(customer, rejected_result, request.motivo_rechazo, rejection_date)
    wait_days = int(engine.config["rules"]["post_rejection_wait_days"].get(request.motivo_rechazo, 15))
    recontact_date = rejection_date + pd.Timedelta(days=wait_days)
    at_recontact = engine.recommend_override(customer, {offer_id: rejection_date}, recontact_date)
    stage_after = mt_stage(customer)
    events = []
    steps = [
        {"step": "initial", "state_version": 0, "mt_stage": before_stage,
         "recommendation": initial.recommendation.oferta_id,
         "decision_trace": initial.decision_trace.model_dump()},
        {"step": "accepted", "state_version": 0, "mt_stage": before_stage,
         "products_changed": False, "recommendation": after_acceptance.recommendation.oferta_id},
    ]
    if activation_applied:
        events.append({
            "event_type": "product_activated", "oferta_id": initial.recommendation.oferta_id,
            "decision_id": initial.decision_id, "source": "provisioning",
            "evidence_type": "order", "evidence_reference": "DEMO-ORDER",
            "expected_state_version": 0,
        })
        steps.append({
            "step": "activated", "state_version": 1, "mt_stage": stage_after,
            "products_changed": True, "recommendation": after_activation.recommendation.oferta_id,
            "decision_trace": after_activation.decision_trace.model_dump(),
        })
    events.append({
        "event_type": "rejected", "decision_id": rejected_result.decision_id,
        "oferta_id": offer_id, "motivo_rechazo": request.motivo_rechazo,
    })
    steps.extend([
        {"step": "rejected", "state_version": int(activation_applied), "mt_stage": stage_after,
         "recommendation": candidates.recommendation.oferta_id,
         "decision_trace": candidates.decision_trace.model_dump()},
        {"step": "recontact", "date": recovery.recontact_from,
         "recommendation": at_recontact.recommendation.oferta_id,
         "decision_trace": at_recontact.decision_trace.model_dump()},
    ])
    markdown = (
        f"# Recorrido NBO — {request.cliente_id}\n\n"
        f"1. Inicial: **{initial.recommendation.nombre_oferta}** por {initial.recommendation.canal}.\n"
        f"2. Rechazo simulado: **{request.motivo_rechazo}**.\n"
        f"3. Acción: {recovery.action}; recontactar desde {recovery.recontact_from}.\n"
        f"4. Inmediata: **{candidates.recommendation.nombre_oferta}**.\n"
        f"5. Al recontacto: **{at_recontact.recommendation.nombre_oferta}**.\n"
    )
    activation_line = (
        f"3. Activacion confirmada de **{initial.recommendation.oferta_id}**: version 0 -> 1; "
        f"etapa {before_stage} -> {stage_after}. Nueva NBO: **{after_activation.recommendation.oferta_id}**.\n"
        if activation_applied else "3. No se simula activacion antes del rechazo en esta etapa.\n"
    )
    adaptive_markdown = (
        f"# Recorrido adaptativo NBO - {request.cliente_id}\n\n"
        f"1. Estado inicial ({before_stage}, version 0): **{initial.recommendation.nombre_oferta}** por {initial.recommendation.canal}.\n"
        f"2. Aceptacion: intencion registrada; **no cambia productos ni version de estado**.\n"
        + activation_line
        + f"4. Rechazo de **{offer_id}** por **{request.motivo_rechazo}**; se aplica cooldown.\n"
        f"5. Accion: {recovery.action}; recontactar desde {recovery.recontact_from}.\n"
        f"6. NBO inmediata: **{candidates.recommendation.nombre_oferta}**.\n"
        f"7. Al recontacto: **{at_recontact.recommendation.nombre_oferta}**.\n"
    )
    return DemoJourneyResponse(
        journey_id=str(uuid.uuid4()), cliente_id=request.cliente_id, persisted=False,
        initial=initial, after_acceptance=after_acceptance, after_activation=after_activation,
        recovery_action=recovery, immediate_after_rejection=candidates,
        at_recontact=at_recontact, steps=steps, events_to_register=events,
        markdown=adaptive_markdown,
    )
