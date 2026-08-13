from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .features import _bundle_services, mt_stage
from .persistence import DecisionStore
from .schemas import CustomerEventRequest, CustomerState, CustomerStateEvent, StateFieldOrigin


USAGE_FIELDS = {
    "consumo_datos_gb_prom", "consumo_voz_min_prom", "consumo_sms_prom", "uso_app_movistar_prom",
    "n_actividad_canal", "n_reclamos",
}
BILLING_FIELDS = {
    "monto_facturado_prom", "monto_facturado_prom_6m", "dias_mora_prom", "meses_moroso",
}
PROTECTED_FIELDS = {"cliente_id", "active_offer_ids", "state_version", "applied_event_ids"}


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def _utc(value: datetime | str | pd.Timestamp | None = None) -> datetime:
    stamp = pd.Timestamp(value if value is not None else datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.to_pydatetime()


class CustomerStateService:
    """Reconstruye el estado operacional sin mutar el perfil maestro."""

    def __init__(
        self,
        customers: pd.DataFrame,
        catalog: pd.DataFrame,
        store: DecisionStore,
        external_activation_sources: set[str] | None = None,
    ):
        self.customers = customers.set_index("cliente_id", drop=False)
        self.catalog = catalog.set_index("oferta_id", drop=False)
        self.store = store
        self.external_activation_sources = external_activation_sources or {
            "billing", "crm", "provisioning", "order_management", "backoffice", "demo",
        }

    def _base(self, cliente_id: str) -> tuple[dict[str, Any], set[str], dict[str, StateFieldOrigin]]:
        if cliente_id not in self.customers.index:
            raise KeyError(cliente_id)
        attrs = {key: _plain(value) for key, value in self.customers.loc[cliente_id].to_dict().items()}
        active = {
            str(value) for value in (attrs.get("plan_actual_id"), attrs.get("oferta_hogar_id"))
            if value not in {None, "unknown", "sin_hogar", "nan"}
        }
        origins = {key: StateFieldOrigin(source="master_profile") for key in attrs}
        return attrs, active, origins

    @staticmethod
    def _derive_mt(attrs: dict[str, Any], override: dict[str, Any] | None) -> None:
        if bool(attrs.get("es_movistar_total")):
            attrs["elegible_mt"] = False
        else:
            derived = bool(
                attrs.get("tiene_movil") and attrs.get("tipo_cliente") == "postpago"
                and attrs.get("tiene_internet_hogar")
            )
            attrs["elegible_mt"] = bool(override["enabled"]) if override is not None else derived

    def get_state(self, cliente_id: str, as_of: datetime | str | None = None) -> CustomerState:
        is_current = as_of is None
        cutoff = _utc(as_of)
        attrs, active, origins = self._base(cliente_id)
        override: dict[str, Any] | None = None
        events = self.store.list_customer_events(cliente_id, cutoff.isoformat())
        for event in events:
            for field, value in event["changes_after"].items():
                if field == "_active_offer_ids":
                    active = set(value or [])
                elif field == "_mt_override":
                    override = value
                elif field == "_mt_stage":
                    continue
                else:
                    attrs[field] = value
                    origins[field] = StateFieldOrigin(
                        source=event["source"], event_id=event["event_id"],
                        effective_at=_utc(event["effective_at"]),
                    )
            self._derive_mt(attrs, override)
        version = (
            self.store.customer_state_version(cliente_id) if is_current
            else max((int(event["state_version_after"]) for event in events), default=0)
        )
        last = max((_utc(event["recorded_at"]) for event in events), default=None)
        return CustomerState(
            cliente_id=cliente_id, as_of=cutoff, state_version=version,
            mt_stage=mt_stage(attrs), active_offer_ids=sorted(active),
            applied_event_ids=[event["event_id"] for event in events], last_updated_at=last,
            field_origins=origins, mt_override=override, attributes=attrs,
        )

    def _product_changes(
        self, state: CustomerState, event_type: str, oferta_id: str,
    ) -> dict[str, Any]:
        if oferta_id not in self.catalog.index:
            raise KeyError(oferta_id)
        offer = self.catalog.loc[oferta_id]
        kind = str(offer["tipo_oferta"])
        attrs = dict(state.attributes)
        active = set(state.active_offer_ids)
        if event_type == "product_activated":
            if oferta_id in active:
                raise ValueError("La oferta ya esta activa")
            if kind == "plan_movil":
                old = attrs.get("plan_actual_id")
                if old:
                    active.discard(str(old))
                attrs.update(tiene_movil=True, tipo_cliente="postpago", plan_actual_id=oferta_id)
            elif kind == "plan_hogar":
                old = attrs.get("oferta_hogar_id")
                if old:
                    active.discard(str(old))
                services = _bundle_services(offer.get("descripcion_bundle"))
                attrs.update(
                    tiene_hogar=True, oferta_hogar_id=oferta_id,
                    tiene_internet_hogar="internet" in services,
                )
            elif kind == "movistar_total":
                attrs.update(
                    tiene_movil=True, tiene_hogar=True, tiene_internet_hogar=True,
                    tipo_cliente="postpago", es_movistar_total=True,
                )
            active.add(oferta_id)
        else:
            if oferta_id not in active:
                raise ValueError("La oferta indicada no esta activa")
            active.remove(oferta_id)
            if kind == "plan_movil" and attrs.get("plan_actual_id") == oferta_id:
                attrs.update(tiene_movil=False, tipo_cliente="sin_linea_movil", plan_actual_id="unknown")
                attrs["es_movistar_total"] = False
            elif kind == "plan_hogar" and attrs.get("oferta_hogar_id") == oferta_id:
                attrs.update(tiene_hogar=False, tiene_internet_hogar=False, oferta_hogar_id="sin_hogar")
                attrs["es_movistar_total"] = False
            elif kind == "movistar_total":
                attrs["es_movistar_total"] = False
        attrs["_active_offer_ids"] = sorted(active)
        return attrs

    def _event_patch(self, request: CustomerEventRequest, before: CustomerState) -> dict[str, Any]:
        if request.correction_of_event_id:
            original = self.store.get_customer_event(request.correction_of_event_id)
            if original["cliente_id"] != request.cliente_id:
                raise ValueError("El evento corregido pertenece a otro cliente")
            if request.changes.get("restore_original") is True:
                return dict(original["changes_before"])
        if request.event_type in {"product_activated", "product_cancelled"}:
            candidate = self._product_changes(before, request.event_type, str(request.oferta_id))
            keys = set(candidate) | set(before.attributes)
            patch = {key: candidate.get(key) for key in keys if candidate.get(key) != before.attributes.get(key)}
            patch["_active_offer_ids"] = candidate["_active_offer_ids"]
            return patch
        changes = dict(request.changes)
        if request.event_type == "usage_updated":
            invalid = set(changes) - USAGE_FIELDS
            if invalid:
                raise ValueError(f"Campos de uso no permitidos: {sorted(invalid)}")
        elif request.event_type == "billing_updated":
            invalid = set(changes) - BILLING_FIELDS
            if invalid:
                raise ValueError(f"Campos de facturacion no permitidos: {sorted(invalid)}")
        elif request.event_type == "preferred_channel_changed":
            channel = changes.get("canal_mas_usado", changes.get("channel"))
            if channel not in {"Digital", "Tienda", "Call In", "Call Out"}:
                raise ValueError("Canal preferido invalido")
            changes = {"canal_mas_usado": channel}
        elif request.event_type == "mt_eligibility_overridden":
            enabled = changes.get("enabled", changes.get("elegible_mt"))
            if enabled is None:
                changes = {"_mt_override": None}
            elif not isinstance(enabled, bool):
                raise ValueError("El override MT debe ser booleano o nulo")
            else:
                changes = {"_mt_override": {
                    "enabled": enabled, "source": request.source,
                    "evidence_type": request.evidence_type,
                    "evidence_reference": request.evidence_reference,
                }}
        elif request.event_type == "customer_attribute_corrected":
            invalid = set(changes) & PROTECTED_FIELDS
            if invalid:
                raise ValueError(f"Campos protegidos: {sorted(invalid)}")
        return changes

    def register_event(
        self, request: CustomerEventRequest,
    ) -> tuple[CustomerStateEvent, CustomerState, CustomerState, dict[str, dict[str, Any]], bool]:
        # Un replay devuelve exactamente el evento ya aceptado y nunca exige la version vieja otra vez.
        replay = self.store.get_customer_event_by_idempotency(request.idempotency_key)
        if replay is not None:
            if (
                replay["cliente_id"] != request.cliente_id
                or replay["event_type"] != request.event_type
                or replay.get("oferta_id") != request.oferta_id
                or replay.get("decision_id") != request.decision_id
                or replay.get("source") != request.source
            ):
                raise ValueError("idempotency_key reutilizada con otro evento")
            previous = self.get_state(request.cliente_id, pd.Timestamp(replay["effective_at"]) - pd.Timedelta(microseconds=1))
            current = self.get_state(request.cliente_id)
            changed = {}
            for key, value in replay["changes_after"].items():
                if key == "_mt_stage":
                    continue
                public_key = "active_offer_ids" if key == "_active_offer_ids" else key
                changed[public_key] = {
                    "before": replay["changes_before"].get(key), "after": value,
                }
            return CustomerStateEvent(**replay), previous, current, changed, True

        current_version = self.store.customer_state_version(request.cliente_id)
        if current_version != request.expected_state_version:
            from .persistence import StateVersionConflict
            raise StateVersionConflict(
                f"Conflicto de version: esperada {request.expected_state_version}, vigente {current_version}"
            )
        if request.cliente_id not in self.customers.index:
            raise KeyError(request.cliente_id)
        if request.event_type == "product_activated":
            if request.decision_id:
                self.store.validate_activation_decision(
                    request.decision_id, str(request.oferta_id), request.cliente_id,
                )
            elif request.source not in self.external_activation_sources:
                raise ValueError("La fuente no esta autorizada para activaciones externas")
        if request.correction_of_event_id:
            self.store.get_customer_event(request.correction_of_event_id)

        effective = _utc(request.effective_at)
        # El nuevo evento se registra después de los ya existentes que tengan el
        # mismo effective_at. Usar un microsegundo anterior los omitía y hacía que
        # una cancelación inmediata no viera la activación previa en sistemas con
        # reloj de baja resolución.
        before_effective = self.get_state(request.cliente_id, effective)
        previous_current = self.get_state(request.cliente_id)
        patch = self._event_patch(request, before_effective)
        projected_attrs = dict(before_effective.attributes)
        projected_override = before_effective.mt_override
        for field, value in patch.items():
            if field == "_mt_override":
                projected_override = value
            elif field != "_active_offer_ids":
                projected_attrs[field] = value
        self._derive_mt(projected_attrs, projected_override)
        if projected_attrs.get("elegible_mt") != before_effective.attributes.get("elegible_mt"):
            patch["elegible_mt"] = projected_attrs.get("elegible_mt")
        patch["_mt_stage"] = mt_stage(projected_attrs)
        before_values: dict[str, Any] = {}
        for field in patch:
            if field == "_active_offer_ids":
                before_values[field] = before_effective.active_offer_ids
            elif field == "_mt_override":
                before_values[field] = before_effective.mt_override
            elif field == "_mt_stage":
                before_values[field] = before_effective.mt_stage
            else:
                before_values[field] = before_effective.attributes.get(field)
        now = _utc()
        raw = {
            "event_id": str(uuid.uuid4()), "cliente_id": request.cliente_id,
            "event_type": request.event_type, "effective_at": effective.isoformat(),
            "recorded_at": now.isoformat(), "source": request.source,
            "decision_id": request.decision_id, "oferta_id": request.oferta_id,
            "changes_before": before_values, "changes_after": patch,
            "evidence_type": request.evidence_type, "evidence_reference": request.evidence_reference,
            "idempotency_key": request.idempotency_key,
            "correction_of_event_id": request.correction_of_event_id,
        }
        saved, replayed = self.store.save_customer_state_event(raw, request.expected_state_version)
        new_current = self.get_state(request.cliente_id)
        before_flat = {**previous_current.attributes, "active_offer_ids": previous_current.active_offer_ids}
        after_flat = {**new_current.attributes, "active_offer_ids": new_current.active_offer_ids}
        changed = {
            field: {"before": before_flat.get(field), "after": after_flat.get(field)}
            for field in set(before_flat) | set(after_flat)
            if before_flat.get(field) != after_flat.get(field)
        }
        return CustomerStateEvent(**saved), previous_current, new_current, changed, replayed
