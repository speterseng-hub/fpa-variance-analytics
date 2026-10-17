-- =====================================================================
-- 02_marts.sql
-- Reporting marts in EUR. Each scenario is translated with its own FX:
-- budget at budget rates, actuals at monthly actual rates, forecasts at
-- actual rates for closed months and spot rate for open months.
-- =====================================================================

CREATE OR REPLACE TABLE fct_sales AS
SELECT s.scenario, s.month, s.country, s.category,
       s.units, s.net_revenue_lc, s.cogs_lc,
       f.rate_per_eur,
       s.net_revenue_lc / f.rate_per_eur                 AS revenue_eur,
       s.cogs_lc / f.rate_per_eur                        AS cogs_eur,
       (s.net_revenue_lc - s.cogs_lc) / f.rate_per_eur   AS gross_margin_eur
FROM stg_sales s
JOIN dim_country c USING (country)
JOIN stg_fx f ON f.scenario = s.scenario AND f.month = s.month AND f.currency = c.currency;

CREATE OR REPLACE TABLE fct_opex AS
SELECT o.scenario, o.month, o.country, o.opex_line, o.amount_lc,
       f.rate_per_eur,
       o.amount_lc / f.rate_per_eur AS amount_eur
FROM stg_opex o
JOIN dim_country c USING (country)
JOIN stg_fx f ON f.scenario = o.scenario AND f.month = o.month AND f.currency = c.currency;

-- Long P&L: one row per scenario / month / country / P&L line.
-- Sign convention: income positive, costs negative -> EBITDA = SUM(amount_eur).
CREATE OR REPLACE TABLE fct_pnl AS
SELECT scenario, month, country, 'Net revenue' AS pnl_line, 1 AS line_order, SUM(revenue_eur) AS amount_eur
FROM fct_sales GROUP BY ALL
UNION ALL
SELECT scenario, month, country, 'COGS', 2, -SUM(cogs_eur)
FROM fct_sales GROUP BY ALL
UNION ALL
SELECT scenario, month, country, opex_line,
       CASE opex_line WHEN 'Personnel' THEN 3 WHEN 'Marketing' THEN 4 WHEN 'Logistics' THEN 5
                      WHEN 'Rent & Occupancy' THEN 6 ELSE 7 END,
       -SUM(amount_eur)
FROM fct_opex GROUP BY ALL;

-- Monthly KPI table per country (feeds tiles, trends and Power BI).
CREATE OR REPLACE TABLE mart_kpi_monthly AS
WITH s AS (
    SELECT scenario, month, country, SUM(units) AS units, SUM(revenue_eur) AS revenue_eur,
           SUM(gross_margin_eur) AS gross_margin_eur
    FROM fct_sales GROUP BY ALL
), o AS (
    SELECT scenario, month, country, SUM(amount_eur) AS opex_eur FROM fct_opex GROUP BY ALL
)
SELECT s.*, o.opex_eur, s.gross_margin_eur - o.opex_eur AS ebitda_eur, h.fte,
       s.gross_margin_eur / NULLIF(s.revenue_eur, 0)                  AS gm_pct,
       (s.gross_margin_eur - o.opex_eur) / NULLIF(s.revenue_eur, 0)   AS ebitda_pct,
       s.revenue_eur / NULLIF(h.fte, 0)                               AS revenue_per_fte
FROM s
JOIN o USING (scenario, month, country)
LEFT JOIN stg_headcount h USING (scenario, month, country);
