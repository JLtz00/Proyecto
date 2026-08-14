from __future__ import annotations

import json
import hashlib
import logging
import time
import uuid
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .data import clean_semantic_nulls, load_raw
from .enrichment import compute_uplift_mt, load_enrichment, population_uplift_mt
from .features import add_pair_features, attach_inference_history, mt_stage, summarize_history
from .models import load_artifact
from .persistence import DecisionStore
from .playbook import build_sales_playbook
from .rules import (
    CHANNELS, best_channel_then_rank, eligibility_mask, eligibility_mask_frame,
    eligibility_reasons_frame, generate_candidates, score_candidate_frame, score_candidates,
)
from .schemas import (
    ChurnAssessment, CommercialStrategy, CustomerSummary, DecisionTrace,
    EvidenceConfidence, Explanation, NBOResult, Objection, PersonaAssignment,
    PlaybookExperiment, PostRejectionAction, Rebate, Recommendation, ScoreBreakdown, Timing,
)
from .validation import validate_data
from .state import CustomerStateService


LOGGER = logging.getLogger("nbo")


class ArtifactUnavailable(RuntimeError):
    pass


FEATURE_LABELS = {
    "hist_accept_rate_channel": ("El historial muestra afinidad con el canal recomendado", "La afinidad histórica con este canal es limitada"),
    "match_canal_preferido": ("El canal coincide con su forma habitual de interacción", "El canal difiere de su interacción habitual"),
    "oferta_es_mt": ("La oferta consolida servicios en Movistar Total", "La oferta convergente no aporta suficiente ajuste adicional"),
    "ratio_precio_facturacion": ("El precio guarda relación con su facturación habitual", "El precio se aleja de su facturación habitual"),
    "gap_gb": ("La capacidad de datos se ajusta a su consumo", "La capacidad de datos tiene menor ajuste a su consumo"),
    "elegible_mt": ("Cumple las condiciones disponibles para Movistar Total", "No cumple aún todas las condiciones para Movistar Total"),
    "friccion_cliente": ("Presenta baja fricción comercial observada", "Hay señales de fricción comercial que aconsejan prudencia"),
    "sensibilidad_precio": ("No muestra una sensibilidad marcada al precio", "El historial muestra sensibilidad al precio"),
}


class NBOEngine:
    def __init__(self, config_path: str | None = None, persist: bool = True):
        self.config = load_config(config_path)
        customers, catalog, history = load_raw(self.config["project"]["data_dir"])
        report = validate_data(customers, catalog, history, self.config["validation"])
        report.raise_for_errors()
        self.customers, self.catalog, self.history = clean_semantic_nulls(customers, catalog, history)
        self.customer_index = self.customers.set_index("cliente_id", drop=False)
        artifact_root = Path(self.config["project"]["artifact_dir"])
        manifest_path = artifact_root / "current.json"
        if not manifest_path.exists():
            raise ArtifactUnavailable("No hay artefactos entrenados. Ejecute `python -m nbo.training`.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_dir = Path(manifest["path"])
        if not artifact_dir.is_absolute():
            artifact_dir = (artifact_root / artifact_dir).resolve()
        required = [artifact_dir / name for name in ("contact.joblib", "acceptance.joblib", "rejection.joblib", "metadata.json")]
        if any(not path.exists() for path in required):
            raise ArtifactUnavailable(f"Artefactos incompletos en {artifact_dir}")
        self.contact_model = load_artifact(artifact_dir / "contact.joblib")
        self.acceptance_model = load_artifact(artifact_dir / "acceptance.joblib")
        self.rejection_model = load_artifact(artifact_dir / "rejection.joblib")
        self.metadata = json.loads((artifact_dir / "metadata.json").read_text(encoding="utf-8"))
        self.artifact_dir = artifact_dir
        artifact_versions = self.metadata["versions"]
        self.versions = {
            **artifact_versions,
            "rules_version": self.config["project"]["rules_version"],
            "catalog_version": self.config["project"]["catalog_version"],
            "playbook_version": self.config["project"].get("playbook_version", "playbook_v1"),
        }
        self.smoothing_alpha = float(self.metadata.get("selected_smoothing_alpha", self.config["features"]["smoothing_alpha"]))
        self._summary_cache: dict[str, object] = {}
        self._timing_cache: dict[str, pd.DataFrame] = {}
        ranking_path = artifact_dir / "ranking_weights.json"
        self.scoring = self.config["scoring"] if not ranking_path.exists() else json.loads(ranking_path.read_text(encoding="utf-8"))["weights"]
        self.enrichment = load_enrichment(artifact_dir)
        self._population_uplift_mt_cached: float | None = None
        self.store = DecisionStore(self.config["project"]["database_path"]) if persist else None
        self.state_service = CustomerStateService(
            self.customers, self.catalog, self.store,
            set(self.config.get("operational_state", {}).get("external_activation_sources", [])) or None,
        ) if self.store else None
        if self.store:
            self.store.register_version(self.versions, self.metadata)

    def _explanation(self, customer: pd.Series, row: pd.Series, contribution: dict[str, float]) -> Explanation:
        positive: list[str] = []
        negative: list[str] = []
        if bool(customer["elegible_mt"]) and bool(row["oferta_es_movistar_total"]):
            positive.append("Es elegible para Movistar Total y la oferta consolida móvil e internet hogar")
        elif mt_stage(customer) == "falta_internet_hogar" and row["tipo_oferta"] == "plan_hogar":
            positive.append("Añade internet hogar y completa el siguiente paso hacia Movistar Total")
        elif mt_stage(customer) == "falta_movil_postpago" and row["tipo_oferta"] == "plan_movil":
            positive.append("Añade una línea móvil y completa el siguiente paso hacia Movistar Total")
        if row["match_canal_preferido"]:
            positive.append(f"{row['canal']} coincide con su canal más usado")
        if row["capacity_fit"] >= 0.8:
            positive.append("La capacidad de la oferta cubre bien su patrón de consumo")
        if row["affordability_fit"] >= 0.85:
            positive.append("El precio es consistente con su facturación actual")
        if row["affordability_fit"] < 0.65:
            negative.append("El precio supera de forma relevante su facturación actual")
        if row["friccion_cliente"] > 0.55:
            negative.append("La mora, reclamos o fatiga aconsejan una aproximación prudente")
        for feature, value in sorted(contribution.items(), key=lambda item: abs(item[1]), reverse=True):
            labels = FEATURE_LABELS.get(feature)
            target = positive if value > 0 else negative
            label = labels[0 if value > 0 else 1] if labels else None
            if label and label not in positive and label not in negative:
                target.append(label)
            if len(positive) >= 3 and len(negative) >= 2:
                break
        return Explanation(positive=positive[:3] or ["La combinación de perfil, oferta y canal obtiene el mejor ajuste disponible"], negative=negative[:2])

    def _timing_history(self, as_of: pd.Timestamp) -> pd.DataFrame:
        """Tasas leakage-safe por día, segmento y canal para oportunidad comercial."""
        cutoff = pd.Timestamp(as_of).tz_localize(None) if pd.Timestamp(as_of).tzinfo else pd.Timestamp(as_of)
        key = cutoff.isoformat()
        if key in self._timing_cache:
            return self._timing_cache[key]
        events = self.history.loc[self.history["fecha"].lt(cutoff)].copy()
        events["weekday"] = events["fecha"].dt.dayofweek
        events["contact"] = events["contactabilidad"].eq("contactado").astype(int)
        if "tipo_cliente" not in events:
            events["tipo_cliente"] = events["cliente_id"].map(
                self.customer_index["tipo_cliente"]
            )
        channel = events.groupby("canal", observed=True)["contact"].agg(["sum", "count"])
        channel["base_rate"] = channel["sum"] / channel["count"].clip(lower=1)
        grouped = events.groupby(
            ["tipo_cliente", "canal", "weekday"], observed=True
        )["contact"].agg(["sum", "count"]).reset_index()
        grouped = grouped.join(channel[["base_rate"]], on="canal")
        alpha = float(self.config.get("timing", {}).get("smoothing_alpha", 100.0))
        grouped["rate"] = (
            grouped["sum"] + alpha * grouped["base_rate"]
        ) / (grouped["count"] + alpha)
        grouped["lift"] = grouped["rate"] - grouped["base_rate"]
        self._timing_cache[key] = grouped
        return grouped

    @staticmethod
    def _next_weekday(reference: pd.Timestamp, weekday: int) -> pd.Timestamp:
        delta = (weekday - reference.dayofweek) % 7
        return reference.normalize() + pd.Timedelta(days=delta)

    def _timing(self, row: pd.Series) -> Timing:
        raw_reference = row.get("_state_as_of", self.config["features"]["as_of_date"])
        reference = pd.Timestamp(raw_reference)
        if reference.tzinfo is not None:
            reference = reference.tz_localize(None)
        urgency = "alta" if row["p_venta"] >= 0.55 and row["fatiga_comercial"] < 0.5 else "media" if row["p_venta"] >= 0.30 else "baja"
        if row["penalizacion_cooldown"] > 0 or row["fatiga_comercial"] > 0.7:
            urgency = "baja"

        if row["penalizacion_cooldown"] > 0:
            rejected_at = pd.Timestamp(row["last_rejection_date"])
            recommended = max(
                reference.normalize(),
                rejected_at.normalize() + pd.Timedelta(days=int(self.config["rules"]["rejection_block_days"]) + 1),
            )
            return Timing(
                momento="recontactar_luego", urgencia=urgency,
                recommended_date=recommended.date().isoformat(),
                recommended_weekday=("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[recommended.dayofweek],
                trigger="cooldown_complete", basis="cooldown_operational",
                support=0, confidence="alta", is_model_optimized=False,
            )

        summary = self._timing_history(pd.Timestamp(self.config["features"]["as_of_date"]))
        matches = summary.loc[
            summary["tipo_cliente"].astype(str).eq(str(row["tipo_cliente"]))
            & summary["canal"].astype(str).eq(str(row["canal"]))
        ]
        timing_cfg = self.config.get("timing", {})
        minimum = int(timing_cfg.get("min_support", 50))
        min_lift = float(timing_cfg.get("min_lift", 0.02))
        useful = matches.loc[(matches["count"] >= minimum) & (matches["lift"] >= min_lift)]
        if not useful.empty:
            best = useful.sort_values(["rate", "count"], ascending=False).iloc[0]
            recommended = self._next_weekday(reference, int(best["weekday"]))
            support = int(best["count"])
            confidence = "alta" if support >= minimum * 4 else "media"
            return Timing(
                momento="proxima_oportunidad_recomendada", urgencia=urgency,
                recommended_date=recommended.date().isoformat(),
                recommended_weekday=("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[recommended.dayofweek],
                trigger="historical_contact_window", basis="segment_channel_weekday_rate",
                support=support, confidence=confidence, is_model_optimized=True,
            )

        moment = "proxima_interaccion_digital" if row["canal"] == "Digital" else "proximo_contacto_asesor"
        return Timing(
            momento=moment, urgencia=urgency, recommended_date=reference.date().isoformat(),
            recommended_weekday=("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[reference.dayofweek],
            trigger="next_interaction", basis="fallback_operational",
            support=int(matches["count"].sum()) if not matches.empty else 0,
            confidence="baja", is_model_optimized=False,
        )

    @staticmethod
    def _commercial_content(customer: pd.Series, row: pd.Series, explanation: Explanation) -> tuple[str, str, str, list[str]]:
        if bool(row["oferta_es_movistar_total"]):
            saving = int(row.get("ahorro_pct", 0))
            capacity = "datos ilimitados" if float(row["gb_incluidos"]) == 9999 else f"{int(row['gb_incluidos'])} GB"
            customer_benefit = f"Integra móvil y hogar con {capacity} y un ahorro ilustrativo de {saving}% según el catálogo del desafío."
        elif bool(row.get("oferta_es_ilimitada", 0)):
            customer_benefit = "Ofrece datos ilimitados para cubrir consumos altos sin un límite de GB del plan."
        elif row["tipo_oferta"] == "plan_hogar":
            customer_benefit = f"Incorpora {row.get('descripcion_bundle', 'servicios hogar')} por S/ {float(row['precio_mensual']):.2f} mensuales."
        else:
            customer_benefit = f"Aporta una alternativa compatible con su perfil por S/ {float(row['precio_mensual']):.2f} mensuales."
        business_benefit = (
            f"Valor de negocio proxy {float(row['valor_negocio']):.2f}, calculado con precio normalizado; "
            + ("además impulsa la ruta Movistar Total." if row["bonus_ruta_mt"] > 0 else "no representa margen ni rentabilidad real.")
        )
        speech = f"Le recomendamos {row['nombre_oferta']}. {explanation.positive[0]}. {customer_benefit}"
        codes = []
        if row["bonus_ruta_mt"] > 0:
            codes.append("MT_PATH")
        if row["match_canal_preferido"]:
            codes.append("CHANNEL_AFFINITY")
        if row["capacity_fit"] >= .8:
            codes.append("CAPACITY_FIT")
        if row["affordability_fit"] >= .85:
            codes.append("AFFORDABLE")
        if row["friccion_cliente"] > .55:
            codes.append("COMMERCIAL_FRICTION")
        return customer_benefit, business_benefit, speech, codes

    def _recommendation(self, customer: pd.Series, row: pd.Series, contribution: dict[str, float]) -> Recommendation:
        explanation = self._explanation(customer, row, contribution)
        customer_benefit, business_benefit, speech, codes = self._commercial_content(customer, row, explanation)
        return Recommendation(
            oferta_id=row["oferta_id"], nombre_oferta=row["nombre_oferta"], canal=row["canal"],
            probabilidad_contacto=float(row["p_contacto"]), probabilidad_aceptacion=float(row["p_aceptacion"]),
            probabilidad_venta=float(row["p_venta"]), score=float(row["score"]),
            es_mt=bool(row["oferta_es_movistar_total"]), precio_mensual=float(row["precio_mensual"]),
            momento=self._timing(row), explanation=explanation,
            beneficio_cliente=customer_benefit, beneficio_negocio=business_benefit,
            speech_principal=speech, reason_codes=codes,
        )

    def _objections(self, row: pd.DataFrame) -> list[Objection]:
        probability = self.rejection_model.predict_multiclass(row)[0]
        order = np.argsort(probability)[::-1][:2]
        return [Objection(motivo=str(self.rejection_model.classes[i]), probability=float(probability[i])) for i in order]

    def _confidence(self, row: pd.Series) -> EvidenceConfidence:
        client_events = int(row.get("hist_client_offer", 0) or 0)
        offer_exposures = int(row.get("hist_offer_offer", 0) or 0)
        channel_contacts = int(row.get("hist_channel_contact", 0) or 0)
        support = min(offer_exposures, channel_contacts)
        cfg = self.config["confidence"]
        cold_start = client_events == 0
        if offer_exposures >= int(cfg["high_min_offer_exposures"]) and channel_contacts >= int(cfg["high_min_channel_contacts"]):
            level = "alto"
        elif support >= int(cfg["medium_min_support"]):
            level = "medio"
        else:
            level = "bajo"
        warning = (
            "Soporte histórico limitado; la decisión depende principalmente de tasas jerárquicas, reglas y ajuste comercial."
            if level == "bajo" else
            "La confianza describe soporte histórico, no garantiza aceptación ni mide efecto causal."
        )
        return EvidenceConfidence(
            level=level, cold_start=cold_start,
            contact_source=str(getattr(self.contact_model, "model_kind", "unknown")),
            acceptance_source=str(getattr(self.acceptance_model, "model_kind", "unknown")),
            rejection_source=str(getattr(self.rejection_model, "model_kind", "unknown")),
            client_events=client_events, client_offer_exposures=offer_exposures,
            client_channel_contacts=channel_contacts, relevant_support=support, warning=warning,
        )

    @staticmethod
    def _decision_trace(candidates: pd.DataFrame, top: pd.DataFrame) -> DecisionTrace:
        first = top.iloc[0]
        breakdown = [ScoreBreakdown(
            oferta_id=str(row["oferta_id"]),
            conversion=float(row["score_conversion_component"]),
            customer_fit=float(row["score_fit_component"]),
            business_value=float(row["score_business_component"]),
            mt_priority=float(row["score_mt_component"]),
            friction=float(row["score_friction_component"]),
            cooldown=float(row["score_cooldown_component"]),
            raw_score=float(row["score_raw"]), final_score=float(row["score"]),
        ) for _, row in top.iterrows()]
        reason_columns = [column for column in candidates if column.startswith("_blocked_")]
        blocked_by_reason = {
            column.removeprefix("_blocked_"): int(first[column]) for column in reason_columns
        }
        gap = float(top.iloc[0]["score"] - top.iloc[1]["score"]) if len(top) > 1 else 0.0
        return DecisionTrace(
            total_offer_channel_pairs=int(first.get("_trace_total", len(candidates))),
            eligible_offer_channel_pairs=int(first.get("_trace_eligible", len(candidates))),
            blocked_offer_channel_pairs=int(first.get("_trace_blocked", 0)),
            blocked_by_reason=blocked_by_reason, top_score_breakdown=breakdown,
            top1_top2_score_gap=gap,
            channel_selection_reason=(
                f"{first['canal']} maximiza P(venta) para {first['oferta_id']} entre los canales elegibles."
            ),
            selection_reason="Mayor score entre ofertas elegibles después de seleccionar el mejor canal por oferta.",
        )

    def _playbook_experiment(self, cliente_id: str, decision_id: str) -> PlaybookExperiment:
        version = self.config["project"]["experiment_version"]
        seed = str(self.config["experiments"]["playbook_seed"])
        bucket = int(hashlib.sha256(f"{cliente_id}|{version}|{seed}".encode()).hexdigest()[:8], 16) % 2
        variant = "benefit_first" if bucket == 0 else "strategic_path_first"
        return PlaybookExperiment(
            experiment_version=version, exposure_id=str(uuid.uuid4()), variant=variant,
        )

    @staticmethod
    def _preserves_mt_path(customer: pd.Series, offer: pd.Series) -> bool:
        stage = mt_stage(customer)
        if stage == "elegible_mt":
            return bool(offer["oferta_es_movistar_total"])
        if stage == "falta_internet_hogar":
            return offer["tipo_oferta"] == "plan_hogar" and "internet" in str(offer.get("descripcion_bundle", "")).lower()
        if stage == "falta_movil_postpago":
            return offer["tipo_oferta"] == "plan_movil"
        return not bool(offer["oferta_es_movistar_total"])

    def _recovery_alternative(
        self, customer: pd.Series, top: pd.Series, eligible: pd.DataFrame, objection: str,
    ) -> pd.Series | None:
        """Busca una alternativa válida sin desviar al cliente de su ruta MT."""
        best_per_offer = eligible.sort_values(
            ["p_venta", "score"], ascending=False
        ).drop_duplicates("oferta_id", keep="first")
        pool = best_per_offer.loc[best_per_offer["oferta_id"].ne(top["oferta_id"])].copy()
        if pool.empty or objection not in {"precio", "no_necesita"}:
            return None
        pool = pool.loc[pool.apply(lambda row: self._preserves_mt_path(customer, row), axis=1)]
        pool = pool.loc[pool["precio_mensual"].astype(float).lt(float(top["precio_mensual"]))]
        if mt_stage(customer) not in {"elegible_mt", "falta_internet_hogar", "falta_movil_postpago"}:
            pool = pool.loc[pool["tipo_oferta"].eq(top["tipo_oferta"])]
        if pool.empty:
            return None
        if objection == "no_necesita":
            return pool.sort_values(["precio_mensual", "score"], ascending=[True, False]).iloc[0]
        return pool.sort_values(["score", "precio_mensual"], ascending=[False, True]).iloc[0]

    def _rebate(self, customer: pd.Series, objection: str, top: pd.Series, eligible: pd.DataFrame) -> Rebate:
        templates = {
            "precio": ("mostrar_ahorro_y_tier_inferior", "Explique el valor verificable de la oferta y, si el presupuesto es la barrera, presente una alternativa de menor precio."),
            "no_necesita": ("demostrar_necesidad", "Relacione la propuesta con su consumo observado, sin asumir necesidades que el cliente no haya confirmado."),
            "ya_tiene_similar": ("explicar_diferencia_incremental", "Aclare únicamente las diferencias incrementales y condiciones verificables frente al servicio actual."),
            "mal_momento": ("programar_seguimiento", "Respete el momento del cliente y acuerde una próxima ventana comercial."),
            "no_confia": ("reforzar_condiciones", "Repase precio, vigencia y condiciones usando información comprobable del catálogo."),
            "otro": ("diagnosticar", "Pregunte qué aspecto no encaja antes de formular otra propuesta."),
        }
        strategy, speech = templates.get(objection, templates["otro"])
        alternative_row = self._recovery_alternative(customer, top, eligible, objection)
        alternative = str(alternative_row["oferta_id"]) if alternative_row is not None else None
        if objection == "precio" and alternative is None:
            speech += " Si no existe un tier inferior que conserve la ruta comercial, no sustituya la oferta por una opción incompatible."
        return Rebate(enabled=True, strategy=strategy, speech=speech, alternative_offer_id=alternative)

    @staticmethod
    def _commercial_strategy(customer: pd.Series, top: pd.Series) -> CommercialStrategy:
        stage = mt_stage(customer)
        if stage == "elegible_mt" and bool(top["oferta_es_movistar_total"]):
            return CommercialStrategy(
                objective="convertir_a_mt", current_stage=stage, mt_priority_applied=True,
                next_step=f"Presentar {top['nombre_oferta']} como propuesta convergente.",
                rationale="El cliente ya cumple las condiciones disponibles para Movistar Total.",
            )
        if (
            stage == "falta_internet_hogar"
            and top["tipo_oferta"] == "plan_hogar"
            and "internet" in str(top.get("descripcion_bundle", "")).lower()
        ):
            return CommercialStrategy(
                objective="completar_hogar_para_mt", current_stage=stage, mt_priority_applied=True,
                next_step=f"Incorporar {top['nombre_oferta']} y reevaluar MT después de la activación.",
                rationale="Internet hogar es la condición pendiente identificada para avanzar hacia Movistar Total.",
            )
        if stage == "falta_movil_postpago" and top["tipo_oferta"] == "plan_movil":
            return CommercialStrategy(
                objective="completar_movil_para_mt", current_stage=stage, mt_priority_applied=True,
                next_step=f"Incorporar {top['nombre_oferta']} y reevaluar MT después de la activación.",
                rationale="La línea móvil postpago es la condición pendiente identificada para avanzar hacia Movistar Total.",
            )
        if stage == "ya_es_mt":
            return CommercialStrategy(
                objective="profundizar_relacion_mt", current_stage=stage, mt_priority_applied=False,
                next_step=f"Ofrecer {top['nombre_oferta']} sin duplicar la adquisición de Movistar Total.",
                rationale="El cliente ya posee Movistar Total; se prioriza una necesidad compatible adicional.",
            )
        return CommercialStrategy(
            objective="mejor_oferta_compatible", current_stage=stage, mt_priority_applied=False,
            next_step=f"Presentar {top['nombre_oferta']} como la mejor acción elegible disponible.",
            rationale="La combinación de propensión, ajuste y reglas comerciales obtiene el mejor score disponible.",
        )

    def _post_rejection_action(
        self,
        customer: pd.Series,
        top: pd.Series,
        eligible: pd.DataFrame,
        objection: str,
        source: str,
        base_date: pd.Timestamp,
    ) -> PostRejectionAction:
        waits = self.config["rules"].get("post_rejection_wait_days", {})
        wait_days = int(waits.get(objection, self.config["rules"]["rejection_block_days"] + 1))
        recontact_from = (pd.Timestamp(base_date).normalize() + timedelta(days=wait_days)).date().isoformat()
        alternative = self._recovery_alternative(customer, top, eligible, objection)
        channel = str(alternative["canal"]) if alternative is not None else str(top["canal"])
        if objection == "no_confia":
            channel = "Digital"

        templates = {
            "precio": (
                "proponer_tier_inferior" if alternative is not None else "revisar_presupuesto_sin_forzar",
                "Mantener la ruta MT con una opción de menor precio." if alternative is not None else "Respetar el presupuesto sin desviar al cliente hacia una oferta incompatible.",
            ),
            "no_necesita": (
                "recalibrar_necesidad",
                "Validar nuevamente consumo y necesidad antes de presentar una propuesta más simple.",
            ),
            "ya_tiene_similar": (
                "validar_servicio_actual",
                "Comparar el servicio actual y continuar solo si existe una diferencia incremental verificable.",
            ),
            "mal_momento": (
                "recontactar_en_ventana_acordada",
                "Retomar la conversación únicamente en una fecha aceptada por el cliente.",
            ),
            "no_confia": (
                "enviar_condiciones_verificables",
                "Recuperar confianza mediante condiciones oficiales y trazables antes de recontactar.",
            ),
            "otro": (
                "capturar_motivo_y_recalcular",
                "Registrar el motivo específico y recalcular la próxima mejor acción con esa evidencia.",
            ),
        }
        action, objective = templates.get(objection, templates["otro"])
        alternative_name = str(alternative["nombre_oferta"]) if alternative is not None else None
        if alternative is not None:
            stage = mt_stage(customer)
            if stage == "ya_es_mt":
                continuity = "la alternativa es compatible con sus servicios MT actuales y no duplica la adquisición"
            elif stage in {"elegible_mt", "falta_internet_hogar", "falta_movil_postpago"}:
                continuity = "la alternativa conserva el siguiente paso hacia Movistar Total"
            else:
                continuity = "la alternativa conserva la compatibilidad comercial del cliente"
            speech = (
                f"No insista con {top['nombre_oferta']} durante el cooldown. Desde {recontact_from}, "
                f"valide nuevamente la necesidad y presente {alternative_name} por {channel}; "
                f"{continuity}."
            )
        elif objection == "mal_momento":
            speech = f"Acordar una nueva ventana y no recontactar antes de {recontact_from}."
        elif objection == "no_confia":
            speech = f"Enviar primero condiciones oficiales por Digital y no retomar la oferta antes de {recontact_from}."
        else:
            speech = (
                f"No insistir con {top['nombre_oferta']} durante el cooldown. Desde {recontact_from}, "
                f"{objective[0].lower() + objective[1:]}"
            )
        reason_codes = ["COOLDOWN_14D", "PRESERVE_MT_PATH"]
        if source == "observed":
            reason_codes.append("OBSERVED_REJECTION")
        if alternative is not None:
            reason_codes.append("LOWER_VALID_TIER")
        return PostRejectionAction(
            source=source, trigger_reason=objection, action=action, objective=objective,
            wait_days=wait_days, recontact_from=recontact_from, channel=channel,
            alternative_offer_id=str(alternative["oferta_id"]) if alternative is not None else None,
            alternative_offer_name=alternative_name,
            preserves_mt_path=True, speech=speech, reason_codes=reason_codes,
        )

    def _history_summary(self, as_of: str | pd.Timestamp):
        key = pd.Timestamp(as_of).isoformat()
        if key not in self._summary_cache:
            self._summary_cache[key] = summarize_history(self.history, self.catalog, as_of, self.smoothing_alpha)
        return self._summary_cache[key]

    def _overlay_operational_rejections(
        self, candidates: pd.DataFrame, cliente_ids: list[str], reference_time: pd.Timestamp,
    ) -> pd.DataFrame:
        """Incorpora rechazos registrados por API sin contaminar evaluaciones históricas."""
        if self.store is None:
            return candidates
        rows = self.store.operational_rejections(cliente_ids)
        if not rows:
            return candidates
        feedback = pd.DataFrame(rows)
        feedback["created_at"] = pd.to_datetime(feedback["created_at"], utc=True).dt.tz_localize(None)
        feedback = feedback.sort_values("created_at").drop_duplicates(
            ["decision_id", "oferta_id"], keep="last"
        )
        reference = pd.Timestamp(reference_time)
        if reference.tzinfo is not None:
            reference = reference.tz_localize(None)
        feedback = feedback.loc[feedback["created_at"].le(reference)]
        if feedback.empty:
            return candidates
        latest = feedback.groupby(["cliente_id", "oferta_id"], observed=True)["created_at"].max()
        latest.name = "operational_rejection_date"
        data = candidates.join(latest, on=["cliente_id", "oferta_id"])
        historical = pd.to_datetime(data["last_rejection_date"])
        operational = pd.to_datetime(data["operational_rejection_date"])
        data["last_rejection_date"] = historical.where(
            operational.isna() | historical.ge(operational), operational
        )
        recent_cutoff = reference - pd.Timedelta(days=30)
        recent = feedback.loc[feedback["created_at"].ge(recent_cutoff)].groupby(
            "cliente_id", observed=True
        ).size()
        data["recent_offers_30d"] = data["recent_offers_30d"] + data["cliente_id"].map(recent).fillna(0)
        return add_pair_features(data, self.config["features"]["friction_weights"])

    def _overlay_operational_behavior(
        self, candidates: pd.DataFrame, cliente_ids: list[str], reference_time: pd.Timestamp,
    ) -> pd.DataFrame:
        """Fusiona cada decision operacional una sola vez y actualiza tasas jerarquicas."""
        if self.store is None:
            return candidates
        rows = self.store.operational_interactions(cliente_ids)
        if not rows:
            return candidates
        events = pd.DataFrame(rows)
        events["created_at"] = pd.to_datetime(events["created_at"], utc=True).dt.tz_localize(None)
        reference = pd.Timestamp(reference_time)
        if reference.tzinfo is not None:
            reference = reference.tz_localize(None)
        events = events.loc[events["created_at"].le(reference)].drop_duplicates("decision_id")
        if events.empty:
            return candidates
        data = candidates.copy()
        events["offer"] = 1
        for column in ("contacted", "accepted", "rejected"):
            events[column] = events[column].astype(int)

        client = events.groupby("cliente_id", observed=True)[
            ["offer", "contacted", "accepted", "rejected"]
        ].sum()
        channel = events.groupby(["cliente_id", "canal"], observed=True)[
            ["offer", "contacted", "accepted", "rejected"]
        ].sum()
        offer = events.groupby(["cliente_id", "oferta_id"], observed=True)[
            ["offer", "contacted", "accepted", "rejected"]
        ].sum()
        for source, keys, mapping in (
            (client, ["cliente_id"], {"offer": "hist_client_offer", "contacted": "hist_client_contact", "accepted": "hist_client_accept", "rejected": "hist_client_reject"}),
            (channel, ["cliente_id", "canal"], {"offer": "hist_channel_offer", "contacted": "hist_channel_contact", "accepted": "hist_channel_accept", "rejected": "hist_channel_reject"}),
            (offer, ["cliente_id", "oferta_id"], {"offer": "hist_offer_offer", "contacted": "hist_offer_contact", "accepted": "hist_offer_accept", "rejected": "hist_offer_reject"}),
        ):
            renamed = source.rename(columns={key: f"_op_{value}" for key, value in mapping.items()})
            data = data.join(renamed, on=keys)
            for raw, target in mapping.items():
                op = f"_op_{target}"
                data[target] = data[target].astype(float) + data[op].fillna(0)
                data.drop(columns=op, inplace=True)

        alpha = self.smoothing_alpha
        op_channel = channel.rename(columns={
            "offer": "op_offer", "contacted": "op_contact", "accepted": "op_accept",
        })
        data = data.join(op_channel[["op_offer", "op_contact", "op_accept"]], on=["cliente_id", "canal"])
        data[["op_offer", "op_contact", "op_accept"]] = data[["op_offer", "op_contact", "op_accept"]].fillna(0)
        data["hist_contact_rate_channel"] = (
            data["op_contact"] + alpha * data["hist_contact_rate_channel"]
        ) / (data["op_offer"] + alpha)
        data["hist_accept_rate_channel"] = (
            data["op_accept"] + alpha * data["hist_accept_rate_channel"]
        ) / (data["op_contact"] + alpha)
        data["hist_contact_rate_channel"] = data["hist_contact_rate_channel"].clip(0, 1)
        data["hist_accept_rate_channel"] = data["hist_accept_rate_channel"].clip(0, 1)
        data.drop(columns=["op_offer", "op_contact", "op_accept"], inplace=True)

        rejected = events.loc[events["rejected"].eq(1)]
        if not rejected.empty:
            latest = rejected.groupby(["cliente_id", "oferta_id"], observed=True)["created_at"].max()
            latest.name = "operational_rejection_date"
            data = data.join(latest, on=["cliente_id", "oferta_id"])
            historical = pd.to_datetime(data["last_rejection_date"])
            operational = pd.to_datetime(data["operational_rejection_date"])
            data["last_rejection_date"] = historical.where(
                operational.isna() | historical.ge(operational), operational,
            )
        recent = events.loc[events["created_at"].ge(reference - pd.Timedelta(days=30))].groupby(
            "cliente_id", observed=True,
        ).size()
        data["recent_offers_30d"] = data["recent_offers_30d"] + data["cliente_id"].map(recent).fillna(0)
        return add_pair_features(data, self.config["features"]["friction_weights"])

    def _prepare_candidates(self, cliente_id: str, as_of: str | pd.Timestamp) -> pd.DataFrame:
        if cliente_id not in self.customer_index.index:
            raise KeyError(cliente_id)
        customer = self.customer_index.loc[cliente_id]
        candidates = generate_candidates(customer, self.catalog)
        candidates = attach_inference_history(
            candidates, self._history_summary(as_of), self.smoothing_alpha, self.config["features"]["friction_weights"]
        )
        rules = {**self.config["rules"], "as_of_date": str(pd.Timestamp(as_of).date())}
        candidates = candidates.loc[eligibility_mask(customer, candidates, self.catalog, rules)].copy()
        if candidates.empty:
            raise RuntimeError("No existen ofertas elegibles para el cliente")
        return candidates

    def _prepare_candidates_many(
        self,
        cliente_ids: list[str],
        as_of: str | pd.Timestamp,
        include_operational_feedback: bool = False,
        rule_as_of: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        missing = [client_id for client_id in cliente_ids if client_id not in self.customer_index.index]
        if missing:
            raise KeyError(missing[0])
        if include_operational_feedback and self.state_service is not None:
            state_rows = []
            for client_id in cliente_ids:
                state = self.state_service.get_state(client_id)
                row = dict(state.attributes)
                row["_state_version"] = state.state_version
                row["_state_as_of"] = state.as_of.isoformat()
                row["_state_event_ids"] = state.applied_event_ids
                row["active_offer_ids"] = state.active_offer_ids
                state_rows.append(row)
            customers = pd.DataFrame(state_rows)
        else:
            customers = self.customer_index.loc[cliente_ids].copy().reset_index(drop=True)
            customers["_state_version"] = 0
            customers["_state_as_of"] = pd.Timestamp(as_of).isoformat()
            customers["_state_event_ids"] = [[] for _ in range(len(customers))]
            customers["active_offer_ids"] = [[] for _ in range(len(customers))]
        offers = self.catalog.rename(columns={"es_movistar_total": "oferta_es_movistar_total"}).copy()
        offers = offers.loc[offers.index.repeat(len(CHANNELS))].reset_index(drop=True)
        offers["canal"] = CHANNELS * len(self.catalog)
        customers["_cross"] = 1
        offers["_cross"] = 1
        candidates = customers.merge(offers, on="_cross", how="inner", validate="many_to_many").drop(columns="_cross")
        candidates = attach_inference_history(
            candidates, self._history_summary(as_of), self.smoothing_alpha,
            self.config["features"]["friction_weights"],
        )
        rule_reference = pd.Timestamp(rule_as_of if rule_as_of is not None else as_of)
        if include_operational_feedback:
            candidates = self._overlay_operational_behavior(candidates, cliente_ids, rule_reference)
        rules = {**self.config["rules"], "as_of_date": rule_reference}
        result = self._filter_with_trace(candidates, rules)
        if result.empty:
            raise RuntimeError("No existen ofertas elegibles para el chunk")
        return result

    def _filter_with_trace(self, candidates: pd.DataFrame, rules: dict) -> pd.DataFrame:
        reasons = eligibility_reasons_frame(candidates, self.catalog, rules)
        valid = ~reasons.any(axis=1)
        grouped_total = candidates.groupby("cliente_id", observed=True).size()
        grouped_blocked = reasons.any(axis=1).groupby(candidates["cliente_id"], observed=True).sum()
        grouped_eligible = valid.groupby(candidates["cliente_id"], observed=True).sum()
        candidates["_trace_total"] = candidates["cliente_id"].map(grouped_total)
        candidates["_trace_blocked"] = candidates["cliente_id"].map(grouped_blocked)
        candidates["_trace_eligible"] = candidates["cliente_id"].map(grouped_eligible)
        for reason in reasons.columns:
            counts = reasons[reason].groupby(candidates["cliente_id"], observed=True).sum()
            candidates[f"_blocked_{reason}"] = candidates["cliente_id"].map(counts)
        return candidates.loc[valid].reset_index(drop=True)

    def recommend_override(
        self,
        customer: pd.Series,
        rejected_offers: dict[str, pd.Timestamp] | None = None,
        rule_as_of: pd.Timestamp | None = None,
        fatigue_delta: float = 0.0,
    ) -> NBOResult:
        """Recomendación aislada para simulaciones; nunca persiste ni muta el maestro."""
        candidates, reference = self._override_candidates(customer, rejected_offers, rule_as_of, fatigue_delta)
        return self._build_result(str(customer["cliente_id"]), customer, candidates, reference)

    def _override_candidates(
        self,
        customer: pd.Series,
        rejected_offers: dict[str, pd.Timestamp] | None = None,
        rule_as_of: pd.Timestamp | None = None,
        fatigue_delta: float = 0.0,
    ) -> tuple[pd.DataFrame, pd.Timestamp]:
        historical_as_of = pd.Timestamp(self.config["features"]["as_of_date"])
        reference = pd.Timestamp(rule_as_of if rule_as_of is not None else historical_as_of)
        candidates = generate_candidates(customer, self.catalog)
        candidates = attach_inference_history(
            candidates, self._history_summary(historical_as_of), self.smoothing_alpha,
            self.config["features"]["friction_weights"],
        )
        if fatigue_delta:
            candidates["recent_offers_30d"] = (
                candidates["recent_offers_30d"] + max(float(fatigue_delta), 0.0)
            )
        for offer_id, rejection_date in (rejected_offers or {}).items():
            mask = candidates["oferta_id"].eq(offer_id)
            candidates.loc[mask, "last_rejection_date"] = pd.Timestamp(rejection_date)
            candidates.loc[mask, "recent_offers_30d"] = candidates.loc[mask, "recent_offers_30d"] + 1
        candidates = add_pair_features(candidates, self.config["features"]["friction_weights"])
        rules = {**self.config["rules"], "as_of_date": reference}
        candidates = self._filter_with_trace(candidates, rules)
        if candidates.empty:
            raise RuntimeError("No existen ofertas elegibles para el escenario")
        candidates["p_contacto"] = self.contact_model.predict_positive(candidates)
        candidates["p_aceptacion"] = self.acceptance_model.predict_positive(candidates)
        candidates = self._attach_churn(candidates)
        candidates = score_candidate_frame(candidates, self.catalog, self.scoring, rules)
        return candidates, reference

    def recovery_for_override(
        self, customer: pd.Series, result: NBOResult, reason: str, base_date: pd.Timestamp,
    ) -> PostRejectionAction:
        candidates, _ = self._override_candidates(customer, rule_as_of=base_date)
        top = candidates.loc[candidates["oferta_id"].eq(result.recommendation.oferta_id)]
        channel = top.loc[top["canal"].eq(result.recommendation.canal)]
        row = (channel if not channel.empty else top).iloc[0]
        return self._post_rejection_action(customer, row, candidates, reason, "observed", base_date)

    def _recommend_many_at(
        self,
        cliente_ids: list[str],
        as_of: str | pd.Timestamp,
        persist: bool,
        include_operational_feedback: bool = False,
    ) -> list[NBOResult]:
        """Vectoriza las predicciones ML del chunk y mantiene reglas por cliente."""
        if len(set(cliente_ids)) != len(cliente_ids):
            raise ValueError("cliente_ids debe contener IDs únicos")
        started = time.perf_counter()
        combined = self._candidate_scores_at(
            cliente_ids, as_of, self.scoring,
            include_operational_feedback=include_operational_feedback,
        )
        results: list[NBOResult] = []
        for client_id in cliente_ids:
            candidates = combined.loc[combined["cliente_id"].eq(client_id)].copy()
            customer = candidates.iloc[0]
            result = self._build_result(client_id, customer, candidates, pd.Timestamp(as_of))
            if persist and self.store:
                self.store.save_decision(result.model_dump())
            results.append(result)
            LOGGER.info("nbo_decision", extra={"cliente_id": client_id, "decision_id": result.decision_id, "candidate_count": len(candidates), "top_offer": result.recommendation.oferta_id})
        LOGGER.info("nbo_batch", extra={"client_count": len(cliente_ids), "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
        return results

    @property
    def _population_uplift_mt(self) -> float:
        if self._population_uplift_mt_cached is None:
            self._population_uplift_mt_cached = population_uplift_mt(self.history, self.catalog)
        return self._population_uplift_mt_cached

    def _persona_for(self, customer: pd.Series) -> PersonaAssignment:
        if self.enrichment.personas is None:
            return PersonaAssignment(disponible=False)
        frame = pd.DataFrame([customer.to_dict()])
        cluster = int(self.enrichment.personas.assign(frame)[0])
        nombre, descripcion = self.enrichment.personas.describe(cluster)
        return PersonaAssignment(disponible=True, cluster_id=cluster, nombre=nombre, descripcion=descripcion)

    def _churn_for(self, customer: pd.Series) -> ChurnAssessment:
        if self.enrichment.churn is None:
            return ChurnAssessment(disponible=False)
        frame = pd.DataFrame([customer.to_dict()])
        probability = float(self.enrichment.churn.predict(frame)[0])
        return ChurnAssessment(
            disponible=True,
            probabilidad=probability,
            nivel=self.enrichment.churn.level(probability),
            fuente="proxy_operacional",
            proxy_definition=self.enrichment.churn.proxy_definition,
        )

    def _build_result(
        self, client_id: str, customer: pd.Series, candidates: pd.DataFrame, as_of: pd.Timestamp,
    ) -> NBOResult:
        top = best_channel_then_rank(candidates, 3)
        contributions = self.acceptance_model.local_contributions(top)
        recommendations = [
            self._recommendation(customer, row, contributions[i])
            for i, (_, row) in enumerate(top.iterrows())
        ]
        objections = self._objections(top.iloc[[0]])
        rebate = self._rebate(customer, objections[0].motivo, top.iloc[0], candidates)
        strategy = self._commercial_strategy(customer, top.iloc[0])
        post_rejection = self._post_rejection_action(
            customer, top.iloc[0], candidates, objections[0].motivo, "predicted", as_of,
        )
        decision_id = str(uuid.uuid4())
        experiment = self._playbook_experiment(client_id, decision_id)
        playbook = build_sales_playbook(
            row=top.iloc[0], strategy=strategy, explanation=recommendations[0].explanation,
            customer_benefit=recommendations[0].beneficio_cliente, objection=objections[0],
            rebate=rebate, post_rejection=post_rejection,
            version=self.versions["playbook_version"], reason_codes=recommendations[0].reason_codes,
            urgency=recommendations[0].momento.urgencia, variant=experiment.variant,
        )
        persona = self._persona_for(customer)
        churn = self._churn_for(customer)
        uplift_mt = compute_uplift_mt(
            candidates, population_uplift=self._population_uplift_mt if bool(customer.get("elegible_mt")) else None
        )
        return NBOResult(
            decision_id=decision_id,
            decision_schema_version=self.config["project"]["decision_schema_version"], versions=self.versions,
            cliente=CustomerSummary(
                cliente_id=client_id, etapa_mt=mt_stage(customer), elegible_mt=bool(customer["elegible_mt"]),
                es_movistar_total=bool(customer["es_movistar_total"]), tipo_cliente=str(customer["tipo_cliente"]),
                tiene_movil=bool(customer["tiene_movil"]), tiene_hogar=bool(customer["tiene_hogar"]),
                tiene_internet_hogar=bool(customer["tiene_internet_hogar"]), plan_actual_id=str(customer["plan_actual_id"]),
                monto_facturado_prom=float(customer["monto_facturado_prom"]),
                consumo_datos_gb_prom=float(customer["consumo_datos_gb_prom"]),
                canal_mas_usado=str(customer["canal_mas_usado"]), n_reclamos=int(customer["n_reclamos"]),
                meses_moroso=int(customer["meses_moroso"]),
                persona=persona, riesgo_fuga=churn, uplift_mt=uplift_mt,
            ),
            recommendation=recommendations[0], alternatives=recommendations[1:], rejection_prediction=objections,
            rebate=rebate, commercial_strategy=strategy, post_rejection_action=post_rejection,
            sales_playbook=playbook, decision_trace=self._decision_trace(candidates, top),
            evidence_confidence=self._confidence(top.iloc[0]), playbook_experiment=experiment,
            state_version=int(customer.get("_state_version", 0) or 0),
            state_as_of=pd.Timestamp(customer.get("_state_as_of", as_of)).to_pydatetime(),
            applied_state_event_ids=list(customer.get("_state_event_ids", []) or []),
        )

    def _attach_churn(self, combined: pd.DataFrame) -> pd.DataFrame:
        if self.enrichment.churn is None:
            return combined
        clients = combined.drop_duplicates("cliente_id").set_index("cliente_id")
        probabilities = self.enrichment.churn.predict(clients)
        churn_map = dict(zip(clients.index.astype(str), probabilities.tolist()))
        combined["p_churn"] = combined["cliente_id"].astype(str).map(churn_map).fillna(0.0)
        return combined

    def _candidate_scores_at(
        self,
        cliente_ids: list[str],
        as_of: str | pd.Timestamp,
        scoring: dict,
        include_operational_feedback: bool = False,
    ) -> pd.DataFrame:
        rule_as_of = (
            pd.Timestamp.now(tz="UTC").tz_localize(None)
            if include_operational_feedback else pd.Timestamp(as_of)
        )
        combined = self._prepare_candidates_many(
            cliente_ids, as_of, include_operational_feedback, rule_as_of,
        )
        combined["p_contacto"] = self.contact_model.predict_positive(combined)
        combined["p_aceptacion"] = self.acceptance_model.predict_positive(combined)
        combined = self._attach_churn(combined)
        rules = {**self.config["rules"], "as_of_date": rule_as_of}
        return score_candidate_frame(combined, self.catalog, scoring, rules)

    def post_rejection_action(self, decision_id: str, reason: str) -> PostRejectionAction:
        """Calcula la próxima mejor acción usando el motivo de rechazo realmente observado."""
        if self.store is None:
            raise RuntimeError("La acción post-rechazo requiere persistencia habilitada")
        decision = self.store.get_decision(decision_id)
        client_id = str(decision["cliente_id"])
        customer = self.customer_index.loc[client_id]
        as_of = self.config["features"]["as_of_date"]
        candidates = self._candidate_scores_at(
            [client_id], as_of, self.scoring, include_operational_feedback=True,
        )
        top_matches = candidates.loc[candidates["oferta_id"].eq(decision["top_offer_id"])]
        if top_matches.empty:
            catalog_row = self.catalog.loc[self.catalog["oferta_id"].eq(decision["top_offer_id"])]
            if catalog_row.empty:
                raise RuntimeError("La oferta de la decisión ya no existe en el catálogo")
            top = catalog_row.iloc[0].copy()
            top["oferta_es_movistar_total"] = bool(top["es_movistar_total"])
            top["canal"] = decision["top_channel"]
        else:
            channel_match = top_matches.loc[top_matches["canal"].eq(decision["top_channel"])]
            top = (channel_match if not channel_match.empty else top_matches).iloc[0]
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        return self._post_rejection_action(customer, top, candidates, reason, "observed", now)

    def candidate_scores_as_of(self, cliente_ids: list[str], fecha: str | pd.Timestamp) -> pd.DataFrame:
        """Salida auditable de candidatos; no persiste decisiones."""
        cutoff = pd.Timestamp(fecha).to_period("M").start_time
        return self._candidate_scores_at(cliente_ids, cutoff, self.scoring)

    def rank_many(self, cliente_ids: list[str], fecha: str | pd.Timestamp | None = None) -> pd.DataFrame:
        """Top 1 vectorizado para batch; omite SHAP, objeciones y persistencia."""
        as_of = fecha or self.config["features"]["as_of_date"]
        candidates = self._candidate_scores_at(
            cliente_ids, as_of, self.scoring, include_operational_feedback=fecha is None,
        )
        best_channel = candidates.sort_values(
            ["cliente_id", "oferta_id", "p_venta", "score"], ascending=[True, True, False, False]
        ).drop_duplicates(["cliente_id", "oferta_id"], keep="first")
        return best_channel.sort_values(
            ["cliente_id", "score", "p_venta", "oferta_id"], ascending=[True, False, False, True]
        ).groupby("cliente_id", observed=True).head(1).reset_index(drop=True)

    def recommend_many(self, cliente_ids: list[str]) -> list[NBOResult]:
        return self._recommend_many_at(
            cliente_ids, self.config["features"]["as_of_date"], persist=True,
            include_operational_feedback=True,
        )

    def recommend(self, cliente_id: str) -> NBOResult:
        return self.recommend_many([cliente_id])[0]

    def recommend_as_of(self, cliente_id: str, fecha: str | pd.Timestamp) -> NBOResult:
        """Recomienda usando solo eventos de meses completos anteriores al corte."""
        cutoff = pd.Timestamp(fecha).to_period("M").start_time
        return self._recommend_many_at([cliente_id], cutoff, persist=False, include_operational_feedback=False)[0]

    def recommend_many_as_of(self, cliente_ids: list[str], fecha: str | pd.Timestamp) -> list[NBOResult]:
        cutoff = pd.Timestamp(fecha).to_period("M").start_time
        return self._recommend_many_at(cliente_ids, cutoff, persist=False, include_operational_feedback=False)
