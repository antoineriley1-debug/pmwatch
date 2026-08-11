# PMWATCH — MedStar PM QC Dashboard

Mobile-first dashboard for tracking closed **preventive-maintenance (PM)** work
orders across 10 MedStar hospitals, QC-ing them against asset-specific
checklists, and surfacing which sites/systems are weak or failing.

**Live:** https://pmwatch.onrender.com
**Stack:** Python / Flask + Jinja templates, Neon Postgres, Playwright scraper
(headless Chromium) against Maintenance Connection (MC). Deployed on Render via
Docker, auto-deploys from GitHub `antoineriley1-debug/pmwatch`.

---

## Architecture (data flow)

```
Maintenance Connection (MC web app)
        │  Playwright login + Repair Center dropdown + "All Closed" view
        ▼
scraper.py  ──► list scrape (WO#, reason, target date, asset text)
        │                     │
        │                     ▼
        │            db.upsert_pms()  ──►  Neon Postgres: closed_pms
        │
        └──► enrichment (open each WO detail: mechanic + close_date + system)
                          │
                          ▼
                    db.upsert_pms() UPDATE (fills closed_by/close_date/system)

Flask (app.py) ── reads Neon ──► Jinja templates (templates/*.html)
```

**Key insight:** WO# and reason come from the list grid, but **mechanic,
close date, and system come only from each WO's detail page** (opened one at a
time — MC blocks direct-URL detail fetch, so we double-click the row). This
"enrichment" is the slow part and drives everything (Today counts, per-mechanic
tracking, system classification). It runs incrementally via `/enrich`.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask routes (pages + JSON scrape/enrich/stats endpoints) |
| `db.py` | All Postgres access. Schema in `SCHEMA`; each DDL runs on its own autocommit connection (see "Migration gotcha") |
| `scraper.py` | Playwright login, per-hospital scrape, portfolio scrape, enrichment walker |
| `checklists.py` | Asset-specific QC checklists + `classify()` (WO text → asset type) |
| `templates/` | Jinja UI (base + one per tab + `wo.html`, `pms_view.html`) |
| `Dockerfile` | Playwright base image + gunicorn |
| `requirements.txt` | flask, gunicorn, psycopg2-binary, playwright |

---

## Environment variables (set in Render)

| Var | Meaning |
|-----|---------|
| `DATABASE_URL` | Neon Postgres connection string (SSL enforced in code) |
| `MC_USERNAME` / `MC_PASSWORD` | Maintenance Connection login |
| `SCRAPE_TOKEN` | Shared secret guarding all scrape/enrich/admin routes (`?token=`) |

Current token: `pmwatch-8842-verify`

---

## Routes

### Pages (UI)
- `/` — Dashboard: per-site Today/Week/Month/Total + network total. **Every number is clickable** → `/pms-view`.
- `/pms-view?period=today|yesterday|week|month&hospital=&mechanic=&system=` — filtered WO list; rows → `/wo/<n>`.
- `/wo/<wo_number>` — single WO: asset, mechanic/contractor, task/procedure, inline QC checklist.
- `/mechanics?show=all|active|inactive&who=<name>&hospital=` — per-mechanic activity + View drilldown + active/inactive (left) toggle + contractor flag.
- `/qc?hospital=` — QC queue; each pending PM shows an asset-specific checklist → auto-score → pass/fail.
- `/insights?hospital=` — site scorecard (well vs weak by QC pass rate) + system scorecard (which systems failing) + auto "needs attention" flags.
- `/trends`, `/reports`, `/contracts` — trend charts, printable reports, vendor contracts.

### POST handlers
- `/qc/submit` — stores QC review: per-item checklist results + auto score + pass/fail.
- `/mechanics/toggle` — active↔inactive.
- `/mechanics/save` — edit display name/trade/site/company/contractor flag.
- `/contracts/add` — add vendor contract.

### JSON / admin (token-gated: `?token=SCRAPE_TOKEN`)
- `/scrape-all?enrich=0[&hospitals=CSV]` — scrape ALL 10 hospitals in one login (use this).
- `/scrape?hospital=CODE&store=0&enrich=0` — single hospital.
- `/enrich?limit=N&hospital=CODE` — **resumable** enrichment walker (newest-first). Call repeatedly to clear backlog.
- `/stats` — per-site enrichment coverage (mechanic/close_date/system).
- `/migrate` — run schema + report per-statement + column list.
- `/probe-paging?hospital=CODE` — diagnostic: MC paging controls + row count.
- `/pms?hospital=CODE` — inspect stored rows. `/health`, `/ping` — liveness.

---

## Two gotchas baked into the code (don't undo them)

1. **Migration:** `db.init_db()` runs each DDL statement on its OWN
   `autocommit=True` connection. A shared transaction poisoned by one error
   silently skipped `ALTER TABLE ADD COLUMN`, causing `column "system" does not
   exist`. Keep per-statement isolation.

2. **Pagination:** MC's grid shows ~48 rows/page. `_build_show_all_url()`
   re-navigates the list frame with `pagesize=5000&sallpages=1` so all ~355
   rows/site (last 6 months) render. Without it, every site's Total was 48.

3. **Full 10-site show-all scrape exceeds Render's ~290s HTTP timeout.** The
   recurring scrape is split into two staggered cron jobs (5 sites each).
   Per-site commits persist even if the request times out.

---

## Portfolio (hospital code → MC repaircenter id, in scraper.py)

52626 Washington HC (4) · 52625 Georgetown (2) · 52624 Southern MD (8) ·
52623 St Mary's (12) · 52622 Harbor (11) · 52621 Good Samaritan (9) ·
52620 Union Memorial (10) · 52619 Franklin Square (5) · 52618 Montgomery (7) ·
52617 National Rehab (6).

---

## Local dev

```bash
pip install -r requirements.txt
playwright install chromium
export DATABASE_URL=...  MC_USERNAME=...  MC_PASSWORD=...  SCRAPE_TOKEN=...
python -m flask --app app run   # or: gunicorn app:app
```

The scraper needs the Playwright Chromium image (see Dockerfile) — that's why
production runs on the `mcr.microsoft.com/playwright/python` base.

---

## QC checklists (checklists.py)

`classify(system, procedure, reason, asset_name)` maps WO text to an asset type;
each type has a concrete inspection list. Types: `hvac_coil`, `hvac_unit`,
`med_gas`, `med_gas_alarm`, `auto_door`, `neg_pressure`, `plumbing_water`,
`booster_pump`, `electrical`, `fire_life_safety`, `generic`. Score = % of items
checked. Add a type: add an entry to `CHECKLISTS` + a matcher in `_MATCHERS`.
