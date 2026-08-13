from __future__ import annotations

import pandas as pd

from nbo.engine import NBOEngine


def _scored_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    frame = catalog.rename(columns={"es_movistar_total": "oferta_es_movistar_total"}).copy()
    frame["canal"] = "Digital"
    frame["p_venta"] = 0.4
    frame["score"] = 0.5
    return frame


def test_price_recovery_does_not_break_home_route(customer, catalog):
    engine = object.__new__(NBOEngine)
    route_customer = customer.copy()
    route_customer.update({
        "elegible_mt": False,
        "tiene_hogar": False,
        "tiene_internet_hogar": False,
        "oferta_hogar_id": None,
    })
    candidates = _scored_catalog(catalog)
    top = candidates.loc[candidates["oferta_id"].eq("OF005")].iloc[0]

    alternative = engine._recovery_alternative(route_customer, top, candidates, "precio")

    # OF007 es más barato, pero solo ofrece TV y desviaría la ruta hacia MT.
    assert alternative is None


def test_price_recovery_for_mt_keeps_a_lower_mt_tier(customer, catalog):
    engine = object.__new__(NBOEngine)
    candidates = _scored_catalog(catalog)
    extra = candidates.loc[candidates["oferta_id"].eq("OF020")].copy()
    extra["oferta_id"] = "OF021"
    extra["nombre_oferta"] = "MT Plus"
    extra["precio_mensual"] = 190.0
    top = candidates.loc[candidates["oferta_id"].eq("OF020")].iloc[0].copy()
    top["oferta_id"] = "OF022"
    top["nombre_oferta"] = "MT Max"
    top["precio_mensual"] = 230.0
    candidates = pd.concat([candidates, extra, top.to_frame().T], ignore_index=True)

    alternative = engine._recovery_alternative(customer, top, candidates, "precio")

    assert alternative is not None
    assert bool(alternative["oferta_es_movistar_total"])
    assert float(alternative["precio_mensual"]) < float(top["precio_mensual"])
