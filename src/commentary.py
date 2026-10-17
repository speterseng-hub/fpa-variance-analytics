"""Automated variance commentary for management packs.

Turns the bridge into the kind of bullet points an FP&A analyst writes for
the CFO: headline, main drivers with their operational explanation, offsets
and what to watch. Rule-based and deterministic, so every sentence can be
traced back to a number in the warehouse.
"""
from __future__ import annotations

import pandas as pd

from src import config as C
from src import variance as V

SCENARIO_LABEL = {"BUDGET": "budget", "ACTUAL": "actuals", "FC_3+9": "the 3+9 forecast",
                  "FC_6+6": "the 6+6 forecast", "FC_9+3": "the 9+3 forecast"}


def eur(x: float, signed: bool = False) -> str:
    sign = ("+" if x > 0 else "−" if x < 0 else "") if signed else ("−" if x < 0 else "")
    a = abs(x)
    return f"{sign}€{a / 1e6:,.1f}m" if a >= 1e5 else f"{sign}€{a / 1e3:,.0f}k"


def pct(x: float, signed: bool = True) -> str:
    txt = f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"
    return txt.replace("-", "−")


def _explain(row: pd.Series, sales: pd.DataFrame, opex: pd.DataFrame, hc: pd.DataFrame) -> str:
    """One operational explanation for a driver x country impact."""
    c, d = row["country"], row["driver"]
    name = C.COUNTRIES[c]["name"]
    s = sales[sales.country == c]
    cat_name = lambda k: C.CATEGORIES[k]["name"]
    if d in ("Volume", "Mix", "Price", "Unit cost"):
        col = {"Volume": "units_var_pct", "Mix": "units_var_pct", "Price": "price_var_pct", "Unit cost": "unit_cost_var_pct"}[d]
        top = s.reindex(s[col].abs().sort_values(ascending=False).index).iloc[0]
        what = {"Volume": "units", "Mix": "units", "Price": "average selling price", "Unit cost": "unit cost"}[d]
        extra = ""
        if d == "Mix":
            up = s.sort_values("units_var_pct").iloc[-1]
            dn = s.sort_values("units_var_pct").iloc[0]
            return (f"{name} mix: {cat_name(up.category)} units {pct(up.units_var_pct)} vs "
                    f"{cat_name(dn.category)} {pct(dn.units_var_pct)}, shifting sales towards lower or higher margin-per-unit categories")
        return f"{name} {d.lower()}: {cat_name(top.category)} {what} {pct(top[col])}{extra}"
    if d == "FX":
        fxv = s.fx_var_pct.mean()
        ccy = C.COUNTRIES[c]["currency"]
        move = "weaker" if fxv > 0 else "stronger"
        return f"{name} FX translation: {ccy} {abs(fxv) * 100:.1f}% {move} than the reference rate"
    if d.startswith("Opex: "):
        line = d.replace("Opex: ", "")
        o = opex[(opex.country == c) & (opex.opex_line == line)]
        txt = f"{name} {line} cost {pct(o.var_pct_const_fx.iloc[0])} at constant FX" if len(o) else f"{name} {line}"
        if line == "Personnel":
            h = hc[hc.country == c]
            if len(h) and h.fte_base.iloc[0]:
                txt += f" (average FTE {h.fte_comp.iloc[0]:,.0f} vs {h.fte_base.iloc[0]:,.0f})"
        return txt
    return f"{name} {d.lower()}"


def generate(con, v: V.View, period_label: str = "YTD", top_n: int = 3) -> list[str]:
    base_label = SCENARIO_LABEL.get(v.base, v.base)
    if v.offset == 12:
        base_label = "prior year"
    kb = V.kpis(con, v.base, v.base_months, v.countries)
    ka = V.kpis(con, v.comp, v.months, v.countries)
    gap = ka["ebitda"] - kb["ebitda"]
    direction = "above" if gap >= 0 else "below"

    br = V.bridge(con, v, by="country")
    br = br[br.impact_eur.abs() > 1]
    sales = V.sales_detail(con, v)
    opex = V.opex_detail(con, v)
    hc = V.headcount(con, v)
    rev = V.revenue_bridge(con, v).iloc[0]

    out = [
        f"**{period_label} EBITDA {eur(ka['ebitda'])}, {eur(abs(gap))} ({pct(gap / abs(kb['ebitda']))}) {direction} "
        f"{base_label}.** EBITDA margin {pct(ka['ebitda_pct'], False)} vs {pct(kb['ebitda_pct'], False)}.",
        f"Net revenue {eur(ka['revenue'])} ({pct(ka['revenue'] / kb['revenue'] - 1)}): volume {eur(rev['Volume'], True)}, "
        f"mix {eur(rev['Mix'], True)}, price {eur(rev['Price'], True)}, FX {eur(rev['FX'], True)}.",
    ]

    neg = br[br.impact_eur < 0].sort_values("impact_eur").head(top_n)
    pos = br[br.impact_eur > 0].sort_values("impact_eur", ascending=False).head(2)
    if len(neg):
        out.append("**Main headwinds**")
        out += [f"- {eur(r.impact_eur, True)} · {_explain(r, sales, opex, hc)}." for _, r in neg.iterrows()]
    if len(pos):
        out.append("**Partly offset by**")
        out += [f"- {eur(r.impact_eur, True)} · {_explain(r, sales, opex, hc)}." for _, r in pos.iterrows()]

    # Group-wide themes: a driver pushing the same way in every country
    n = len(v.countries)
    if n > 1:
        for drv, g in br.groupby("driver"):
            tot = g.impact_eur.sum()
            same_sign = g.impact_eur.lt(0).all() or g.impact_eur.gt(0).all()
            spread = g.impact_eur.abs().max() < 0.6 * abs(tot)  # not driven by a single country
            if len(g) == n and same_sign and spread and abs(tot) > 0.1 * abs(gap):
                note = ""
                if drv == "Unit cost":
                    k = sales.groupby("category").unit_cost_var_pct.mean().sort_values().index[-1]
                    note = f": {C.CATEGORIES[k]['name']} unit cost up {pct(sales[sales.category == k].unit_cost_var_pct.mean())} on average"
                out.append(f"Group-wide theme: {drv.lower()} {eur(tot, True)}, "
                           f"{'adverse' if tot < 0 else 'favourable'} in all {n} countries{note}.")

    # Concentration: how much of the gap the top country explains
    by_c = br.groupby("country").impact_eur.sum().sort_values()
    worst = by_c.index[0]
    if n > 1 and gap < 0 and by_c.iloc[0] < 0:
        out.append(f"{C.COUNTRIES[worst]['name']} explains {abs(by_c.iloc[0]) / abs(gap) * 100:.0f}% "
                   f"of the EBITDA gap ({eur(by_c.iloc[0], True)}).")
    return out


if __name__ == "__main__":
    con = V.connect()
    for line in generate(con, V.View()):
        print(line)
