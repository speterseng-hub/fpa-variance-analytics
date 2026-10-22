"""End-to-end build: raw data -> forecast cycles -> DuckDB warehouse -> checks -> Power BI extracts.

Usage:
    python -m src.pipeline            # full rebuild
    python -m src.pipeline --no-data  # keep existing raw data, rebuild the rest
"""
from __future__ import annotations

import argparse
import sys

import duckdb

from src import config as C
from src import forecast, generate_data

SQL_FILES = ["01_staging.sql", "02_marts.sql", "03_variance_bridge.sql", "04_quality_checks.sql"]


def build_warehouse(path=C.WAREHOUSE) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    for f in SQL_FILES:
        sql = (C.SQL_DIR / f).read_text(encoding="utf-8")
        sql = sql.replace("{raw}", C.DATA_RAW.as_posix()).replace("{processed}", C.DATA_PROCESSED.as_posix())
        con.execute(sql)
    return con


def export_powerbi(con: duckdb.DuckDBPyConnection) -> None:
    """Star schema extracts for the Power BI report (see powerbi/README.md)."""
    C.POWERBI_DIR.mkdir(parents=True, exist_ok=True)
    # explicit ORDER BY: DuckDB writes in parallel, so without it every rebuild reshuffles the committed CSVs
    queries = {
        "dim_country": "SELECT * FROM dim_country",
        "dim_category": "SELECT * FROM dim_category",
        "dim_scenario": "SELECT * FROM dim_scenario",
        "dim_date": """
            SELECT DISTINCT month AS date, year(month) AS year, month(month) AS month_no,
                   strftime(month, '%b') AS month_name, 'Q' || quarter(month) AS quarter
            FROM fct_sales ORDER BY 1""",
        "fct_sales": """
            SELECT scenario, month AS date, country, category, units,
                   ROUND(revenue_eur, 2) AS revenue_eur, ROUND(cogs_eur, 2) AS cogs_eur,
                   ROUND(gross_margin_eur, 2) AS gross_margin_eur
            FROM fct_sales ORDER BY scenario, date, country, category""",
        "fct_opex": """
            SELECT scenario, month AS date, country, opex_line, ROUND(amount_eur, 2) AS amount_eur
            FROM fct_opex ORDER BY scenario, date, country, opex_line""",
        "fct_headcount": "SELECT scenario, month AS date, country, fte FROM stg_headcount ORDER BY scenario, date, country",
        "fct_bridge_budget_vs_actual": """
            SELECT month AS date, country, detail, driver, driver_order, ROUND(impact_eur, 2) AS impact_eur
            FROM ebitda_bridge('BUDGET', 'ACTUAL', 0) ORDER BY date, country, driver_order, detail""",
    }
    for name, q in queries.items():
        con.execute(f"COPY ({q}) TO '{(C.POWERBI_DIR / (name + '.csv')).as_posix()}' (HEADER, DELIMITER ',')")


def run(generate: bool = True) -> int:
    if generate or not (C.DATA_RAW / "sales.csv").exists():
        generate_data.main()
    forecast.main()
    con = build_warehouse()
    export_powerbi(con)
    checks = con.execute("SELECT check_name, status, detail FROM quality_checks").fetchall()
    print("\nData quality checks")
    for name, status, detail in checks:
        print(f"  [{status}] {name} - {detail}")
    con.close()
    failed = [c for c in checks if c[1] != "PASS"]
    print(f"\nWarehouse: {C.WAREHOUSE}\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-data", action="store_true", help="do not regenerate raw data")
    sys.exit(run(generate=not ap.parse_args().no_data))
