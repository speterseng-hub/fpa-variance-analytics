-- =====================================================================
-- 04_quality_checks.sql
-- Automated reconciliation checks ("cuadres") run on every build.
-- Each check returns: check_name, status ('PASS' / 'FAIL'), detail.
-- =====================================================================

CREATE OR REPLACE TABLE quality_checks AS

-- 1. Every sales row found its FX rate (no silent drops in the EUR mart)
SELECT 'FX coverage: every sales row translated to EUR' AS check_name,
       CASE WHEN (SELECT COUNT(*) FROM stg_sales) = (SELECT COUNT(*) FROM fct_sales) THEN 'PASS' ELSE 'FAIL' END AS status,
       (SELECT COUNT(*) FROM stg_sales) || ' staging rows vs ' || (SELECT COUNT(*) FROM fct_sales) || ' mart rows' AS detail

UNION ALL
-- 2. Budget is complete: 2 years x 12 months x 5 countries x 4 categories
SELECT 'Completeness: budget grid (2y x 12m x 5 countries x 4 categories)',
       CASE WHEN COUNT(*) = 480 THEN 'PASS' ELSE 'FAIL' END,
       COUNT(*) || ' rows (expected 480)'
FROM stg_sales WHERE scenario = 'BUDGET'

UNION ALL
-- 3. No negative units, revenue or cost
SELECT 'Sanity: no negative units, revenue or COGS',
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COUNT(*) || ' offending rows'
FROM stg_sales WHERE units < 0 OR net_revenue_lc < 0 OR cogs_lc < 0

UNION ALL
-- 4. Gross margin within a plausible range for retail (0-70%)
SELECT 'Sanity: gross margin % between 0% and 70% on every line',
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COUNT(*) || ' lines outside range'
FROM fct_sales WHERE gross_margin_eur / revenue_eur NOT BETWEEN 0 AND 0.70

UNION ALL
-- 5. Bridge reconciles: Budget -> Actual components add up to the GM gap
SELECT 'Reconciliation: GM bridge Budget vs Actual sums to the variance',
       CASE WHEN MAX(ABS(diff)) < 0.01 THEN 'PASS' ELSE 'FAIL' END,
       'max abs difference EUR ' || ROUND(MAX(ABS(diff)), 6)
FROM (
    SELECT (gm_comp - gm_base) - (gm_volume + gm_mix + gm_price + gm_unit_cost + gm_fx) AS diff
    FROM sales_bridge('BUDGET', 'ACTUAL', 0)
)

UNION ALL
-- 6. Revenue bridge reconciles as well
SELECT 'Reconciliation: revenue bridge Budget vs Actual sums to the variance',
       CASE WHEN MAX(ABS(diff)) < 0.01 THEN 'PASS' ELSE 'FAIL' END,
       'max abs difference EUR ' || ROUND(MAX(ABS(diff)), 6)
FROM (
    SELECT (revenue_comp - revenue_base) - (rev_volume + rev_mix + rev_price + rev_fx) AS diff
    FROM sales_bridge('BUDGET', 'ACTUAL', 0)
)

UNION ALL
-- 7. EBITDA bridge total equals EBITDA actual minus budget
SELECT 'Reconciliation: EBITDA bridge equals EBITDA Actual - Budget',
       CASE WHEN ABS(bridge - gap) < 1 THEN 'PASS' ELSE 'FAIL' END,
       'bridge EUR ' || ROUND(bridge, 2) || ' vs gap EUR ' || ROUND(gap, 2)
FROM (
    SELECT (SELECT SUM(impact_eur) FROM ebitda_bridge('BUDGET', 'ACTUAL', 0)) AS bridge,
           (SELECT SUM(ebitda_eur) FROM mart_kpi_monthly WHERE scenario = 'ACTUAL')
         - (SELECT SUM(ebitda_eur) FROM mart_kpi_monthly k WHERE scenario = 'BUDGET'
              AND month <= (SELECT MAX(month) FROM stg_sales WHERE scenario = 'ACTUAL')) AS gap
)

UNION ALL
-- 8. Forecast closed months equal actuals (no restatement of the past)
SELECT 'Forecast integrity: closed months of each cycle equal actuals',
       CASE WHEN MAX(ABS(f.revenue_eur - a.revenue_eur)) < 0.01 THEN 'PASS' ELSE 'FAIL' END,
       'max abs difference EUR ' || ROUND(MAX(ABS(f.revenue_eur - a.revenue_eur)), 6)
FROM fct_sales f
JOIN fct_sales a ON a.scenario = 'ACTUAL' AND a.month = f.month AND a.country = f.country AND a.category = f.category
WHERE f.scenario LIKE 'FC_%'
  AND f.month <= CASE f.scenario WHEN 'FC_3+9' THEN DATE '2026-03-01'
                                 WHEN 'FC_6+6' THEN DATE '2026-06-01' ELSE DATE '2026-09-01' END

UNION ALL
-- 9. Every forecast cycle covers the full year
SELECT 'Completeness: each forecast cycle covers 12 months x 5 countries x 4 categories',
       CASE WHEN MIN(n) = 240 AND MAX(n) = 240 THEN 'PASS' ELSE 'FAIL' END,
       'rows per cycle: ' || STRING_AGG(scenario || '=' || n, ', ' ORDER BY scenario)
FROM (SELECT scenario, COUNT(*) AS n FROM stg_sales WHERE scenario LIKE 'FC_%' GROUP BY scenario)

UNION ALL
-- 10. Opex lines complete for every scenario/month/country
SELECT 'Completeness: 5 opex lines for every scenario, month and country',
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
       COUNT(*) || ' incomplete combinations'
FROM (SELECT scenario, month, country FROM stg_opex GROUP BY ALL HAVING COUNT(DISTINCT opex_line) <> 5);
