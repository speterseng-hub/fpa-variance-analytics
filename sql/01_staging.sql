-- =====================================================================
-- 01_staging.sql
-- Load raw extracts (ERP / EPM style, local currency) and the forecast
-- cycles produced by the driver-based engine into typed staging tables.
-- {raw} and {processed} are replaced by the pipeline with folder paths.
-- =====================================================================

CREATE OR REPLACE TABLE dim_country  AS SELECT * FROM read_csv_auto('{raw}/dim_country.csv');
CREATE OR REPLACE TABLE dim_category AS SELECT * FROM read_csv_auto('{raw}/dim_category.csv');
CREATE OR REPLACE TABLE business_events AS SELECT * FROM read_csv_auto('{raw}/business_events.csv');

CREATE OR REPLACE TABLE stg_sales AS
SELECT scenario, CAST(month AS DATE) AS month, country, category,
       CAST(units AS BIGINT) AS units,
       CAST(net_revenue_lc AS DOUBLE) AS net_revenue_lc,
       CAST(cogs_lc AS DOUBLE) AS cogs_lc
FROM (
    SELECT * FROM read_csv_auto('{raw}/sales.csv')
    UNION ALL
    SELECT * FROM read_csv_auto('{processed}/sales_forecast.csv')
);

CREATE OR REPLACE TABLE stg_opex AS
SELECT scenario, CAST(month AS DATE) AS month, country, opex_line,
       CAST(amount_lc AS DOUBLE) AS amount_lc
FROM (
    SELECT * FROM read_csv_auto('{raw}/opex.csv')
    UNION ALL
    SELECT * FROM read_csv_auto('{processed}/opex_forecast.csv')
);

CREATE OR REPLACE TABLE stg_headcount AS
SELECT scenario, CAST(month AS DATE) AS month, country, CAST(fte AS DOUBLE) AS fte
FROM (
    SELECT * FROM read_csv_auto('{raw}/headcount.csv')
    UNION ALL
    SELECT * FROM read_csv_auto('{processed}/headcount_forecast.csv')
);

CREATE OR REPLACE TABLE stg_fx AS
SELECT scenario, CAST(month AS DATE) AS month, currency, CAST(rate_per_eur AS DOUBLE) AS rate_per_eur
FROM (
    SELECT * FROM read_csv_auto('{raw}/fx_rates.csv')
    UNION ALL
    SELECT * FROM read_csv_auto('{processed}/fx_rates_forecast.csv')
);

CREATE OR REPLACE TABLE dim_scenario AS
SELECT * FROM (VALUES
    ('ACTUAL', 'Actual',            1),
    ('BUDGET', 'Budget',            2),
    ('FC_3+9', 'Forecast 3+9',      3),
    ('FC_6+6', 'Forecast 6+6',      4),
    ('FC_9+3', 'Forecast 9+3',      5)
) AS t(scenario, scenario_name, sort_order);
