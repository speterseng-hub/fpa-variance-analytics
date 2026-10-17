# Power BI report

The Power BI version of the dashboard is built on the same warehouse as the
Streamlit app. `python -m src.pipeline` exports a clean star schema to
`powerbi/data/`, so the numbers match those in the Python version.

## Data model (star schema)

| Table | Grain | Key columns |
|---|---|---|
| `fct_sales` | scenario × month × country × category | units, revenue_eur, cogs_eur, gross_margin_eur |
| `fct_opex` | scenario × month × country × opex line | amount_eur |
| `fct_headcount` | scenario × month × country | fte |
| `fct_bridge_budget_vs_actual` | month × country × detail × driver | impact_eur, driver_order |
| `dim_date` | month | year, month_no, month_name, quarter |
| `dim_country` | country | country_name, currency |
| `dim_category` | category | category_name |
| `dim_scenario` | scenario | scenario_name, sort_order |

```
dim_date ─┐            ┌─ dim_country
          ├─ fct_sales ─┤
dim_scenario ┘   (same keys on fct_opex, fct_headcount, fct_bridge)
                       └─ dim_category
```

## Build steps (about 20 minutes)

1. **Get data → Text/CSV**: load the 8 files in `powerbi/data/`. Set `date` columns to *Date*.
2. **Model view**: create one-to-many relationships from each `dim_*` table to the fact tables
   (`date`, `country`, `category`, `scenario`). Mark `dim_date` as a date table.
3. Create a table `Measures` and paste the measures from [`measures.dax`](measures.dax).
4. Sort `dim_scenario[scenario_name]` by `sort_order` and `fct_bridge_budget_vs_actual[driver]` by `driver_order`.
5. Build three pages:
   - **Executive summary**: cards (`EBITDA Actual YTD`, `EBITDA Var vs Budget %`, `GM %`, `EBITDA %`),
     a P&L matrix (scenario columns) and a line chart of monthly EBITDA by scenario.
   - **Variance bridge**: a waterfall with `driver` as category and `Bridge Impact` as value, plus a
     matrix of driver × country with conditional formatting from `Variance Color`.
   - **Country drill-down**: country and category slicers, a decomposition tree on `EBITDA Var vs Budget`.
6. Theme: import [`theme.json`](theme.json) (same palette as the Streamlit app).
7. Save as `powerbi/FPA_Variance_Analytics.pbix` and add screenshots to `docs/img/`.

`Bridge Check` must return 0 for any filter. It is the same reconciliation that
the pipeline runs in SQL.
