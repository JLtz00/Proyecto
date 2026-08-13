from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from .schemas import PlaybookRenderResponse


def _allowed_payload(decision: dict[str, Any], tone: str) -> dict[str, Any]:
    recommendation = decision["recommendation"]
    return {
        "tone": tone,
        "offer": {
            "id": recommendation["oferta_id"], "name": recommendation["nombre_oferta"],
            "price": recommendation["precio_mensual"], "channel": recommendation["canal"],
            "verified_benefit": recommendation["beneficio_cliente"],
        },
        "commercial_objective": decision["commercial_strategy"]["objective"],
        "mt_stage": decision["commercial_strategy"]["current_stage"],
        "reason_codes": recommendation["reason_codes"],
        "likely_objection": decision["rejection_prediction"][0]["motivo"],
        "deterministic_playbook": decision["sales_playbook"],
    }


def _validate_script(script: str, allowed: dict[str, Any], max_chars: int) -> str | None:
    if not script or len(script) > max_chars:
        return "invalid_length"
    lowered = script.lower()
    forbidden = ["probabilidad", "score", "mora", "moroso", "reclamo", "edad", "región", "region"]
    if any(term in lowered for term in forbidden):
        return "forbidden_content"
    input_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", json.dumps(allowed, ensure_ascii=False)))
    output_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", script))
    if not output_numbers.issubset(input_numbers):
        return "invented_number"
    return None


def render_playbook(decision: dict[str, Any], tone: str, config: dict, store) -> PlaybookRenderResponse:
    started = time.perf_counter()
    llm = config["llm"]
    fallback_script = decision["sales_playbook"]["suggested_script"]
    provider = str(llm["provider"])
    status, reason, validation, rendered = "fallback", None, "not_called", fallback_script
    if not bool(llm.get("enabled", False)):
        reason = "provider_disabled"
    else:
        api_key = os.getenv(str(llm["api_key_env"]))
        if not api_key:
            reason = "missing_api_key"
        else:
            allowed = _allowed_payload(decision, tone)
            try:
                response = httpx.post(
                    f"{str(llm['base_url']).rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": llm["model"], "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": "Reformula el playbook como un speech corto. Devuelve JSON con offer_id, offer_name, price, channel y script. Copia exactamente los cuatro campos comerciales recibidos. Usa solo los datos dados; no inventes números, beneficios, descuentos o condiciones; no menciones modelos, scores, probabilidades ni atributos sensibles."},
                            {"role": "user", "content": json.dumps(allowed, ensure_ascii=False)},
                        ],
                    },
                    timeout=float(llm["timeout_seconds"]),
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                output = json.loads(content)
                offer = allowed["offer"]
                locked_valid = (
                    output.get("offer_id") == offer["id"]
                    and output.get("offer_name") == offer["name"]
                    and float(output.get("price")) == float(offer["price"])
                    and output.get("channel") == offer["channel"]
                )
                script = str(output["script"])
                validation_error = (
                    None if locked_valid else "locked_field_modified"
                ) or _validate_script(script, allowed, int(llm["max_output_characters"]))
                if validation_error:
                    reason, validation = validation_error, "rejected"
                else:
                    status, validation, rendered = "generated", "passed", script
            except Exception as exc:
                reason, validation = f"provider_error:{type(exc).__name__}", "failed"
    latency_ms = (time.perf_counter() - started) * 1000
    event = {
        "decision_id": decision["decision_id"], "provider": provider, "model": llm.get("model"),
        "prompt_version": llm["prompt_version"], "render_status": status,
        "validation_status": validation, "latency_ms": latency_ms, "fallback_reason": reason,
    }
    if store is not None:
        store.save_llm_render_event(event)
    return PlaybookRenderResponse(
        decision_id=decision["decision_id"], render_status=status, provider=provider,
        model=llm.get("model"), rendered_script=rendered, fallback_reason=reason,
        latency_ms=latency_ms,
    )
