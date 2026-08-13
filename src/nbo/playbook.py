from __future__ import annotations

from typing import Any, Mapping

from .schemas import (
    CommercialStrategy, Explanation, Objection, PostRejectionAction, Rebate, SalesPlaybook,
)


CHANNEL_GUIDANCE = {
    "Digital": (
        "mensaje_breve",
        "Tenemos una alternativa que puede ajustarse a sus servicios actuales.",
    ),
    "Tienda": (
        "conversacion_consultiva",
        "Antes de recomendarle algo, revisemos brevemente qué servicio le aportaría más valor.",
    ),
    "Call In": (
        "respuesta_contextual",
        "Aprovechando su consulta, podemos revisar una alternativa compatible con sus servicios.",
    ),
    "Call Out": (
        "llamada_con_permiso",
        "¿Nos permite comentarle brevemente una alternativa que podría resultarle útil?",
    ),
}


STAGE_QUESTIONS = {
    "elegible_mt": "¿Le interesaría integrar sus servicios móvil y hogar en una sola propuesta?",
    "falta_internet_hogar": "¿Está buscando incorporar o mejorar el servicio de internet en su hogar?",
    "falta_movil_postpago": "¿Le resultaría útil contar con una línea móvil postpago dentro de su relación actual?",
    "ya_es_mt": "¿Qué aspecto de sus servicios actuales le gustaría mejorar o complementar?",
}


TYPE_QUESTIONS = {
    "plan_movil": "¿La capacidad de datos de su plan actual cubre normalmente su uso?",
    "plan_hogar": "¿Qué servicio utiliza más en el hogar y qué le gustaría mejorar?",
    "upgrade": "¿Ha identificado alguna limitación de capacidad o velocidad en su servicio actual?",
    "equipo": "¿Su equipo actual limita la experiencia que espera del servicio?",
    "paquete_adicional": "¿Le interesaría complementar sus servicios con una funcionalidad adicional?",
    "movistar_total": "¿Le interesaría integrar sus servicios móvil y hogar en una sola propuesta?",
}


def build_sales_playbook(
    row: Mapping[str, Any],
    strategy: CommercialStrategy,
    explanation: Explanation,
    customer_benefit: str,
    objection: Objection,
    rebate: Rebate,
    post_rejection: PostRejectionAction,
    version: str,
    reason_codes: list[str],
    urgency: str,
    variant: str = "benefit_first",
) -> SalesPlaybook:
    """Traduce la decisión analítica a una conversación comercial verificable."""
    channel = str(row["canal"])
    channel_style, opening = CHANNEL_GUIDANCE.get(channel, CHANNEL_GUIDANCE["Tienda"])
    discovery = STAGE_QUESTIONS.get(
        strategy.current_stage,
        TYPE_QUESTIONS.get(str(row["tipo_oferta"]), "¿Qué necesidad le gustaría resolver con su servicio?"),
    )
    reasons = [reason.rstrip(".") for reason in explanation.positive[:2]]
    main_argument = ". Además, ".join(
        [reasons[0], reasons[1][0].lower() + reasons[1][1:]] if len(reasons) > 1 else reasons
    ) + "."

    if urgency == "alta":
        close = "Si la propuesta encaja con lo que necesita, podemos revisar ahora las condiciones para continuar."
    elif channel == "Digital":
        close = "¿Desea que le enviemos el detalle verificable para revisarlo antes de decidir?"
    else:
        close = "¿Desea que revisemos juntos el precio y las condiciones antes de tomar una decisión?"

    do_not_say = [
        "No mencionar scores, probabilidades ni que el cliente fue perfilado por un modelo.",
        "No utilizar edad, región, mora o reclamos como argumento comercial.",
        "No prometer descuentos, ahorro o condiciones que no estén en el catálogo vigente.",
        "No insistir después de un rechazo; respetar el cooldown y la fecha de recontacto.",
    ]
    if float(row.get("affordability_fit", 1.0)) < 0.85:
        do_not_say.append("No afirmar que el precio es económico o que está dentro del presupuesto del cliente.")
    if float(row.get("ahorro_pct", 0.0) or 0.0) <= 0:
        do_not_say.append("No comunicar un porcentaje de ahorro para esta oferta.")

    evidence_codes = list(dict.fromkeys([
        *reason_codes,
        f"OBJECTIVE_{strategy.objective.upper()}",
        f"OBJECTION_{objection.motivo.upper()}",
    ]))
    middle = [customer_benefit, main_argument] if variant == "benefit_first" else [main_argument, customer_benefit]
    suggested_script = " ".join([opening, discovery, *middle, close])
    return SalesPlaybook(
        version=version,
        objective=strategy.objective,
        channel_style=channel_style,
        opening=opening,
        discovery_question=discovery,
        main_argument=main_argument,
        verified_benefit=customer_benefit,
        close=close,
        likely_objection=objection.motivo,
        objection_response=rebate.speech,
        post_rejection_guidance=post_rejection.speech,
        suggested_script=suggested_script,
        evidence_codes=evidence_codes,
        do_not_say=do_not_say,
    )
