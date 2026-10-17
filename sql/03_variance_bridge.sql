-- =====================================================================
-- 03_variance_bridge.sql
-- Price / Volume / Mix / Unit cost / FX decomposition, as table macros.
--
--   base_sc  : reference scenario   (e.g. 'BUDGET', 'FC_6+6', 'ACTUAL' for PY)
--   comp_sc  : compared scenario    (e.g. 'ACTUAL', 'FC_9+3')
--   offset_m : months between base and compared period (12 = vs prior year)
--
-- For each country x category x month (U = units, P = price, C = unit cost,
-- all in local currency; fx = local currency per EUR; b = base, a = compared):
--
--   Volume    = (U_a_total x mix_b - U_b) x margin_b / fx_b
--   Mix       = (U_a - U_a_total x mix_b) x margin_b / fx_b
--   Price     = (P_a - P_b) x U_a / fx_b
--   Unit cost = -(C_a - C_b) x U_a / fx_b
--   FX        = GM_a_local x (1/fx_a - 1/fx_b)
--
-- Mix is measured within each country (category mix). The components add
-- up exactly to GM_a - GM_b in EUR; this is enforced by 04_quality_checks.
-- Sign convention: positive = favourable to EBITDA.
-- =====================================================================

CREATE OR REPLACE MACRO sales_bridge(base_sc, comp_sc, offset_m) AS TABLE
WITH b AS (
    SELECT *, CAST(month + to_months(CAST(offset_m AS INTEGER)) AS DATE) AS comp_month
    FROM fct_sales WHERE scenario = base_sc
), a AS (
    SELECT * FROM fct_sales WHERE scenario = comp_sc
), j AS (
    SELECT a.month, a.country, a.category,
           b.units AS u_b, a.units AS u_a,
           b.net_revenue_lc / b.units AS p_b, a.net_revenue_lc / a.units AS p_a,
           b.cogs_lc / b.units        AS c_b, a.cogs_lc / a.units        AS c_a,
           b.rate_per_eur AS fx_b, a.rate_per_eur AS fx_a,
           b.revenue_eur AS revenue_base, a.revenue_eur AS revenue_comp,
           b.gross_margin_eur AS gm_base, a.gross_margin_eur AS gm_comp,
           SUM(a.units) OVER (PARTITION BY a.month, a.country) AS u_a_tot,
           SUM(b.units) OVER (PARTITION BY a.month, a.country) AS u_b_tot
    FROM a JOIN b ON b.comp_month = a.month AND b.country = a.country AND b.category = a.category
)
SELECT month, country, category,
       revenue_base, revenue_comp, gm_base, gm_comp,
       -- revenue bridge
       (u_a_tot * u_b / u_b_tot - u_b) * p_b / fx_b        AS rev_volume,
       (u_a - u_a_tot * u_b / u_b_tot) * p_b / fx_b        AS rev_mix,
       (p_a - p_b) * u_a / fx_b                            AS rev_price,
       u_a * p_a * (1 / fx_a - 1 / fx_b)                   AS rev_fx,
       -- gross margin bridge
       (u_a_tot * u_b / u_b_tot - u_b) * (p_b - c_b) / fx_b AS gm_volume,
       (u_a - u_a_tot * u_b / u_b_tot) * (p_b - c_b) / fx_b AS gm_mix,
       (p_a - p_b) * u_a / fx_b                             AS gm_price,
       -(c_a - c_b) * u_a / fx_b                            AS gm_unit_cost,
       u_a * (p_a - c_a) * (1 / fx_a - 1 / fx_b)            AS gm_fx
FROM j;

-- Opex: variance at constant currency + FX translation, favourable positive.
CREATE OR REPLACE MACRO opex_bridge(base_sc, comp_sc, offset_m) AS TABLE
WITH b AS (
    SELECT *, CAST(month + to_months(CAST(offset_m AS INTEGER)) AS DATE) AS comp_month
    FROM fct_opex WHERE scenario = base_sc
), a AS (
    SELECT * FROM fct_opex WHERE scenario = comp_sc
)
SELECT a.month, a.country, a.opex_line,
       b.amount_eur AS opex_base, a.amount_eur AS opex_comp,
       -(a.amount_lc - b.amount_lc) / b.rate_per_eur              AS opex_var_const_fx,
       -a.amount_lc * (1 / a.rate_per_eur - 1 / b.rate_per_eur)   AS opex_fx
FROM a JOIN b ON b.comp_month = a.month AND b.country = a.country AND b.opex_line = a.opex_line;

-- EBITDA bridge in long format: one row per month / country / driver.
CREATE OR REPLACE MACRO ebitda_bridge(base_sc, comp_sc, offset_m) AS TABLE
SELECT month, country, category AS detail, 'Volume' AS driver, 1 AS driver_order, gm_volume AS impact_eur FROM sales_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, category, 'Mix',       2, gm_mix       FROM sales_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, category, 'Price',     3, gm_price     FROM sales_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, category, 'Unit cost', 4, gm_unit_cost FROM sales_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, opex_line, 'Opex: ' || opex_line,
                 CASE opex_line WHEN 'Personnel' THEN 5 WHEN 'Marketing' THEN 6 WHEN 'Logistics' THEN 7
                                WHEN 'Rent & Occupancy' THEN 8 ELSE 9 END,
                 opex_var_const_fx FROM opex_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, category, 'FX',        10, gm_fx       FROM sales_bridge(base_sc, comp_sc, offset_m)
UNION ALL SELECT month, country, opex_line, 'FX',       10, opex_fx     FROM opex_bridge(base_sc, comp_sc, offset_m);
