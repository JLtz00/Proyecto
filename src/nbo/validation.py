from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

import pandas as pd


CUSTOMER_COLUMNS = {
    "cliente_id", "tipo_cliente", "antiguedad_meses", "tiene_movil", "tiene_hogar",
    "oferta_hogar_id", "tiene_internet_hogar", "es_movistar_total", "elegible_mt",
    "plan_actual_id", "monto_facturado_prom", "edad_rango", "ubicacion_departamento",
    "es_usuario_app", "consumo_datos_gb_prom", "consumo_voz_min_prom", "consumo_sms_prom",
    "uso_app_movistar_prom", "monto_facturado_prom_6m", "dias_mora_prom", "meses_moroso",
    "n_reclamos", "n_actividad_canal", "canal_mas_usado",
}
CATALOG_COLUMNS = {
    "oferta_id", "nombre_oferta", "tipo_oferta", "segmento_objetivo", "es_movistar_total",
    "precio_mensual", "ahorro_pct", "gb_incluidos", "cluster_hogar",
    "descripcion_bundle", "descripcion_corta",
}
HISTORY_COLUMNS = {
    "ofrecimiento_id", "cliente_id", "oferta_id", "fecha", "canal", "resultado",
    "motivo_rechazo", "es_rebate", "contactabilidad", "medio_probatorio", "tipo_cliente",
    "antiguedad_meses", "elegible_mt", "es_movistar_total", "nombre_oferta",
    "tipo_oferta", "oferta_es_mt",
}


@dataclass
class QualityIssue:
    level: str
    check: str
    count: int
    detail: str


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def add(self, level: str, check: str, count: int, detail: str) -> None:
        if count:
            self.issues.append(QualityIssue(level, check, int(count), detail))

    def to_dict(self) -> dict:
        return {"valid": self.valid, "issues": [asdict(item) for item in self.issues]}

    def raise_for_errors(self) -> None:
        errors = [f"{x.check}: {x.detail} ({x.count})" for x in self.issues if x.level == "error"]
        if errors:
            raise ValueError("Validacion critica fallida: " + "; ".join(errors))


def _missing(required: set[str], actual: Iterable[str]) -> set[str]:
    return required.difference(actual)


def validate_data(
    customers: pd.DataFrame,
    catalog: pd.DataFrame,
    history: pd.DataFrame,
    expected: dict | None = None,
) -> QualityReport:
    expected = expected or {}
    report = QualityReport()
    for name, frame, required in (
        ("customers", customers, CUSTOMER_COLUMNS),
        ("catalog", catalog, CATALOG_COLUMNS),
        ("history", history, HISTORY_COLUMNS),
    ):
        absent = _missing(required, frame.columns)
        report.add("error", f"{name}.schema", len(absent), f"Columnas ausentes: {sorted(absent)}")

    if not report.valid:
        return report

    expected_rows = {
        "customers": expected.get("expected_customers"),
        "catalog": expected.get("expected_offers"),
        "history": expected.get("expected_history"),
    }
    for name, frame in (("customers", customers), ("catalog", catalog), ("history", history)):
        wanted = expected_rows[name]
        if wanted is not None and len(frame) != wanted:
            report.add("warning", f"{name}.volume", abs(len(frame) - wanted), f"Esperado {wanted}; observado {len(frame)}")

    for frame, key, name in (
        (customers, "cliente_id", "customers.pk"),
        (catalog, "oferta_id", "catalog.pk"),
        (history, "ofrecimiento_id", "history.pk"),
    ):
        report.add("error", name, frame[key].duplicated().sum(), "IDs duplicados")
        report.add("error", f"{name}.empty", frame[key].isna().sum() + frame[key].astype(str).str.strip().eq("").sum(), "IDs vacios")

    for name, frame, cols in (
        ("customers", customers, ["tiene_movil", "tiene_hogar", "tiene_internet_hogar", "es_movistar_total", "elegible_mt", "es_usuario_app"]),
        ("catalog", catalog, ["es_movistar_total"]),
        ("history", history, ["es_rebate", "elegible_mt", "es_movistar_total", "oferta_es_mt"]),
    ):
        for col in cols:
            report.add("error", f"{name}.{col}.boolean", frame[col].isna().sum(), "Booleano invalido o nulo")

    nonnegative_customer = [
        "antiguedad_meses", "monto_facturado_prom", "consumo_datos_gb_prom",
        "consumo_voz_min_prom", "consumo_sms_prom", "uso_app_movistar_prom",
        "monto_facturado_prom_6m", "dias_mora_prom", "n_reclamos", "n_actividad_canal",
    ]
    for col in nonnegative_customer:
        values = pd.to_numeric(customers[col], errors="coerce")
        report.add("error", f"customers.{col}.domain", values.isna().sum() + values.lt(0).sum(), "Debe ser numerico no negativo")
    months = pd.to_numeric(customers["meses_moroso"], errors="coerce")
    report.add("error", "customers.meses_moroso.domain", months.isna().sum() + (~months.between(0, 6)).sum(), "Debe estar entre 0 y 6")
    customer_type_invalid = customers["tipo_cliente"].notna() & ~customers["tipo_cliente"].isin(["prepago", "postpago"])
    report.add("error", "customers.tipo_cliente.domain", customer_type_invalid.sum(), "Debe ser prepago, postpago o nulo sin línea")
    preferred_channel_invalid = customers["canal_mas_usado"].notna() & ~customers["canal_mas_usado"].isin(["Digital", "Tienda", "Call In", "Call Out"])
    report.add("error", "customers.canal_mas_usado.domain", preferred_channel_invalid.sum(), "Canal preferido inválido")

    prices = pd.to_numeric(catalog["precio_mensual"], errors="coerce")
    report.add("error", "catalog.precio_mensual.domain", prices.isna().sum() + prices.le(0).sum(), "Debe ser positivo")
    actual_mt = set(catalog.loc[catalog["es_movistar_total"].fillna(False), "oferta_id"])
    report.add("error", "catalog.mt_ids", int(actual_mt != {"OF020", "OF021", "OF022"}), f"IDs MT observados: {sorted(actual_mt)}")
    savings = pd.to_numeric(catalog["ahorro_pct"], errors="coerce")
    invalid_savings = ((catalog["es_movistar_total"] & savings.le(0)) | (~catalog["es_movistar_total"] & savings.ne(0))).sum()
    report.add("error", "catalog.ahorro_pct", invalid_savings, "El ahorro debe ser positivo solo para MT")
    report.add("error", "catalog.tipo_oferta.domain", (~catalog["tipo_oferta"].isin(["plan_movil", "plan_hogar", "upgrade", "equipo", "paquete_adicional", "movistar_total"])).sum(), "Tipo de oferta inválido")
    report.add("error", "catalog.segmento_objetivo.domain", (~catalog["segmento_objetivo"].isin(["movil", "hogar", "ambos"])).sum(), "Segmento inválido")
    for column in ("ahorro_pct", "gb_incluidos"):
        values = pd.to_numeric(catalog[column], errors="coerce")
        report.add("error", f"catalog.{column}.domain", values.isna().sum() + values.lt(0).sum(), "Debe ser numérico no negativo")

    catalog_ids = set(catalog["oferta_id"])
    for column in ("plan_actual_id", "oferta_hogar_id"):
        values = customers[column].dropna()
        report.add("error", f"customers.{column}.fk", (~values.isin(catalog_ids)).sum(), "Referencia a oferta inexistente")
    home_state_bad = (customers["tiene_hogar"] & customers["oferta_hogar_id"].isna()) | (~customers["tiene_hogar"] & customers["oferta_hogar_id"].notna())
    report.add("error", "customers.home_state", home_state_bad.sum(), "tiene_hogar y oferta_hogar_id son incoherentes")
    report.add("error", "customers.internet_requires_home", (customers["tiene_internet_hogar"] & ~customers["tiene_hogar"]).sum(), "Internet hogar requiere servicio hogar")
    expected_eligible = customers["tiene_movil"] & customers["tipo_cliente"].eq("postpago") & customers["tiene_internet_hogar"] & ~customers["es_movistar_total"]
    report.add("error", "customers.mt_eligibility", customers["elegible_mt"].ne(expected_eligible).sum(), "elegible_mt no coincide con las condiciones observables")

    report.add("error", "history.customer_fk", (~history["cliente_id"].isin(customers["cliente_id"])).sum(), "Cliente inexistente")
    report.add("error", "history.offer_fk", (~history["oferta_id"].isin(catalog["oferta_id"])).sum(), "Oferta inexistente")
    for col, allowed in (
        ("canal", {"Digital", "Tienda", "Call In", "Call Out"}),
        ("resultado", {"aceptada", "rechazada", "pendiente"}),
        ("contactabilidad", {"contactado", "no_contactado"}),
    ):
        report.add("error", f"history.{col}.domain", (~history[col].isin(allowed)).sum(), f"Fuera de {sorted(allowed)}")
    pending_bad = ((history["resultado"] == "pendiente") != (history["contactabilidad"] == "no_contactado")).sum()
    report.add("error", "history.pending_contact", pending_bad, "pendiente debe equivaler a no_contactado")
    rejection_null = history["motivo_rechazo"].isna() | history["motivo_rechazo"].astype(str).str.strip().eq("")
    motive_bad = ((history["resultado"] == "rechazada") & rejection_null).sum() + ((history["resultado"] != "rechazada") & ~rejection_null).sum()
    report.add("error", "history.rejection_reason", motive_bad, "Motivo solo debe existir en rechazos")
    mt_map = catalog.set_index("oferta_id")["es_movistar_total"]
    expected_mt = history["oferta_id"].map(mt_map).astype("boolean")
    report.add("error", "history.offer_mt_consistency", expected_mt.ne(history["oferta_es_mt"]).sum(), "Bandera MT no coincide con catalogo")
    catalog_master = catalog.drop_duplicates("oferta_id", keep="first").set_index("oferta_id")
    for copied, master in (("nombre_oferta", "nombre_oferta"), ("tipo_oferta", "tipo_oferta")):
        expected_value = history["oferta_id"].map(catalog_master[master]).fillna("__null__").astype(str)
        observed_value = history[copied].fillna("__null__").astype(str)
        report.add("error", f"history.{copied}.master_consistency", observed_value.ne(expected_value).sum(), "Copia histórica no coincide con catálogo maestro")
    customer_master = customers.drop_duplicates("cliente_id", keep="first").set_index("cliente_id")
    for copied, master in (("tipo_cliente", "tipo_cliente"), ("antiguedad_meses", "antiguedad_meses"), ("elegible_mt", "elegible_mt"), ("es_movistar_total", "es_movistar_total")):
        expected_value = history["cliente_id"].map(customer_master[master]).fillna("__null__").astype(str)
        observed_value = history[copied].fillna("__null__").astype(str)
        report.add("error", f"history.{copied}.master_consistency", observed_value.ne(expected_value).sum(), "Copia histórica no coincide con cliente maestro")
    report.add("error", "history.fecha", history["fecha"].isna().sum(), "Fecha invalida")
    return report
