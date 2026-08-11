# PMWATCH — Product Spec (owner: Twiney, director-level, mobile-first)

## Home / Dashboard (at a glance)
- Running count of **PMs closed TODAY per site**, plus a **network total**.
- Numbers are **drill-downable**: tap a site → see exactly what was closed there today.
- **Sortable / groupable by system** (HVAC, medical gas, plumbing, electrical, etc.) **and by site**.

## Trends
- **Per-site** completion trends over time.
- **Network-wide** completion trends over time.

## QC
- **Checklist** to QC completed PMs (pass/fail + notes + photos).
- One-button **"what was closed per site"** view.

## Reports
- Generate reports based on QC findings (per-site, with results).

## Contracts (vendor)
- Track vendor contracts.
- Highlight **issues & discrepancies** (obligated vs completed).
- Running **countdown to expiration**.

## Data foundation (from Maintenance Connection)
- Closed PMs per site (10 hospitals), correctives excluded.
- Each PM: WO#, site, **system/category**, **mechanic who closed it (closed_by)**,
  **actual close date**, asset name/model/serial, location.
- closed_by + close_date come from the WO detail (Assignments block); enriched
  by clicking the row in-app (direct URL returns empty).

## Nav (top tabs)
Dashboard | Sites | Trends | QC | Reports | Contracts
