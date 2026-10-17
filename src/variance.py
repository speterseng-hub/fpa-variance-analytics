"""Python access layer over the DuckDB warehouse: KPIs, P&L and variance bridges.

Every function takes the same filter set, so the dashboard, the commentary
engine and the tests read numbers in exactly the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import pandas as pd

from src import config as C

PNL_ORDER = ["Net revenue", "COGS", "Gross margin", "Personnel", "Marketing", "Logistics",
             "Rent & Occupancy", "IT & Technology", "Total opex", "EBITDA"]


@dataclass
class View:
    """A comparison: `comp` scenario vs `base` scenario over `months` (comp periods)."""
    base: str = "BUDGET"
    comp: str = "ACTUAL"
    months: list[str] = field(default_factory=lambda: [f"2026-{m:02d}-01" for m in range(1, 10)])
    countries: list[str] = field(default_factory=lambda: list(C.COUNTRIES))
    offset: int = 0  # 12 when base is prior-year actuals

    @property
    def base_months(self) -> list[str]:
        return [(pd.Timestamp(m) - pd.DateOffset(months=self.offset)).strftime("%Y-%m-%d") for m in self.months]


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not C.WAREHOUSE.exists():
        from src import pipeline
        pipeline.run(generate=not (C.DATA_RAW / "sales.csv").exists())
    return duckdb.connect(str(C.WAREHOUSE), read_only=read_only)


def _filters(months: list[str], countries: list[str]) -> str:
    m = ", ".join(f"DATE '{x}'" for x in months)
    c = ", ".join(f"'{x}'" for x in countries)
    return f"month IN ({m}) AND country IN ({c})"


def kpis(con, scenario: str, months: list[str], countries: list[str]) -> dict:
    row = con.execute(f"""
        SELECT SUM(units), SUM(revenue_eur), SUM(gross_margin_eur), SUM(opex_eur), SUM(ebitda_eur), AVG(fte_sum)
        FROM (SELECT month, SUM(units) units, SUM(revenue_eur) revenue_eur, SUM(gross_margin_eur) gross_margin_eur,
                     SUM(opex_eur) opex_eur, SUM(ebitda_eur) ebitda_eur, SUM(fte) fte_sum
              FROM mart_kpi_monthly WHERE scenario = ? AND {_filters(months, countries)} GROUP BY month)
    """, [scenario]).fetchone()
    keys = ["units", "revenue", "gross_margin", "opex", "ebitda", "fte"]
    d = dict(zip(keys, [float(x or 0) for x in row]))
    d["gm_pct"] = d["gross_margin"] / d["revenue"] if d["revenue"] else 0.0
    d["ebitda_pct"] = d["ebitda"] / d["revenue"] if d["revenue"] else 0.0
    return d


def pnl(con, v: View) -> pd.DataFrame:
    """P&L with base, comp, variance and variance % (costs shown as negatives)."""
    def one(scenario, months):
        df = con.execute(f"""
            SELECT pnl_line, SUM(amount_eur) AS amount FROM fct_pnl
            WHERE scenario = ? AND {_filters(months, v.countries)} GROUP BY 1""", [scenario]).df()
        s = df.set_index("pnl_line")["amount"]
        s["Gross margin"] = s["Net revenue"] + s["COGS"]
        s["Total opex"] = sum(s[x] for x in C.OPEX_LINES)
        s["EBITDA"] = s["Gross margin"] + s["Total opex"]
        return s
    out = pd.DataFrame({"base": one(v.base, v.base_months), "comp": one(v.comp, v.months)}).reindex(PNL_ORDER)
    out["variance"] = out["comp"] - out["base"]
    out["variance_pct"] = out["variance"] / out["base"].abs()
    return out


def bridge(con, v: View, by: str | None = None) -> pd.DataFrame:
    """EBITDA bridge from base to comp. `by` = None | 'country' | 'detail'."""
    extra = f", {by}" if by else ""
    return con.execute(f"""
        SELECT driver, MIN(driver_order) AS driver_order{extra}, SUM(impact_eur) AS impact_eur
        FROM ebitda_bridge(?, ?, ?)
        WHERE {_filters(v.months, v.countries)}
        GROUP BY driver{extra} ORDER BY driver_order{extra}
    """, [v.base, v.comp, v.offset]).df()


def revenue_bridge(con, v: View) -> pd.DataFrame:
    return con.execute(f"""
        SELECT SUM(revenue_base) AS base, SUM(rev_volume) AS "Volume", SUM(rev_mix) AS "Mix",
               SUM(rev_price) AS "Price", SUM(rev_fx) AS "FX", SUM(revenue_comp) AS comp
        FROM sales_bridge(?, ?, ?) WHERE {_filters(v.months, v.countries)}
    """, [v.base, v.comp, v.offset]).df()


def sales_detail(con, v: View) -> pd.DataFrame:
    """Country x category drivers: units %, price %, unit cost %, FX % and GM impact."""
    return con.execute(f"""
        WITH b AS (
            SELECT country, category, SUM(units) u, SUM(net_revenue_lc) r, SUM(cogs_lc) c,
                   SUM(revenue_eur) reur, SUM(net_revenue_lc) / SUM(revenue_eur) fx
            FROM fct_sales WHERE scenario = ? AND {_filters(v.base_months, v.countries)} GROUP BY ALL),
        a AS (
            SELECT country, category, SUM(units) u, SUM(net_revenue_lc) r, SUM(cogs_lc) c,
                   SUM(revenue_eur) reur, SUM(net_revenue_lc) / SUM(revenue_eur) fx
            FROM fct_sales WHERE scenario = ? AND {_filters(v.months, v.countries)} GROUP BY ALL),
        g AS (
            SELECT country, category, SUM(gm_comp - gm_base) gm_var
            FROM sales_bridge(?, ?, ?) WHERE {_filters(v.months, v.countries)} GROUP BY ALL)
        SELECT a.country, a.category,
               a.u / b.u - 1 AS units_var_pct,
               (a.r / a.u) / (b.r / b.u) - 1 AS price_var_pct,
               (a.c / a.u) / (b.c / b.u) - 1 AS unit_cost_var_pct,
               a.fx / b.fx - 1 AS fx_var_pct,
               a.reur - b.reur AS revenue_var_eur,
               g.gm_var AS gm_var_eur
        FROM a JOIN b USING (country, category) JOIN g USING (country, category)
    """, [v.base, v.comp, v.base, v.comp, v.offset]).df()


def opex_detail(con, v: View) -> pd.DataFrame:
    return con.execute(f"""
        SELECT country, opex_line, SUM(opex_base) AS base_eur, SUM(opex_comp) AS comp_eur,
               SUM(opex_var_const_fx) AS var_const_fx_eur,
               -SUM(opex_var_const_fx) / NULLIF(SUM(opex_base), 0) AS var_pct_const_fx
        FROM opex_bridge(?, ?, ?) WHERE {_filters(v.months, v.countries)} GROUP BY ALL
    """, [v.base, v.comp, v.offset]).df()


def headcount(con, v: View) -> pd.DataFrame:
    return con.execute(f"""
        SELECT country,
               AVG(CASE WHEN scenario = ? THEN fte END) AS fte_comp,
               AVG(CASE WHEN scenario = ? THEN fte END) AS fte_base
        FROM stg_headcount
        WHERE (scenario = ? AND {_filters(v.months, v.countries)})
           OR (scenario = ? AND {_filters(v.base_months, v.countries)})
        GROUP BY country
    """, [v.comp, v.base, v.comp, v.base]).df()


def trend(con, scenarios: list[str], countries: list[str], metric: str = "ebitda_eur") -> pd.DataFrame:
    c = ", ".join(f"'{x}'" for x in countries)
    s = ", ".join(f"'{x}'" for x in scenarios)
    return con.execute(f"""
        SELECT scenario, month, SUM({metric}) AS value FROM mart_kpi_monthly
        WHERE scenario IN ({s}) AND country IN ({c}) GROUP BY ALL ORDER BY month
    """).df()


def forecast_accuracy(con) -> pd.DataFrame:
    """Weighted absolute % error of budget, 3+9 and 6+6 vs actuals on Jul-Sep 2026 (forecast months for all three)."""
    return con.execute("""
        WITH fc AS (
            SELECT f.scenario, f.country, f.month, f.revenue_eur AS fc_rev, a.revenue_eur AS act_rev,
                   f.ebitda_eur AS fc_ebitda, a.ebitda_eur AS act_ebitda
            FROM mart_kpi_monthly f
            JOIN mart_kpi_monthly a ON a.scenario = 'ACTUAL' AND a.month = f.month AND a.country = f.country
            WHERE f.scenario IN ('FC_3+9', 'FC_6+6') AND f.month BETWEEN DATE '2026-07-01' AND DATE '2026-09-01'
            UNION ALL
            SELECT 'BUDGET', b.country, b.month, b.revenue_eur, a.revenue_eur, b.ebitda_eur, a.ebitda_eur
            FROM mart_kpi_monthly b
            JOIN mart_kpi_monthly a ON a.scenario = 'ACTUAL' AND a.month = b.month AND a.country = b.country
            WHERE b.scenario = 'BUDGET' AND b.month BETWEEN DATE '2026-07-01' AND DATE '2026-09-01'
        )
        SELECT scenario, country,
               SUM(ABS(fc_rev - act_rev)) / SUM(act_rev)          AS revenue_wape,
               SUM(ABS(fc_ebitda - act_ebitda)) / SUM(act_ebitda) AS ebitda_wape,
               SUM(fc_ebitda - act_ebitda)                       AS ebitda_bias_eur,
               COUNT(DISTINCT month)                             AS months_evaluated
        FROM fc GROUP BY ALL ORDER BY scenario, country
    """).df()
