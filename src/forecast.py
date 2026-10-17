"""Driver-based rolling forecast engine.

For a forecast cycle with cut-off month *k* (e.g. 9+3 -> September):

* months 1..k are ACTUALS;
* months k+1..12 are projected from the BUDGET drivers, corrected with
  run-rate indices measured on the last three closed months:

  - units          = budget units x volume index (actual / budget units)
  - price          = budget price x price index
  - unit cost      = budget unit cost x unit cost index
  - personnel      = last actual FTE x budget cost per FTE x cost index
  - logistics      = forecast units x actual logistics cost per unit
  - marketing, rent, IT = budget x run-rate index
  - FX             = last closed month spot rate

Management overrides (what-if levers used in the dashboard) are applied on
top of the run-rate: volume %, price %, unit cost %, FTE %, FX %.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src import config as C

KEY_SALES = ["country", "category"]


@dataclass
class Overrides:
    volume_pct: float = 0.0     # +5 = +5% units on forecast months
    price_pct: float = 0.0
    unit_cost_pct: float = 0.0
    fte_pct: float = 0.0
    fx_pct: float = 0.0         # +10 = local currencies 10% weaker vs EUR
    countries: tuple[str, ...] | None = None  # None = all countries

    def applies(self, country: str) -> bool:
        return self.countries is None or country in self.countries


def load_raw() -> dict[str, pd.DataFrame]:
    out = {}
    for name in ["sales", "opex", "headcount", "fx_rates", "dim_country"]:
        df = pd.read_csv(C.DATA_RAW / f"{name}.csv")
        if "month" in df:
            df["month"] = pd.to_datetime(df["month"])
        out[name] = df
    return out


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.where(den != 0)).fillna(1.0)


def build_forecast(raw: dict[str, pd.DataFrame], cycle: str, cutoff: str,
                   ov: Overrides | None = None, year: int = 2026) -> dict[str, pd.DataFrame]:
    ov = ov or Overrides()
    cutoff = pd.Timestamp(cutoff)
    window = pd.date_range(cutoff - pd.DateOffset(months=2), cutoff, freq="MS")
    yr = lambda df: df[df["month"].dt.year == year]

    sales, opex, hc, fx = (yr(raw[n]) for n in ["sales", "opex", "headcount", "fx_rates"])
    ccy = raw["dim_country"].set_index("country")["currency"]

    act = lambda df: df[(df.scenario == "ACTUAL") & (df.month <= cutoff)]
    bud_future = lambda df: df[(df.scenario == "BUDGET") & (df.month > cutoff)]
    trailing = lambda df, sc: df[(df.scenario == sc) & (df.month.isin(window))]

    # ---------- sales drivers ----------
    ta = trailing(sales, "ACTUAL").groupby(KEY_SALES)[["units", "net_revenue_lc", "cogs_lc"]].sum()
    tb = trailing(sales, "BUDGET").groupby(KEY_SALES)[["units", "net_revenue_lc", "cogs_lc"]].sum()
    idx = pd.DataFrame({
        "vol": _ratio(ta.units, tb.units),
        "price": _ratio(ta.net_revenue_lc / ta.units, tb.net_revenue_lc / tb.units),
        "cost": _ratio(ta.cogs_lc / ta.units, tb.cogs_lc / tb.units),
    }).reset_index()

    fs = bud_future(sales).merge(idx, on=KEY_SALES, how="left")
    lever = fs["country"].map(ov.applies)
    k = lambda pct: 1 + lever * pct / 100
    price_b = fs.net_revenue_lc / fs.units
    cost_b = fs.cogs_lc / fs.units
    fs["units"] = (fs.units * fs.vol * k(ov.volume_pct)).round().astype(int)
    fs["net_revenue_lc"] = (fs.units * price_b * fs.price * k(ov.price_pct)).round(2)
    fs["cogs_lc"] = (fs.units * cost_b * fs.cost * k(ov.unit_cost_pct)).round(2)
    sales_fc = pd.concat([act(sales), fs[sales.columns]]).assign(scenario=cycle)

    # ---------- headcount ----------
    last_fte = act(hc)[act(hc).month == cutoff].set_index("country")["fte"]
    fh = bud_future(hc).copy()
    fh["fte"] = (fh.country.map(last_fte) * (1 + fh.country.map(ov.applies) * ov.fte_pct / 100)).round(1)
    hc_fc = pd.concat([act(hc), fh]).assign(scenario=cycle)

    # ---------- opex ----------
    oa = trailing(opex, "ACTUAL").groupby(["country", "opex_line"]).amount_lc.sum()
    ob = trailing(opex, "BUDGET").groupby(["country", "opex_line"]).amount_lc.sum()
    o_idx = _ratio(oa, ob).rename("idx").reset_index()
    fo = bud_future(opex).merge(o_idx, on=["country", "opex_line"], how="left")
    fo["amount_lc"] = fo.amount_lc * fo.idx

    # Personnel = forecast FTE x actual cost per FTE (trailing)
    hca = trailing(hc, "ACTUAL").groupby("country").fte.sum()
    pers_a = oa.xs("Personnel", level="opex_line")
    cost_per_fte = pers_a / hca
    fte_map = fh.set_index(["country", "month"]).fte
    m = fo.opex_line == "Personnel"
    fo.loc[m, "amount_lc"] = [fte_map[(c, mo)] * cost_per_fte[c] for c, mo in zip(fo.loc[m, "country"], fo.loc[m, "month"])]

    # Logistics = forecast units x actual cost per unit (trailing)
    units_a = trailing(sales, "ACTUAL").groupby("country").units.sum()
    log_rate = oa.xs("Logistics", level="opex_line") / units_a
    fc_units = fs.groupby(["country", "month"]).units.sum()
    m = fo.opex_line == "Logistics"
    fo.loc[m, "amount_lc"] = [fc_units[(c, mo)] * log_rate[c] for c, mo in zip(fo.loc[m, "country"], fo.loc[m, "month"])]

    # Marketing keeps its run-rate share of revenue
    rev_fc = fs.groupby(["country", "month"]).net_revenue_lc.sum()
    rev_b = bud_future(sales).groupby(["country", "month"]).net_revenue_lc.sum()
    m = fo.opex_line == "Marketing"
    fo.loc[m, "amount_lc"] = [a * rev_fc[(c, mo)] / rev_b[(c, mo)]
                              for a, c, mo in zip(fo.loc[m, "amount_lc"], fo.loc[m, "country"], fo.loc[m, "month"])]
    fo["amount_lc"] = fo.amount_lc.round(2)
    opex_fc = pd.concat([act(opex), fo[opex.columns]]).assign(scenario=cycle)

    # ---------- FX: last spot rate, plus optional shock ----------
    spot = act(fx)[act(fx).month == cutoff].set_index("currency").rate_per_eur
    ffx = bud_future(fx).copy()
    shocked = ffx.currency.map(lambda c: any(ov.applies(k) and ccy[k] == c for k in ccy.index))
    ffx["rate_per_eur"] = ffx.currency.map(spot) * (1 + shocked * (ffx.currency != "EUR") * ov.fx_pct / 100)
    fx_fc = pd.concat([act(fx), ffx]).assign(scenario=cycle)

    return {"sales": sales_fc, "opex": opex_fc, "headcount": hc_fc, "fx_rates": fx_fc}


def build_all_cycles(raw: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    raw = raw or load_raw()
    parts = [build_forecast(raw, cycle, cutoff) for cycle, cutoff in C.FORECAST_CYCLES.items()]
    return {name: pd.concat([p[name] for p in parts], ignore_index=True) for name in parts[0]}


def main() -> None:
    C.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = build_all_cycles()
    for name, df in out.items():
        df.assign(month=df.month.dt.strftime("%Y-%m-%d")).to_csv(C.DATA_PROCESSED / f"{name}_forecast.csv", index=False)
    print(f"Forecast cycles {list(C.FORECAST_CYCLES)} written to {C.DATA_PROCESSED}")


if __name__ == "__main__":
    main()
