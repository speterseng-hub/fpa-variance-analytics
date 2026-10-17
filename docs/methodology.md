# Methodology

## Scenarios and FX

| Scenario | Months | FX used for EUR translation |
|---|---|---|
| `BUDGET` | Jan 2025 – Dec 2026 | Budget rate per year (flat) |
| `ACTUAL` | Jan 2025 – Sep 2026 | Monthly average actual rate |
| `FC_3+9`, `FC_6+6`, `FC_9+3` | Jan – Dec 2026 | Actual rate for closed months, last spot rate for open months |

Comparisons vs prior year use `ACTUAL` shifted by 12 months (`offset = 12`), so the FX effect
there is the translation difference between this year's and last year's rates.

## Variance bridge

The bridge is computed in SQL ([`sql/03_variance_bridge.sql`](../sql/03_variance_bridge.sql)) as
DuckDB table macros, so any pair of scenarios can be compared:

```sql
SELECT driver, SUM(impact_eur)
FROM ebitda_bridge('BUDGET', 'ACTUAL', 0)
WHERE month BETWEEN DATE '2026-01-01' AND DATE '2026-09-01'
GROUP BY driver;
```

* **Volume and mix** use the base unit margin, so a shift towards categories that earn less per
  unit shows as negative mix even when their GM% is higher (Beauty in Peru is an example).
* **Price and unit cost** are measured in local currency and converted at the base rate, so they
  are free of FX noise.
* **FX** is applied to the actual local-currency value; it is zero for Spain (EUR).
* **Opex** variance is shown at constant currency per line, with its FX effect added to the FX bar.

Sign convention: positive = favourable to EBITDA.

## Driver-based rolling forecast

For a cycle with cut-off month *k* ([`src/forecast.py`](../src/forecast.py)):

| Driver | Projection for months k+1…12 |
|---|---|
| Units | Budget units × (actual ÷ budget units, last 3 closed months) |
| Price, unit cost | Budget × run-rate index on the last 3 closed months |
| Personnel | Last actual FTE × actual cost per FTE |
| Logistics | Forecast units × actual cost per unit |
| Marketing | Run-rate index × budget, scaled with forecast revenue |
| Rent, IT | Budget × run-rate index |
| FX | Spot rate at cut-off |

The dashboard levers (volume, price, unit cost, FTE, FX) apply on top of the run-rate for the
selected countries and only on open months. Closed months are never restated, and a quality
check enforces this.

**Forecast accuracy** is measured as the weighted absolute percentage error (WAPE) of monthly
EBITDA on Jul–Sep 2026, a window that all three of budget, 3+9 and 6+6 had to forecast.

## Data quality checks

Ten checks in [`sql/04_quality_checks.sql`](../sql/04_quality_checks.sql) run on every build and
in CI: FX coverage, completeness of the budget, forecast and opex grids, sanity of
units, revenue and margins, three bridge reconciliations, and the integrity of closed forecast months.
