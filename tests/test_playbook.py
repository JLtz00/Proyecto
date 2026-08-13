from __future__ import annotations

from nbo.playbook import build_sales_playbook
from nbo.schemas import CommercialStrategy, Explanation, Objection, PostRejectionAction, Rebate


def test_playbook_adapts_to_channel_and_uses_only_verified_arguments():
    strategy = CommercialStrategy(
        objective="convertir_a_mt", current_stage="elegible_mt", mt_priority_applied=True,
        next_step="Presentar MT.", rationale="Cliente elegible.",
    )
    explanation = Explanation(
        positive=["Es elegible para Movistar Total", "El canal coincide con su interacción habitual"],
        negative=[],
    )
    objection = Objection(motivo="precio", probability=0.35)
    rebate = Rebate(
        enabled=True, strategy="tier_inferior", speech="Compare el valor y revise un tier inferior.",
        alternative_offer_id="OF020",
    )
    post_rejection = PostRejectionAction(
        source="predicted", trigger_reason="precio", action="proponer_tier_inferior",
        objective="Mantener la ruta MT.", wait_days=15, recontact_from="2026-08-28",
        channel="Digital", alternative_offer_id="OF020", alternative_offer_name="MT Básico",
        preserves_mt_path=True, speech="Recontactar desde 2026-08-28.",
        reason_codes=["COOLDOWN_14D", "PRESERVE_MT_PATH"],
    )
    expected_styles = {
        "Digital": "mensaje_breve",
        "Tienda": "conversacion_consultiva",
        "Call In": "respuesta_contextual",
        "Call Out": "llamada_con_permiso",
    }
    for channel, expected_style in expected_styles.items():
        playbook = build_sales_playbook(
            row={
                "canal": channel, "tipo_oferta": "movistar_total",
                "affordability_fit": 0.75, "ahorro_pct": 20,
            },
            strategy=strategy, explanation=explanation,
            customer_benefit="Integra móvil y hogar con condiciones del catálogo.",
            objection=objection, rebate=rebate, post_rejection=post_rejection,
            version="playbook_v1", reason_codes=["MT_PATH", "CHANNEL_AFFINITY"],
            urgency="media",
        )
        assert playbook.channel_style == expected_style
        assert playbook.objective == "convertir_a_mt"
        assert playbook.likely_objection == "precio"
        assert "0.35" not in playbook.suggested_script
        assert "MT_PATH" in playbook.evidence_codes
        assert any("presupuesto" in warning for warning in playbook.do_not_say)
