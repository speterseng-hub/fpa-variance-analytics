"""Generate a synthetic, reproducible FP&A dataset for a fictional retail group.

The output mimics what an FP&A team extracts from the ERP / EPM tools:
local-currency sales, opex, headcount and FX rates, for the BUDGET and ACTUAL
scenarios. Forecast scenarios are produced afterwards by `src/forecast.py`.

A handful of business events are embedded on purpose, so the variance
analysis has a real story to tell (see `BUSINESS_EVENTS`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config as C

# Multiplicative shocks applied to ACTUALS in 2026 (vs budget drivers).
# (country, category or None, driver, value, first month it applies)
BUSINESS_EVENTS = [
    ("CL", "ELEC", "units", -0.12, 3, "New online competitor in Chile electronics"),
    ("CL", "ELEC", "price", -0.04, 3, "Promotional pricing to defend share"),
    ("CL", None,   "marketing", 0.15, 3, "Extra marketing to answer the competitor"),
    ("ES", "FASH", "units", 0.09, 1, "Strong Fashion season in Spain"),
    ("PE", "BEAU", "units", 0.10, 1, "Mix shift to Beauty in Peru (higher GM%, lower margin per unit)"),
    ("PE", "HOME", "units", -0.05, 1, "Softer Home & DIY demand in Peru"),
    ("MX", None,   "logistics", 0.14, 4, "Carrier tariff increase in Mexico"),
    ("MX", None,   "fte", 0.06, 2, "Unbudgeted hires for new DC in Mexico"),
    (None, "ELEC", "unit_cost", 0.02, 1, "Higher supplier cost on electronics"),
]


def months(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS")


def _shock(country: str, category: str | None, driver: str, month: pd.Timestamp) -> float:
    """Total multiplicative shock (as a +% value) for a driver in a month."""
    if month.year != 2026:
        return 0.0
    total = 0.0
    for c, k, d, v, m0, _ in BUSINESS_EVENTS:
        if d == driver and (c is None or c == country) and (k is None or k == category) and month.month >= m0:
            total += v
    return total


def build_fx(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for _code, cfg in C.COUNTRIES.items():
        for y in C.YEARS:
            fx_b = cfg["fx_budget"][y]
            drift = cfg["fx_drift"] * (1.0 if y == 2026 else 0.4)
            for i, m in enumerate(months(y)):
                rows.append(("BUDGET", m, cfg["currency"], fx_b))
                if m <= pd.Timestamp(C.LAST_CLOSED_MONTH):
                    noise = 0 if cfg["currency"] == "EUR" else rng.normal(0, 0.008)
                    rows.append(("ACTUAL", m, cfg["currency"], fx_b * (1 + drift * (i + 1) / 12 + noise)))
    return pd.DataFrame(rows, columns=["scenario", "month", "currency", "rate_per_eur"])


def build_sales(rng: np.random.Generator, fx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    last = pd.Timestamp(C.LAST_CLOSED_MONTH)
    for code, cfg in C.COUNTRIES.items():
        for y in C.YEARS:
            fx_b = cfg["fx_budget"][y]
            growth = 1.05 ** (y - 2025)          # budget volume growth
            inflation = 1.03 ** (y - 2025)       # budget price increase
            for m in months(y):
                for cat, kcfg in C.CATEGORIES.items():
                    u_b = C.BASE_UNITS_K[code][cat] * 1000 * C.SEASONALITY[m.month] * growth
                    p_b = kcfg["price_eur"] * inflation * fx_b
                    c_b = p_b * (1 - kcfg["gm_pct"])
                    rows.append(("BUDGET", m, code, cat, round(u_b), round(u_b) * p_b, round(u_b) * c_b))
                    if m > last:
                        continue
                    u_a = u_b * (1 + _shock(code, cat, "units", m)) * rng.normal(1.0, 0.03)
                    p_a = p_b * (1 + _shock(code, cat, "price", m)) * rng.normal(1.0, 0.01)
                    c_a = c_b * (1 + _shock(code, cat, "unit_cost", m)) * rng.normal(1.0, 0.008)
                    u_a = round(u_a)
                    rows.append(("ACTUAL", m, code, cat, u_a, u_a * p_a, u_a * c_a))
    df = pd.DataFrame(rows, columns=["scenario", "month", "country", "category", "units", "net_revenue_lc", "cogs_lc"])
    df[["net_revenue_lc", "cogs_lc"]] = df[["net_revenue_lc", "cogs_lc"]].round(2)
    return df


def build_headcount_opex(rng: np.random.Generator, sales: pd.DataFrame):
    hc_rows, opex_rows = [], []
    last = pd.Timestamp(C.LAST_CLOSED_MONTH)
    o = C.OPEX
    rev = sales.groupby(["scenario", "month", "country"], as_index=False)[["net_revenue_lc", "units"]].sum()
    rev = rev.set_index(["scenario", "month", "country"])
    for code, cfg in C.COUNTRIES.items():
        for y in C.YEARS:
            fx_b = cfg["fx_budget"][y]
            wage = 1.04 ** (y - 2025)
            for m in months(y):
                b = rev.loc[("BUDGET", m, code)]
                fte_b = o["fte_budget"][code] * (1.02 ** (y - 2025))
                budget = {
                    "Personnel": fte_b * o["cost_per_fte_month"][code] * wage * fx_b,
                    "Marketing": b["net_revenue_lc"] * o["marketing_pct_rev"],
                    "Logistics": b["units"] * o["logistics_per_unit"][code] * fx_b,
                    "Rent & Occupancy": o["rent_month"][code] * fx_b,
                    "IT & Technology": o["it_month"][code] * fx_b,
                }
                hc_rows.append(("BUDGET", m, code, round(fte_b, 1)))
                for line, amt in budget.items():
                    opex_rows.append(("BUDGET", m, code, line, round(amt, 2)))
                if m > last:
                    continue
                a = rev.loc[("ACTUAL", m, code)]
                fte_a = fte_b * (1 + _shock(code, None, "fte", m)) * rng.normal(1.0, 0.006)
                actual = {
                    "Personnel": fte_a * o["cost_per_fte_month"][code] * wage * fx_b * rng.normal(1.0, 0.01),
                    "Marketing": budget["Marketing"] * (1 + _shock(code, None, "marketing", m)) * rng.normal(1.0, 0.04),
                    "Logistics": a["units"] * o["logistics_per_unit"][code] * fx_b
                                 * (1 + _shock(code, None, "logistics", m)) * rng.normal(1.0, 0.015),
                    "Rent & Occupancy": budget["Rent & Occupancy"] * rng.normal(1.0, 0.005),
                    "IT & Technology": budget["IT & Technology"] * rng.normal(1.0, 0.03),
                }
                hc_rows.append(("ACTUAL", m, code, round(fte_a, 1)))
                for line, amt in actual.items():
                    opex_rows.append(("ACTUAL", m, code, line, round(amt, 2)))
    hc = pd.DataFrame(hc_rows, columns=["scenario", "month", "country", "fte"])
    opex = pd.DataFrame(opex_rows, columns=["scenario", "month", "country", "opex_line", "amount_lc"])
    return hc, opex


def dimensions():
    countries = pd.DataFrame(
        [(k, v["name"], v["currency"]) for k, v in C.COUNTRIES.items()],
        columns=["country", "country_name", "currency"],
    )
    categories = pd.DataFrame(
        [(k, v["name"]) for k, v in C.CATEGORIES.items()], columns=["category", "category_name"]
    )
    events = pd.DataFrame(
        [(c or "ALL", k or "ALL", d, v, f"2026-{m0:02d}-01", txt) for c, k, d, v, m0, txt in BUSINESS_EVENTS],
        columns=["country", "category", "driver", "shock_pct", "from_month", "description"],
    )
    return countries, categories, events


def main() -> None:
    rng = np.random.default_rng(C.SEED)
    C.DATA_RAW.mkdir(parents=True, exist_ok=True)
    fx = build_fx(rng)
    sales = build_sales(rng, fx)
    hc, opex = build_headcount_opex(rng, sales)
    countries, categories, events = dimensions()
    out = {"fx_rates": fx, "sales": sales, "headcount": hc, "opex": opex,
           "dim_country": countries, "dim_category": categories, "business_events": events}
    for name, df in out.items():
        if "month" in df:
            df = df.assign(month=pd.to_datetime(df["month"]).dt.strftime("%Y-%m-%d"))
        if "rate_per_eur" in df:
            df = df.assign(rate_per_eur=df["rate_per_eur"].round(6))
        df.to_csv(C.DATA_RAW / f"{name}.csv", index=False)
    print(f"Raw data written to {C.DATA_RAW} ({len(sales):,} sales rows, {len(opex):,} opex rows)")


if __name__ == "__main__":
    main()
