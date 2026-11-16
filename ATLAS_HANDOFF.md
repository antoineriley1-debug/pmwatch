# ATLAS Upgrade Handoff — Consolidation, Repo Completeness, and "One Path to the Answer"

**Audience:** the Claude/agent working on the ATLAS box (`/workspace/atlas`).
**Source of this review:** full structural audit of `atlas_live_code_20261116.zip` (code, docs, deploy, tests, web UI), import-graph analysis of all ~130 `atlas/*.py` modules, JS reference map of all 52 `atlas/web/*.js` files, and a fixture-only test run (1,194 passed; ~600 failures were all "no such table: asset" / missing `data/*.db` — environment, not breakage).

---

## 0. North star (read this first)

Antoine's #1 complaint is **navigation, not features**: *"I want to get to a path of destination when I'm using this app. I don't want to be bouncing around looking for data."*

Every change below serves one of two goals:

1. **One engine per question, one screen per answer.** No two modules computing overlapping answers with different rules; no two screens where the user must guess which one has the data.
2. **A complete, reproducible repo.** Everything needed to rebuild the system lives in the tree or is explicitly documented as external.

**Hard constraints — do not violate:**
- ATLAS stays **read-only toward all upstream systems** (Maintenance Connection, source files). Never weaken `atlas/connectors/` or `tests/test_connectors_readonly.py`.
- Corrective data **never** enters PM data, gap logic, or counts (`SCOPE_TEXT` in `config.py`; `tests/test_scope_text.py`). The corrective/PM wall stays; only its *spelling* changes (§3.4).
- Append-only stores stay append-only. Site identity stays prefix-only (the MSMH/MSMHC guard in `config.py`).
- The architecture-guard tests (`test_gap_authority.py::test_guard_every_read_path_uses_the_authority`, scope-text sync tests, `DATA_START` sync tests) must pass after every phase — update them deliberately when a refactor moves what they guard, never delete them to get green.
- Run `pytest -q --ignore=tests/e2e` after each work package; run the full suite incl. E2E before calling a phase done.

Work the phases in order. Each phase is independently shippable.

---

## Phase 1 — Make the repo complete and honest (small, do first)

### 1.1 Commit the missing orchestration layer
These are referenced by code/docs but absent from the tree. A fresh machine cannot reproduce the feed, publish, watchdog, or 2FA:
- `scripts/feed_and_publish.sh` — referenced in `docs/DEPLOY.md`, `atlas/datapull.py`, `atlas/stamp.py`, `atlas/sync_health.py`, `scripts/corrective_feed.sh`; `tests/test_datapull.py` and `tests/test_feed_stamp_wiring.py` silently skip without it.
- `install_auth_module.sh` and the `/opt/atlas_auth` gate (or a README section stating exactly where it lives and how it's installed).
- `atlas-sync-watch.timer` (+ its `.service`).
- The cron entry / timer that runs `scripts/corrective_feed.sh` "every 15 min".

Also: `scripts/corrective_feed.sh` hardcodes a VPS IP and SSH key path as defaults — move to env vars with the current values documented in `docs/DEPLOY.md`.

### 1.2 Dead/orphan code
- `atlas/schedule_changes.py` (510 lines): nothing in the tree calls it; its only caller is the missing `feed_and_publish.sh`. Once 1.1 lands, wire it visibly (a `__main__` or a script entry); if it's actually retired, delete it and the `sync_health.py` read of `schedule_changes.db`.

### 1.3 Fail loudly on missing data
- `atlas/corrective.py:228` reads `atlas/corrective_pool.csv` (381-name mechanic pool) and returns `{}` on `OSError`, silently changing corrective classification, the registry, and labor hours. If the file is excluded from backups on purpose (names), keep excluding it, but: log a prominent startup warning, surface a banner in the corrective screens, and add a `/api/health` field. Never degrade silently.

### 1.4 Dev/test dependencies
- Create `deploy/requirements-dev.txt` (pytest, hypothesis, Playwright pin matching the box Chrome, httpx, anything else the suite imports). `hypothesis` currently breaks collection on any fresh venv. Note it in README.

### 1.5 Portability nits
- `atlas/sources.py:7` hardcodes `W = "/workspace"`; `atlas/mcx.py:43` hardcodes the `ATLAS_MCX_SRC` default. Derive from `config.ROOT` or env with documented defaults.
- `data/` bootstrap: `scripts/run_pipeline.py` (or a tiny `scripts/bootstrap.py`) should create `data/` and friendly-error when source DBs are absent instead of `sqlite3.OperationalError`.

### 1.6 Deploy unit vs. reality
- `deploy/atlas.service` doesn't set `ATLAS_AUTH_MODULE_DIR`, so as committed it runs in-tree `auth.py`, not the documented `/opt/atlas_auth` 2FA gate (`api.py:1557-1572`). Commit the real drop-in or set the var in the unit.
- Document the hidden convention that ~13 side stores (`triage.db`, `pm_actions.db`, `oos_override.db`, `series_exclusion.db`, `replacement_links.db`, …) resolve "next to prime.db" and therefore land in the systemd `StateDirectory` only because `ATLAS_PRIME_DB` points there. (§3.2 removes the copy-paste; the convention still needs one paragraph in DEPLOY.md.)
- Add `ATLAS_PRIME_ROLES`, `ATLAS_UPLOAD_ENABLED`, and the prewarm switches to DEPLOY.md. Better: generate an env-var reference (grep `ATLAS_` once, keep it as a doc page).

### 1.7 Rewrite the stale docs
- `docs/ARCHITECTURE.md` §1, §7, §9, §11 still say frontend "Not started", "no auth yet", "one write route only". Reality: ~356 routes, auth, RBAC, ~15 write stores, 52-file SPA. Rewrite to match; this doc is the map future agents navigate by.
- README: "130 tests" → actual (~200 files / ~1,685 functions). `docs/prime/IMPLEMENTATION.md` still lists removed `atlas/example_data.py`. DEPLOY.md header still describes the 2026-10-22 revert state.
- Refresh `scripts/prime_release_gate.py`'s hardcoded module list (frozen at 2026-10-22).

---

## Phase 2 — Kill the redundancy (engines)

### 2.1 One gap engine, computed at build time (the big one)
Today there are effectively **two gap engines**: `continuity.py` writes `finding` into canonical.db at build time (1.5P rule), then `gap_authority.py` (810 lines) + `freq_coverage.py` (1,800 lines) shadow `finding`/`asset` with TEMP views on **every read** (3/6/12-month rule), with `observed_cadence.py` / `cadence_rule.py` / `daycov.py` layering more read-time patches. The stored table is not what any screen shows.

This read-time recomputation is the root cause of the entire performance stack: `singleflight.py`, `heavy_prewarm.py`, five background prewarmers in `api.py:_lifespan` (one a separate process), the corrective disk cache, and the gap-authority generation DB.

**Do:** move the authority's computation into the pipeline build (`run_pipeline.py` step after continuity) so canonical.db stores the *final* answer every screen shows. Keep `gap_authority.ro()` as the single read entrypoint (the guard test keeps everyone honest) but make it a plain read, no TEMP views. Then delete, one at a time with measurements, whichever prewarm/singleflight pieces become unnecessary. Expected win: most of the cold-load machinery disappears and every screen shows the same number by construction — directly serving the "no bouncing between screens with different answers" goal.

### 2.2 One series-successor matcher
Five-plus overlapping replacement/rename detectors, each with private thresholds: continuity deep-sweep candidates, `replacement.py`, `supersede.py`, `replwork.py`, `stale_pms.py` (twin/old), `done_not_recorded.py` (renamed PMs, twin series). Extract one shared matcher module (`atlas/successor.py`): given a PM series, return scored successor candidates with the evidence (name overlap, period proximity, window rules) — and have all five call it. Keep each caller's *decision* semantics (auto-archive vs. review vs. dismiss) but delete the five private matching implementations. Add property tests comparing old/new outputs on fixtures before deleting.

### 2.3 One suppression ledger view
There are ~10 independent suppression/exclusion mechanisms, each with its own store: lifecycle archive, supersede, series_exclusion, oos overrides, mc_inactive_folder, bfpe_rule, identity_dismiss, triage retire, retire_queue, pm_replacement links, done_not_recorded dismissals. They exist for real, separately-ordered reasons — **do not merge the stores**. But `gap_scope.py` exists because two sets had already diverged (its own docstring: "2,597 vs 2,600"), and `pots.py` is a first-match classifier over all of them. **Do:** make `gap_scope.py` the single composition point every consumer uses (pots, screens, exports), add a test asserting the sets can't diverge again, and add a UI affordance: on any asset/series, show *which* mechanism suppressed it and link to that decision (feeds Phase 4's record page).

### 2.4 Shared infrastructure helpers
Delete the copy-paste:
- One `atlas/store_util.py`: `side_store_path(name)` (env var or sibling-of-prime.db — currently duplicated ~12×: `triage.py:41`, `identity_dismiss.py:36`, `replwork.py:40`, `oos_notes.py:185`, `series_exclusion.py:37`, `pm_replacement.py:35`, `done_not_recorded.py:128`, `corrective_pmdisguised.py:805`, `corrective_classify.py:57`, `corrective_unified.py:226`, `pm_coverage.py:258`, `corrective_pmlink_actions.py:49`), `append_only(con, table)` (the UPDATE/DELETE triggers duplicated 14×), `connect_ro/rw`.
- One `atlas/cache_util.py`: memoize-until-DB-mtime-changes (replaces ~15 module `_CACHE` dicts and ~21 stamp/key functions).
- One `now_et()/today_et()` in `config.py` (replaces ~13 copies).
- One XLSX writer utility (5 copies: `corrective_unified._xlsx`, `freq_coverage._xlsx`, `findings_export.to_xlsx`, `stale_pms.to_xlsx`, `report_studio.to_xlsx`) — keep `report_studio` styling as the canonical one.

### 2.5 Untangle `api.py`
`api.py` (1,578 lines) is both composition root and shared library: ~20 modules lazy-import it for private helpers (`A._gap_ro`, `A._retired_gaps`, `A._superseded`, `A._oos_moved`, `A._excluded`, `A._now`; `review_api.py` imports it 9×), plus ~42 imports of `prime_api`/`lifecycle_api` `_`-privates. **Do:** move those helpers into plain modules (the archive/exclusion ones belong in `gap_scope.py` per 2.3; prime helpers into `prime_util.py`), make `api.py` nothing but app assembly + middleware, and move `ActivityMiddleware` out of `corrective_api.py` (it's cross-cutting).

---

## Phase 3 — Structure and naming

### 3.1 Consistent module convention
The `foo.py` + `foo_api.py` split is applied unevenly (triage/oos_notes/pm_replacement split properly; freq_coverage/cadence_view/corrective_unified/closed_by/sync_health/pm_series_links/timeline_modes/page_exports embed routers in logic; some `_api` files are 15-line stubs). Pick ONE rule — suggest: logic module + router in the same file *unless* the router exceeds ~100 lines, then `_api.py` — and apply it. Merge the stub `_api` files (`boiler_templates_api.py`, `mc_inactive_folder_api.py`, …).

### 3.2 `corrective/` subpackage
The `corrective_*` filename prefix is really an access-control boundary (`tests/test_scope_text.py:37-52` only lets `atlas/corrective*.py` open corrective.db), which forces PM features (`corrective_pmsearch.py`, `corrective_labor_hours.py`, `corrective_locsrc.py`, `corrective_registry.py`, `corrective_mechtickets_api.py`) to wear the prefix. Create `atlas/corrective/` as a subpackage, key the guard test on the package path, and move the genuinely-PM modules out from behind the prefix. Do this as a pure-move commit (no logic changes) so the diff is reviewable.

### 3.3 Side-store migrations
Only prime.db has versioned, reversible, flock-protected migrations; the other ~12 write stores create schema ad hoc. Either fold the small side stores into prime.db as tables (preferred where append-only semantics allow — it also makes audit-then-write atomic, fixing the current non-atomic hash-chain audit across files), or give `store_util.py` a minimal per-store migration runner. Decide per store; document the decision.

### 3.4 Trim speculative scaffolding (confirm with Antoine before deleting)
- 4-role RBAC (`prime_db.py:135-160`) where `prime_db.py:132` notes the only login is Antoine→admin: collapse to admin/viewer, keep the role column so it can grow back.
- `billing_recon.py` (508 lines) + `mc_export.py` run on self-described EXAMPLE data and a provisional mapping: move behind a feature flag and out of nav until real data exists.
- Two auth implementations (in-tree `auth.py`, 289 lines, + external `atlas_auth` 2FA gate): keep exactly one in production; keep the other only as a documented fallback.
- `sync_health.py` serves its own embedded-HTML page (~line 292) outside the SPA: port it to a normal `web/` module.

---

## Phase 4 — "One path to the destination" (the UX payoff)

This is the phase Antoine actually feels. The app has ~52 screens and ~356 routes; data about one asset/PM series is scattered across gap views, coverage views, corrective views, timelines, decisions, retire queues, and exports. Build the navigation so **every question has one entry point and every entity has one home**:

### 4.1 One global search, everywhere
There are multiple search surfaces (`strict_search.py`, `corrective_pmsearch.py`, per-screen filters). Make one omnibox in the header of every screen that searches assets, PM series, WO numbers, mechanics, and sites in one query, with typed result groups. It routes to exactly one place per entity type (4.2). Keyboard: `/` focuses it. Keep `strict_search`'s literal-match guarantees as the backend.

### 4.2 One record page per entity (the hub pages)
- **Asset record** (`asset_record.py` is the seed — grow it into the single home): identity + location, every PM series on it with current gap status *and why* (which engine rule, which suppression if any, link to the decision per 2.3), full PM timeline, correctives side-by-side (read-one-way, never counted), notes/investigations, retire/replacement lineage (predecessor/successor chain from 2.2). Everything currently reachable only via six different screens appears or is one click deep from here.
- **PM-series record**: cadence (scheduled vs. observed), event history, gap findings with evidence, exclusions/supersessions affecting it, link up to the asset.
- **Mechanic record**: `mech_drill`/`mechanic_tl`/closed_by views unified under one person page.
- **Site dashboard**: the one landing page per site — compliance, open gaps by bucket, data freshness (`sync_health`), with every number a drill-down link into the hubs above. 

### 4.3 Navigation audit — merge or demote screens
Inventory all ~52 web screens. For each: is it (a) a hub (keep), (b) a worklist/queue that *acts* on entities (keep, but every row links to the hub page), or (c) a read-only slice of what a hub now shows (fold into the hub and delete)? Candidates for folding: the overlapping gap list variants, separate stale/retire/replacement list screens whose content becomes sections of the asset/series records, the standalone sync_health page. Target: a top nav of ~6-8 destinations (Home/site, Search, Gap Worklist, Corrective, Compliance, Reports, Admin), everything else reached *through* an entity, not hunted in a menu.
Every screen stays a URL (deep links and refresh keep working — that property is one of the app's best and must survive).

### 4.4 Breadcrumbs + provenance everywhere
`pathtrail.js` exists — make it universal: every page shows where you are (Site → Asset → PM series → Finding) and every number shows which engine produced it (one shared provenance footer already exists in `provenance.py` — surface it per-widget, not just per-export). The user should never wonder "is this the same number as the other screen" — after 2.1 it provably is, and the UI should say so.

### 4.5 E2E tests for the paths
For each of the top ~10 questions Antoine asks (e.g., "why does asset X show a gap", "who closed this PM", "is this month's data loaded for site Y", "what replaced this series"), add one E2E test that starts at the omnibox and asserts the answer is reachable in ≤3 clicks. These tests are the permanent guard against navigation regressions.

---

## Sequencing & acceptance

| Phase | Risk | Done when |
|---|---|---|
| 1 Repo completeness | Low | Fresh clone + `requirements*.txt` + documented externals can run pipeline, server, and full fixture test suite; docs match code |
| 2 Engine consolidation | Medium-high (2.1) | One stored gap answer; guard tests updated and green; prewarm/singleflight pieces removed only with before/after timings; matcher parity tests green |
| 3 Structure | Low-medium | Pure-move commits; no logic diffs; suite green |
| 4 UX | Medium | Omnibox + 4 hub pages live; screen inventory executed; ≤3-click E2E tests green |

Rules of engagement: one work package per commit/PR; never mix a move with a logic change; measure before deleting any performance machinery; anything ambiguous about *intent* (especially §3.4 deletions and §4.3 screen folding) gets a question to Antoine, not a guess. Preserve every behavior the guard tests encode — they are orders, not suggestions.
