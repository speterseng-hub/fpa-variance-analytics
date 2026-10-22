"""FP&A Variance Analytics - interactive management dashboard.

Run locally:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import commentary as K
from src import config as C
from src import forecast as F
from src import variance as V

st.set_page_config(page_title="FP&A Variance Analytics", page_icon="📊", layout="wide")

# ---------- design tokens (validated categorical + diverging palette) ----------
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
FAV, ADV, TOTAL = "#2a78d6", "#e34948", "#52514e"          # diverging poles + neutral
SERIES = {"ACTUAL": "#2a78d6", "BUDGET": "#eb6834", "FC_9+3": "#1baf7a", "FC_6+6": "#6250d6", "FC_3+9": "#e87ba4"}
LABEL = {"ACTUAL": "Actual", "BUDGET": "Budget", "FC_3+9": "Forecast 3+9", "FC_6+6": "Forecast 6+6", "FC_9+3": "Forecast 9+3"}
FONT = dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=13)
MONTHS_2026 = [f"2026-{m:02d}-01" for m in range(1, 13)]
CLOSED = [m for m in MONTHS_2026 if m <= C.LAST_CLOSED_MONTH]

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.7rem;}
  .commentary p, .commentary li {font-size: 0.97rem; line-height: 1.5;}
  .small-note {color: #898781; font-size: 0.85rem;}
</style>""", unsafe_allow_html=True)


def layout(fig: go.Figure, height: int = 420, **kw) -> go.Figure:
    fig.update_layout(height=height, font=FONT, plot_bgcolor="#fcfcfb", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=40, b=10), hoverlabel=dict(font=FONT, bgcolor="white"),
                      legend=dict(orientation="h", y=1.08, x=0, title=None), **kw)
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor=AXIS, tickfont=dict(color=MUTED))
    return fig


def m_eur(x: float) -> str:
    return f"€{x / 1e6:,.1f}m"


def d_eur(x: float) -> str | None:
    """Signed delta; a leading ASCII '-' lets st.metric colour it correctly."""
    if abs(x) < 5e4:
        return None
    return f"{'-' if x < 0 else '+'}€{abs(x) / 1e6:,.1f}m"


def vs(delta: str | None, ref: str) -> str | None:
    return f"{delta} vs {ref}" if delta else None


# ---------- cached data access ----------
@st.cache_data(show_spinner="Building warehouse…")
def q(fn: str, **kw):
    con = V.connect()
    try:
        if fn == "commentary":
            return K.generate(con, V.View(**kw.pop("view")), **kw)
        if fn in ("kpis", "trend"):
            return getattr(V, fn)(con, **kw)
        if fn in ("forecast_accuracy",):
            return getattr(V, fn)(con)
        if fn == "checks":
            return con.execute("SELECT check_name, status, detail FROM quality_checks").df()
        if fn == "events":
            return con.execute("SELECT * FROM business_events").df()
        view = V.View(**kw.pop("view"))
        return getattr(V, fn)(con, view, **kw)
    finally:
        con.close()


@st.cache_data
def scenario_landing(volume, price, unit_cost, fte, fx, countries):
    """Re-run the driver-based 9+3 forecast with management overrides, return FY KPIs in EUR."""
    raw = F.load_raw()
    ov = F.Overrides(volume, price, unit_cost, fte, fx, tuple(countries))
    fc = F.build_forecast(raw, "SCENARIO", C.FORECAST_CYCLES["FC_9+3"], ov)
    ccy = raw["dim_country"][["country", "currency"]]
    fxr = fc["fx_rates"][["month", "currency", "rate_per_eur"]]
    s = fc["sales"].merge(ccy, on="country").merge(fxr, on=["month", "currency"])
    o = fc["opex"].merge(ccy, on="country").merge(fxr, on=["month", "currency"])
    s, o = s[s.country.isin(countries)], o[o.country.isin(countries)]
    rev = (s.net_revenue_lc / s.rate_per_eur).sum()
    gm = ((s.net_revenue_lc - s.cogs_lc) / s.rate_per_eur).sum()
    opex = (o.amount_lc / o.rate_per_eur).sum()
    return {"revenue": rev, "gross_margin": gm, "opex": opex, "ebitda": gm - opex}


# ---------- sidebar ----------
st.sidebar.title("📊 FP&A Variance Analytics")
st.sidebar.caption(C.COMPANY + " · synthetic data · EUR")

COMPARISONS = {
    "Actual vs Budget": dict(base="BUDGET", comp="ACTUAL", offset=0),
    "Actual vs Prior year": dict(base="ACTUAL", comp="ACTUAL", offset=12),
    "Actual vs Forecast 6+6": dict(base="FC_6+6", comp="ACTUAL", offset=0),
    "FY landing (Forecast 9+3) vs Budget": dict(base="BUDGET", comp="FC_9+3", offset=0),
}
comparison = st.sidebar.radio("Comparison", list(COMPARISONS))
cfg = COMPARISONS[comparison]

if comparison.startswith("FY landing"):
    months, period_label = MONTHS_2026, "FY 2026 landing"
    st.sidebar.info("Jan–Sep actuals + Oct–Dec driver-based forecast.")
else:
    options = CLOSED if cfg["base"] != "FC_6+6" else [m for m in CLOSED if m > "2026-06-01"]
    month = st.sidebar.select_slider("Closing month", options=options, value=options[-1],
                                     format_func=lambda m: pd.Timestamp(m).strftime("%b %Y"))
    period = st.sidebar.radio("Period", ["Year to date", "Month"], horizontal=True)
    start = "2026-07-01" if cfg["base"] == "FC_6+6" else "2026-01-01"
    months = [m for m in options if start <= m <= month] if period == "Year to date" else [month]
    mlabel = pd.Timestamp(month).strftime("%b %Y")
    period_label = f"YTD {mlabel}" if period == "Year to date" else mlabel
    if cfg["base"] == "FC_6+6" and period == "Year to date":
        period_label = f"Jul–{pd.Timestamp(month).strftime('%b')} 2026"

countries_all = list(C.COUNTRIES)
countries = st.sidebar.multiselect("Countries", countries_all, default=countries_all,
                                   format_func=lambda c: C.COUNTRIES[c]["name"]) or countries_all
view = dict(base=cfg["base"], comp=cfg["comp"], months=months, countries=countries, offset=cfg["offset"])
v = V.View(**view)

st.sidebar.markdown("---")
st.sidebar.markdown("Built by **Sebastián Petersen** · [LinkedIn](https://www.linkedin.com/in/sipetersen) · "
                    "[GitHub repo](https://github.com/speterseng-hub/fpa-variance-analytics) · "
                    "Python · SQL (DuckDB) · Streamlit · Power BI")

# ---------- header ----------
st.title("FY 2026 landing · Forecast 9+3 vs Budget" if comparison.startswith("FY landing") else f"{period_label} · {comparison}")
base_lbl = "Prior year" if cfg["offset"] == 12 else LABEL[cfg["base"]]
st.caption(f"{', '.join(C.COUNTRIES[c]['name'] for c in countries)} · EUR · base: {base_lbl}")

tab_over, tab_bridge, tab_drill, tab_fc, tab_dq = st.tabs(
    ["Overview", "Variance bridge", "Country & category", "Forecast & scenarios", "Data quality"])

# ---------- Overview ----------
with tab_over:
    kb = q("kpis", scenario=v.base, months=v.base_months, countries=countries)
    ka = q("kpis", scenario=v.comp, months=months, countries=countries)
    cols = st.columns(5)
    tiles = [
        ("Net revenue", m_eur(ka["revenue"]), f"{(ka['revenue'] / kb['revenue'] - 1) * 100:+.1f}% vs {base_lbl.lower()}", "normal"),
        ("Gross margin %", f"{ka['gm_pct'] * 100:.1f}%", f"{(ka['gm_pct'] - kb['gm_pct']) * 1e4:+.0f} bp", "normal"),
        ("EBITDA", m_eur(ka["ebitda"]), vs(d_eur(ka['ebitda'] - kb['ebitda']), base_lbl.lower()), "normal"),
        ("EBITDA margin", f"{ka['ebitda_pct'] * 100:.1f}%", f"{(ka['ebitda_pct'] - kb['ebitda_pct']) * 1e4:+.0f} bp", "normal"),
        ("Average FTE", f"{ka['fte']:,.0f}", f"{ka['fte'] - kb['fte']:+,.0f} FTE", "inverse"),
    ]
    for col, (lbl, val, delta, dc) in zip(cols, tiles):
        col.metric(lbl, val, delta, delta_color=dc)

    left, right = st.columns([1.05, 1])
    with left:
        st.subheader("Management commentary")
        st.caption("Generated automatically from the variance bridge. Every figure traces back to the warehouse.")
        lines = q("commentary", view=view, period_label=period_label)
        st.markdown('<div class="commentary">\n\n' + "\n".join(
            ln if ln.startswith("-") else f"\n{ln}\n" for ln in lines) + "\n\n</div>", unsafe_allow_html=True)
    with right:
        st.subheader("P&L")
        p = q("pnl", view=view)
        tbl = pd.DataFrame({
            base_lbl: p["base"] / 1e6, LABEL[cfg["comp"]] if cfg["offset"] == 0 else "Actual": p["comp"] / 1e6,
            "Var €m": p["variance"] / 1e6, "Var %": p["variance_pct"] * 100,
        })
        tbl.index.name = None
        bold = {"Gross margin", "Total opex", "EBITDA", "Net revenue"}

        def color(val):
            return f"color: {FAV if val > 0 else ADV if val < 0 else INK2}"
        st.dataframe(
            tbl.style.format({c: "{:,.1f}" for c in tbl.columns[:3]} | {"Var %": "{:+.1f}%"})
               .map(color, subset=["Var €m", "Var %"])
               .apply(lambda r: ["font-weight: 700" if r.name in bold else "" for _ in r], axis=1),
            width="stretch", height=388)
        st.markdown('<span class="small-note">Costs shown as negatives; variance positive = favourable to EBITDA.</span>',
                    unsafe_allow_html=True)

# ---------- Variance bridge ----------
with tab_bridge:
    br = q("bridge", view=view)
    kb = q("kpis", scenario=v.base, months=v.base_months, countries=countries)
    ka = q("kpis", scenario=v.comp, months=months, countries=countries)
    x = [f"{base_lbl} EBITDA"] + br.driver.tolist() + [f"{LABEL[cfg['comp']]} EBITDA"]
    y = [kb["ebitda"]] + br.impact_eur.tolist() + [ka["ebitda"]]
    fig = go.Figure(go.Waterfall(
        x=x, y=[val / 1e6 for val in y], measure=["absolute"] + ["relative"] * len(br) + ["total"],
        increasing=dict(marker=dict(color=FAV)), decreasing=dict(marker=dict(color=ADV)),
        totals=dict(marker=dict(color=TOTAL)), connector=dict(line=dict(color=AXIS, width=1)),
        text=[f"{val / 1e6:+.1f}" if 0 < i < len(y) - 1 else f"{val / 1e6:.1f}" for i, val in enumerate(y)],
        textposition="outside", hovertemplate="%{x}<br>€%{y:,.2f}m<extra></extra>"))
    st.subheader("EBITDA bridge")
    st.caption("Volume, mix, price and unit cost at the base FX rate; opex at constant currency; FX = translation effect. Blue = favourable, red = adverse.")
    run = [kb["ebitda"]]
    for val in br.impact_eur:
        run.append(run[-1] + val)
    lo, hi = min(run + [ka["ebitda"]]) / 1e6, max(run + [ka["ebitda"]]) / 1e6
    pad = max((hi - lo) * 0.25, abs(hi) * 0.02)
    fig = layout(fig, 460, yaxis_title="€m (axis does not start at zero)", showlegend=False)
    fig.update_yaxes(range=[lo - pad * 2, hi + pad])
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.subheader("Driver × country (€m)")
        bc = q("bridge", view=view, by="country")
        piv = bc.pivot_table(index=["driver_order", "driver"], columns="country", values="impact_eur", aggfunc="sum") / 1e6
        piv = piv.droplevel(0)
        piv.index.name = None
        piv.columns = [C.COUNTRIES[c]["name"] for c in piv.columns]
        piv["Total"] = piv.sum(axis=1)
        piv.loc["Total EBITDA variance"] = piv.sum()
        lim = max(piv.drop(index="Total EBITDA variance").drop(columns="Total").abs().max().max(), 0.1)
        st.dataframe(piv.style.format("{:+,.2f}").background_gradient(cmap="RdBu", vmin=-lim, vmax=lim, axis=None)
                     , width="stretch", height=460)
    with c2:
        st.subheader("Revenue bridge")
        rb = q("revenue_bridge", view=view).iloc[0]
        parts = ["Volume", "Mix", "Price", "FX"]
        fig = go.Figure(go.Waterfall(
            x=[f"{base_lbl}"] + parts + [LABEL[cfg["comp"]]],
            y=[rb["base"] / 1e6] + [rb[p] / 1e6 for p in parts] + [rb["comp"] / 1e6],
            measure=["absolute"] + ["relative"] * 4 + ["total"],
            increasing=dict(marker=dict(color=FAV)), decreasing=dict(marker=dict(color=ADV)),
            totals=dict(marker=dict(color=TOTAL)), connector=dict(line=dict(color=AXIS, width=1)),
            text=[f"{rb['base'] / 1e6:,.0f}"] + [f"{rb[p] / 1e6:+.1f}" for p in parts] + [f"{rb['comp'] / 1e6:,.0f}"],
            textposition="outside", hovertemplate="%{x}<br>€%{y:,.2f}m<extra></extra>"))
        lo = min(rb["base"], rb["comp"]) / 1e6
        fig = layout(fig, 460, yaxis_title="€m", showlegend=False)
        fig.update_yaxes(range=[lo * 0.95, max(rb["base"], rb["comp"]) / 1e6 * 1.02])
        st.plotly_chart(fig, width="stretch")

# ---------- Country & category ----------
with tab_drill:
    sd = q("sales_detail", view=view)
    sd["Country"] = sd.country.map(lambda c: C.COUNTRIES[c]["name"])
    sd["Category"] = sd.category.map(lambda k: C.CATEGORIES[k]["name"])
    st.subheader("Operational drivers by country and category")
    st.caption("Change vs base. Price and unit cost in local currency (constant FX); FX = local currency movement (+ = weaker vs EUR).")
    sd = sd.sort_values("gm_var_eur")
    show = sd[["Country", "Category", "units_var_pct", "price_var_pct", "unit_cost_var_pct", "fx_var_pct",
               "revenue_var_eur", "gm_var_eur"]].copy()
    show.columns = ["Country", "Category", "Units %", "Price %", "Unit cost %", "FX %", "Revenue var €m", "GM var €m"]
    for c in ["Units %", "Price %", "Unit cost %", "FX %"]:
        show[c] *= 100
    for c in ["Revenue var €m", "GM var €m"]:
        show[c] /= 1e6
    lim = max(show["GM var €m"].abs().max(), 0.05)
    st.dataframe(show.style.format({"Units %": "{:+.1f}%", "Price %": "{:+.1f}%", "Unit cost %": "{:+.1f}%",
                                    "FX %": "{:+.1f}%", "Revenue var €m": "{:+,.2f}", "GM var €m": "{:+,.2f}"})
                 .background_gradient(cmap="RdBu", vmin=-lim, vmax=lim, subset=["GM var €m"]),
                 width="stretch", hide_index=True, height=420)

    st.subheader("Monthly EBITDA by scenario")
    metric = st.radio("Metric", ["EBITDA", "Net revenue", "Gross margin"], horizontal=True, label_visibility="collapsed")
    col = {"EBITDA": "ebitda_eur", "Net revenue": "revenue_eur", "Gross margin": "gross_margin_eur"}[metric]
    tr = q("trend", scenarios=["ACTUAL", "BUDGET", "FC_9+3"], countries=countries, metric=col)
    fig = go.Figure()
    for sc in ["BUDGET", "FC_9+3", "ACTUAL"]:
        d = tr[tr.scenario == sc]
        if sc == "FC_9+3":
            d = d[d.month >= pd.Timestamp(C.LAST_CLOSED_MONTH)]
        fig.add_trace(go.Scatter(x=d.month, y=d.value / 1e6, name=LABEL[sc], mode="lines+markers",
                                 line=dict(color=SERIES[sc], width=2, dash="dot" if sc != "ACTUAL" else None),
                                 marker=dict(size=8, line=dict(color="#fcfcfb", width=2)),
                                 hovertemplate=f"{LABEL[sc]}<br>%{{x|%b %Y}}: €%{{y:,.1f}}m<extra></extra>"))
    st.plotly_chart(layout(fig, 380, yaxis_title=f"{metric} €m", hovermode="x unified"), width="stretch")

    st.subheader("Opex at constant currency")
    od = q("opex_detail", view=view)
    od["Country"] = od.country.map(lambda c: C.COUNTRIES[c]["name"])
    opv = od.pivot_table(index="opex_line", columns="Country", values="var_pct_const_fx") * 100
    opv = opv.reindex(C.OPEX_LINES)
    opv.index.name = None
    st.dataframe(opv.style.format("{:+.1f}%").background_gradient(cmap="RdBu_r", vmin=-15, vmax=15, axis=None)
                 , width="stretch")
    st.markdown('<span class="small-note">Cost growth vs base; red = overspend.</span>', unsafe_allow_html=True)

# ---------- Forecast & scenarios ----------
with tab_fc:
    st.subheader("What-if on the FY 2026 landing")
    st.caption("Levers apply to the open months (Oct–Dec) of the 9+3 driver-based forecast, for the selected countries.")
    c1, c2, c3, c4, c5 = st.columns(5)
    vol = c1.slider("Volume %", -15, 15, 0)
    prc = c2.slider("Price %", -10, 10, 0)
    uc = c3.slider("Unit cost %", -10, 10, 0)
    fte = c4.slider("FTE %", -10, 10, 0)
    fxs = c5.slider("FX shock %", -15, 15, 0, help="+10 = local currencies 10% weaker vs EUR")
    sc = scenario_landing(vol, prc, uc, fte, fxs, tuple(countries))
    kb_fy = q("kpis", scenario="BUDGET", months=MONTHS_2026, countries=countries)
    kf_fy = q("kpis", scenario="FC_9+3", months=MONTHS_2026, countries=countries)
    a, b, c = st.columns(3)
    a.metric("Budget FY EBITDA", m_eur(kb_fy["ebitda"]))
    b.metric("Forecast 9+3 FY EBITDA", m_eur(kf_fy["ebitda"]), vs(d_eur(kf_fy['ebitda'] - kb_fy['ebitda']), "budget"))
    c.metric("Scenario FY EBITDA", m_eur(sc["ebitda"]), vs(d_eur(sc['ebitda'] - kf_fy['ebitda']), "9+3"))
    fig = go.Figure(go.Bar(
        x=["Budget", "Forecast 9+3", "Scenario"], y=[kb_fy["ebitda"] / 1e6, kf_fy["ebitda"] / 1e6, sc["ebitda"] / 1e6],
        marker=dict(color=[SERIES["BUDGET"], SERIES["FC_9+3"], SERIES["ACTUAL"]], cornerradius=4),
        text=[m_eur(val) for val in [kb_fy["ebitda"], kf_fy["ebitda"], sc["ebitda"]]], textposition="outside",
        hovertemplate="%{x}: €%{y:,.1f}m<extra></extra>", width=0.5))
    st.plotly_chart(layout(fig, 340, yaxis_title="FY EBITDA €m", showlegend=False), width="stretch")

    st.subheader("Forecast accuracy")
    st.caption("Weighted absolute % error of monthly EBITDA vs actuals, on the months each cycle had to forecast. "
               "All cycles measured on the same months (Jul–Sep 2026) for a like-for-like comparison.")
    fa = q("forecast_accuracy")
    fig = go.Figure()
    for scn in ["BUDGET", "FC_3+9", "FC_6+6"]:
        d = fa[fa.scenario == scn]
        fig.add_trace(go.Bar(x=d.country.map(lambda c: C.COUNTRIES[c]["name"]), y=d.ebitda_wape * 100,
                             name=LABEL[scn], marker=dict(color=SERIES[scn], cornerradius=4),
                             hovertemplate=f"{LABEL[scn]}<br>%{{x}}: %{{y:.1f}}%<extra></extra>"))
    fig = layout(fig, 360, barmode="group", yaxis_title="EBITDA error %", bargap=0.25, bargroupgap=0.08)
    st.plotly_chart(fig, width="stretch")

    with st.expander("Business events embedded in the synthetic data (what the analysis should find)"):
        st.dataframe(q("events"), width="stretch", hide_index=True)

# ---------- Data quality ----------
with tab_dq:
    st.subheader("Automated reconciliation checks")
    st.caption("Run on every build (sql/04_quality_checks.sql) and in CI. A failing check stops the pipeline.")
    dq = q("checks")
    dq.insert(0, "", dq.status.map({"PASS": "✅", "FAIL": "❌"}))
    dq.columns = ["", "Check", "Status", "Detail"]
    st.dataframe(dq, width="stretch", hide_index=True)
