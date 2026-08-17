from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAGE_LABELS = {
    "falta_internet_hogar": "Falta internet hogar",
    "falta_movil_postpago": "Falta móvil postpago",
    "elegible_mt": "Elegible para Movistar Total",
    "ya_es_mt": "Cliente Movistar Total",
    "no_elegible_actual": "Sin ruta MT inmediata",
}

OBJECTIVE_LABELS = {
    "convertir_a_mt": "Ayudarle a completar Movistar Total",
    "completar_hogar_para_mt": "Completar sus servicios del hogar",
    "completar_movil_para_mt": "Completar su servicio móvil",
    "profundizar_relacion_mt": "Fortalecer sus servicios actuales",
    "mejor_oferta_compatible": "Presentar la opción que mejor encaja",
}

REJECTION_LABELS = {
    "precio": "Precio",
    "no_necesita": "No lo necesita",
    "ya_tiene_similar": "Ya tiene algo similar",
    "mal_momento": "No es un buen momento",
    "no_confia": "Necesita más confianza",
    "otro": "Otro motivo",
}

EVENT_LABELS = {
    "product_activated": "Producto activado",
    "product_cancelled": "Producto cancelado",
    "usage_updated": "Consumo actualizado",
    "billing_updated": "Facturación actualizada",
    "preferred_channel_changed": "Canal preferido actualizado",
    "mt_eligibility_overridden": "Elegibilidad MT ajustada",
    "customer_attribute_corrected": "Dato del cliente corregido",
}


class AdvisorApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AdvisorApi:
    def __init__(self, base_url: str, timeout: float = 25.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        import httpx

        try:
            response = httpx.request(
                method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except (ValueError, AttributeError):
                detail = exc.response.text
            if isinstance(detail, dict):
                detail = "; ".join(f"{key}: {value}" for key, value in detail.items())
            raise AdvisorApiError(str(detail), exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise AdvisorApiError(
                "No se pudo conectar con el motor NBO. Verifica que la API esté activa.",
            ) from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def recommend(self, cliente_id: str) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/nbo/recommend", json={"cliente_id": cliente_id},
        )

    def customer_state(self, cliente_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/nbo/customer-state/{cliente_id}")

    def customer_events(self, cliente_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/nbo/customer-state/{cliente_id}/events")

    def save_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/nbo/feedback", json=payload)

    def save_funnel_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/nbo/events", json=payload)

    def activate_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/nbo/customer-events", json=payload)

    def metrics(self, source: str = "operational") -> dict[str, Any]:
        return self._request("GET", "/api/v1/nbo/executive-report", params={"source": source})

    def demo_journey(self, cliente_id: str = "CLI000001", motivo: str = "precio") -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/nbo/demo/journey",
            json={"cliente_id": cliente_id, "motivo_rechazo": motivo},
        )

    def economics(self, cliente_id: str, assumptions: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/nbo/economics/simulate",
            json={"cliente_id": cliente_id, "assumptions": assumptions},
        )


def percentage(value: float | int | None) -> str:
    return f"{float(value or 0):.0%}"


def money(value: float | int | None) -> str:
    return f"S/ {float(value or 0):,.2f}"


def label_stage(value: str) -> str:
    return STAGE_LABELS.get(value, value.replace("_", " ").capitalize())


def label_objective(value: str) -> str:
    return OBJECTIVE_LABELS.get(value, value.replace("_", " ").capitalize())


def label_rejection(value: str) -> str:
    return REJECTION_LABELS.get(value, value.replace("_", " ").capitalize())


def label_event(value: str) -> str:
    return EVENT_LABELS.get(value, value.replace("_", " ").capitalize())


def confidence_summary(confidence: dict[str, Any]) -> str:
    level = str(confidence.get("level", "bajo")).capitalize()
    support = int(confidence.get("relevant_support", 0) or 0)
    return f"Confianza {level} · {support} observaciones relevantes"


def advisor_level(value: float | int | None) -> str:
    probability = float(value or 0)
    if probability >= 0.65:
        return "Alta"
    if probability >= 0.30:
        return "Media"
    return "Baja"


def advisor_level_key(value: float | int | None) -> str:
    return advisor_level(value).lower()


def advisor_fit_level(value: float | int | None) -> str:
    score = float(value or 0)
    if score >= 0.50:
        return "Muy buen ajuste"
    if score >= 0.40:
        return "Buen ajuste"
    return "Ajuste moderado"


def advisor_fit_level_key(value: float | int | None) -> str:
    score = float(value or 0)
    if score >= 0.50:
        return "alta"
    if score >= 0.40:
        return "media"
    return "baja"


def advisor_confidence(confidence: dict[str, Any]) -> str:
    labels = {
        "alto": "Buena información para orientar la conversación",
        "medio": "Información suficiente para orientar la conversación",
        "bajo": "Pocos datos: confirma la necesidad con el cliente",
    }
    return labels.get(
        str(confidence.get("level", "bajo")),
        "Pocos datos: confirma la necesidad con el cliente",
    )


def advisor_next_step(strategy: dict[str, Any], offer_name: str) -> str:
    objective = str(strategy.get("objective", ""))
    messages = {
        "convertir_a_mt": f"Presenta {offer_name} y explica cómo reúne sus servicios.",
        "completar_hogar_para_mt": f"Presenta {offer_name} como el servicio del hogar que le falta.",
        "completar_movil_para_mt": f"Presenta {offer_name} como el servicio móvil que le falta.",
        "profundizar_relacion_mt": f"Presenta {offer_name} como una mejora de sus servicios actuales.",
        "mejor_oferta_compatible": f"Presenta {offer_name} y confirma si responde a su necesidad.",
    }
    return messages.get(objective, f"Presenta {offer_name} y confirma si le resulta útil.")


def label_moment(value: str) -> str:
    labels = {
        "proxima_interaccion_digital": "En la próxima interacción digital",
        "proximo_contacto_asesor": "En el próximo contacto",
        "proxima_oportunidad_recomendada": "En la fecha recomendada",
        "recontactar_luego": "Esperar antes de volver a contactar",
    }
    return labels.get(value, value.replace("_", " ").capitalize())


def label_urgency(value: str) -> str:
    return {
        "alta": "Atender ahora",
        "media": "Atender pronto",
        "baja": "Sin urgencia",
    }.get(value, value.replace("_", " ").capitalize())


def service_summary(customer: dict[str, Any], state: dict[str, Any] | None) -> list[str]:
    attributes = (state or {}).get("attributes", {})
    source = {**customer, **attributes}
    services = []
    if source.get("tiene_movil"):
        services.append("Móvil postpago" if source.get("tipo_cliente") == "postpago" else "Móvil")
    if source.get("tiene_internet_hogar"):
        services.append("Internet hogar")
    elif source.get("tiene_hogar"):
        services.append("Servicio hogar")
    if source.get("es_movistar_total"):
        services.append("Movistar Total")
    return services or ["Sin servicios activos identificados"]


def alternative_rows(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Oferta": item["nombre_oferta"],
            "Canal": item["canal"],
            "Precio": money(item["precio_mensual"]),
            "Oportunidad": f"{advisor_level(item['probabilidad_venta'])} ({percentage(item['probabilidad_venta'])})",
            "Motivo principal": (item.get("explanation", {}).get("positive") or ["Oferta compatible"])[0],
        }
        for item in alternatives
    ]


@dataclass(frozen=True)
class AdvisorContext:
    result: dict[str, Any]
    state: dict[str, Any]
    events: list[dict[str, Any]]

    @property
    def cliente_id(self) -> str:
        return str(self.result["cliente"]["cliente_id"])

    @property
    def decision_id(self) -> str:
        return str(self.result["decision_id"])

    @property
    def offer_id(self) -> str:
        return str(self.result["recommendation"]["oferta_id"])

    @property
    def state_version(self) -> int:
        return int(self.state.get("state_version", self.result.get("state_version", 0)))
