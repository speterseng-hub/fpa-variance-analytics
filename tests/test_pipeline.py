"""Tests: the numbers must reconcile, whatever the filter."""
import pandas as pd
import pytest

from src import commentary as K
from src import config as C
from src import forecast as F
from src import pipeline
from src import variance as V


@pytest.fixture(scope="session")
def con():
    assert pipeline.run(generate=True) == 0, "data quality checks failed"
    c = V.connect()
    yield c
    c.close()


def test_all_quality_checks_pass(con):
    checks = con.execute("SELECT check_name, status FROM quality_checks").df()
    assert len(checks) >= 10
    assert (checks.status == "PASS").all(), checks[checks.status != "PASS"]


@pytest.mark.parametrize("view", [
    V.View(),                                                             # YTD actual vs budget
    V.View(base="ACTUAL", comp="ACTUAL", offset=12),                      # vs prior year
    V.View(base="FC_6+6", months=["2026-07-01", "2026-08-01", "2026-09-01"]),
    V.View(comp="FC_9+3", months=[f"2026-{m:02d}-01" for m in range(1, 13)]),  # FY landing
    V.View(months=["2026-05-01"], countries=["CO"]),                      # single month, one country
])
def test_ebitda_bridge_reconciles(con, view):
    kb = V.kpis(con, view.base, view.base_months, view.countries)
    ka = V.kpis(con, view.comp, view.months, view.countries)
    bridge = V.bridge(con, view).impact_eur.sum()
    assert bridge == pytest.approx(ka["ebitda"] - kb["ebitda"], abs=1.0)


def test_revenue_bridge_reconciles(con):
    rb = V.revenue_bridge(con, V.View()).iloc[0]
    assert rb[["Volume", "Mix", "Price", "FX"]].sum() == pytest.approx(rb["comp"] - rb["base"], abs=1.0)


def test_pnl_subtotals(con):
    p = V.pnl(con, V.View())["comp"]
    assert p["Gross margin"] == pytest.approx(p["Net revenue"] + p["COGS"])
    assert p["EBITDA"] == pytest.approx(p["Gross margin"] + p["Total opex"])


def test_no_fx_effect_for_euro_country(con):
    b = V.bridge(con, V.View(countries=["ES"]))
    assert b.loc[b.driver == "FX", "impact_eur"].sum() == pytest.approx(0, abs=1e-6)


def test_embedded_events_are_detected(con):
    """The analysis must surface the business events planted in the data."""
    d = V.sales_detail(con, V.View(months=["2026-09-01"]))
    cl_elec = d[(d.country == "CL") & (d.category == "ELEC")].iloc[0]
    es_fash = d[(d.country == "ES") & (d.category == "FASH")].iloc[0]
    assert cl_elec.units_var_pct < -0.05      # competitor in Chile electronics
    assert cl_elec.price_var_pct < -0.02      # promotional pricing
    assert es_fash.units_var_pct > 0.03       # strong Fashion season in Spain
    o = V.opex_detail(con, V.View(months=["2026-09-01"], countries=["MX"]))
    assert o.set_index("opex_line").loc["Logistics", "var_pct_const_fx"] > 0.08


def test_forecast_overrides_move_the_landing():
    raw = F.load_raw()
    cutoff = C.FORECAST_CYCLES["FC_9+3"]
    base = F.build_forecast(raw, "X", cutoff)["sales"]
    up = F.build_forecast(raw, "X", cutoff, F.Overrides(volume_pct=10))["sales"]
    closed = base.month <= pd.Timestamp(cutoff)
    # closed months untouched, open months +10% units
    assert (up[closed.values].units.values == base[closed].units.values).all()
    ratio = up[~closed.values].units.sum() / base[~closed].units.sum()
    assert ratio == pytest.approx(1.10, rel=0.001)


def test_commentary_mentions_main_story(con):
    text = " ".join(K.generate(con, V.View()))
    assert "below budget" in text
    assert "Chile" in text and "Mexico" in text
