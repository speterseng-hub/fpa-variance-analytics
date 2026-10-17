"""Central configuration for the FP&A Variance Analytics project.

All business assumptions of the (fictional) retail group live here, so the
data generator, the forecast engine and the dashboard read the same numbers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
WAREHOUSE = DATA_PROCESSED / "warehouse.duckdb"
SQL_DIR = ROOT / "sql"
POWERBI_DIR = ROOT / "powerbi" / "data"

SEED = 42
REPORTING_CURRENCY = "EUR"
COMPANY = "Andes & Iberia Retail Group (fictional)"

# Fiscal years covered. Actuals are closed up to LAST_CLOSED_MONTH.
YEARS = [2025, 2026]
LAST_CLOSED_MONTH = "2026-09-01"  # 9+3 forecast is the current outlook

# Countries: currency, budget FX rate (local currency per 1 EUR) per year,
# and the actual monthly FX drift vs budget (cumulative %, + = local weakens).
COUNTRIES = {
    "CL": {"name": "Chile",    "currency": "CLP", "fx_budget": {2025: 1010.0, 2026: 1030.0}, "fx_drift": 0.015},
    "PE": {"name": "Peru",     "currency": "PEN", "fx_budget": {2025: 4.05,   2026: 4.10},   "fx_drift": 0.005},
    "CO": {"name": "Colombia", "currency": "COP", "fx_budget": {2025: 4350.0, 2026: 4450.0}, "fx_drift": 0.090},
    "MX": {"name": "Mexico",   "currency": "MXN", "fx_budget": {2025: 19.80,  2026: 20.40},  "fx_drift": 0.020},
    "ES": {"name": "Spain",    "currency": "EUR", "fx_budget": {2025: 1.0,    2026: 1.0},    "fx_drift": 0.0},
}

# Categories: budget unit price in EUR-equivalent, gross margin % and
# relative weight of units in each country.
CATEGORIES = {
    "ELEC": {"name": "Electronics", "price_eur": 240.0, "gm_pct": 0.18},
    "HOME": {"name": "Home & DIY",  "price_eur": 55.0,  "gm_pct": 0.32},
    "FASH": {"name": "Fashion",     "price_eur": 38.0,  "gm_pct": 0.48},
    "BEAU": {"name": "Beauty",      "price_eur": 22.0,  "gm_pct": 0.55},
}

# Budget monthly units (thousands) per country at a "normal" month.
BASE_UNITS_K = {
    "CL": {"ELEC": 42, "HOME": 210, "FASH": 260, "BEAU": 180},
    "PE": {"ELEC": 18, "HOME": 95,  "FASH": 140, "BEAU": 110},
    "CO": {"ELEC": 25, "HOME": 120, "FASH": 175, "BEAU": 130},
    "MX": {"ELEC": 30, "HOME": 150, "FASH": 190, "BEAU": 160},
    "ES": {"ELEC": 15, "HOME": 60,  "FASH": 120, "BEAU": 70},
}

# Retail seasonality index by month (1 = average month).
SEASONALITY = {1: 0.85, 2: 0.80, 3: 0.92, 4: 0.93, 5: 1.02, 6: 0.98,
               7: 1.00, 8: 0.95, 9: 0.97, 10: 1.03, 11: 1.25, 12: 1.30}

# Opex drivers (budget). Amounts in EUR-equivalent at budget FX.
OPEX = {
    "cost_per_fte_month": {"CL": 1900, "PE": 1300, "CO": 1250, "MX": 1500, "ES": 2900},
    "fte_budget":         {"CL": 2500, "PE": 2000, "CO": 2400, "MX": 2600, "ES": 650},
    "marketing_pct_rev":  0.035,
    "logistics_per_unit": {"CL": 1.15, "PE": 1.05, "CO": 1.10, "MX": 1.20, "ES": 1.60},
    "rent_month":         {"CL": 1_250_000, "PE": 520_000, "CO": 700_000, "MX": 850_000, "ES": 600_000},
    "it_month":           {"CL": 420_000, "PE": 180_000, "CO": 230_000, "MX": 300_000, "ES": 260_000},
}
OPEX_LINES = ["Personnel", "Marketing", "Logistics", "Rent & Occupancy", "IT & Technology"]

# Forecast cycles: name -> last closed month used as actuals.
FORECAST_CYCLES = {"FC_3+9": "2026-03-01", "FC_6+6": "2026-06-01", "FC_9+3": "2026-09-01"}
