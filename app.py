import os
from datetime import datetime
from flask import Flask, jsonify, request, render_template, redirect
import scraper
import db
import checklists

app = Flask(__name__)


def _scrape_token():
    """Read the token at REQUEST time, not import time.
    A module-level constant can freeze to "" if the worker imported
    before the env var was populated. Strip stray paste whitespace.
    """
    return os.environ.get("SCRAPE_TOKEN", "").strip()


def _check_token():
    token = request.args.get("token", "").strip()
    expected = _scrape_token()
    return bool(expected) and token == expected


@app.route("/")
def home():
    """Dashboard: PMs closed today per site + network total, drill-down."""
    selected = request.args.get("hospital")
    order = request.args.get("order", "close_date")
    system = request.args.get("system")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        systems = db.system_breakdown(hospital_code=selected)
        rows = db.list_pms(hospital_code=selected, system=system, order=order, limit=500)
        # Fall back to the known name map when a site's stored name is blank.
        for s in sites:
            if not s.get("hospital_name"):
                s["hospital_name"] = scraper.HOSPITAL_NAMES.get(s.get("hospital_code"))
    except Exception as e:
        return f"PMWATCH is running. (DB not ready: {e})", 200

    net_today = sum((s.get("today") or 0) for s in sites)
    net_week = sum((s.get("week") or 0) for s in sites)
    net_total = sum((s.get("total") or 0) for s in sites)

    return render_template(
        "dashboard.html",
        tab="dashboard", sites=sites, systems=systems, rows=rows,
        selected=selected, order=order, system=system,
        net_today=net_today, net_week=net_week, net_total=net_total,
        updated=datetime.now().strftime("%b %d, %I:%M %p"),
    )


@app.route("/trends")
def trends():
    selected = request.args.get("hospital")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        net_trend = db.completion_trend(days=30)
        site_trend = db.completion_trend(hospital_code=selected, days=30) if selected else []
    except Exception as e:
        return f"DB not ready: {e}", 200
    return render_template("trends.html", tab="trends", sites=sites,
                           selected=selected, net_trend=net_trend,
                           site_trend=site_trend,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/qc")
def qc():
    selected = request.args.get("hospital")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        queue = db.qc_queue(hospital_code=selected, limit=200)
    except Exception as e:
        return f"DB not ready: {e}", 200
    # Attach an asset-specific checklist to each pending item so the QC form
    # shows real things to check, not just pass/fail.
    for r in queue:
        atype = checklists.classify(r.get("system"), r.get("procedure"),
                                    r.get("reason"), r.get("asset_name"))
        r["asset_type"] = atype
        r["checklist"] = checklists.get_checklist(atype)
    return render_template("qc.html", tab="qc", sites=sites,
                           selected=selected, queue=queue,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/qc/submit", methods=["POST"])
def qc_submit():
    f = request.form
    wo = f.get("wo_number")
    asset_type = f.get("asset_type") or "generic"
    # Rebuild the checklist item results from the submitted checkboxes.
    # The form posts item ids under 'item_<id>' when checked; we render the
    # full item set from the template so we know the complete list.
    clist = checklists.get_checklist(asset_type)
    item_results = []
    for iid, label in clist["items"]:
        item_results.append({
            "id": iid,
            "label": label,
            "ok": f.get(f"item_{iid}") == "1",
        })
    auto_score, passed, total = checklists.score_from_checklist(item_results)

    # Result: explicit pass/fail radio wins; otherwise derive from score
    # (>=80% and no critical miss = pass). Manual score overrides auto.
    result = f.get("qc_result") or f.get("result")
    if not result:
        result = "pass" if (auto_score is not None and auto_score >= 80) else "fail"
    manual_score = f.get("qc_score") or f.get("score")
    score = int(manual_score) if manual_score else auto_score

    try:
        db.add_qc_review(
            wo_number=wo,
            result=result,
            score=score,
            notes=f.get("notes"),
            reviewer=f.get("reviewer") or "director",
            asset_type=asset_type,
            checklist=item_results,
        )
    except Exception as e:
        return f"QC save failed: {e}", 400
    return redirect(f.get("back", "/qc"))


@app.route("/mechanics")
def mechanics():
    """Mechanics area: per-mechanic activity + active/inactive management."""
    selected = request.args.get("hospital")
    show = request.args.get("show", "all")  # all | active | inactive
    focus = request.args.get("who")          # drill into one mechanic
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        include_inactive = show != "active"
        people = db.list_mechanics(hospital_code=selected,
                                   include_inactive=include_inactive)
        if show == "inactive":
            people = [p for p in people if not p.get("active")]
        detail = db.mechanic_detail(focus) if focus else None
    except Exception as e:
        return f"DB not ready: {e}", 200

    net_today = sum((p.get("today") or 0) for p in people)
    active_n = sum(1 for p in people if p.get("active"))
    inactive_n = sum(1 for p in people if not p.get("active"))
    return render_template(
        "mechanics.html", tab="mechanics", sites=sites, people=people,
        selected=selected, show=show, focus=focus, detail=detail,
        net_today=net_today, active_n=active_n, inactive_n=inactive_n,
        updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/mechanics/toggle", methods=["POST"])
def mechanics_toggle():
    """Flip a mechanic active<->inactive. 'inactive' = someone who left."""
    f = request.form
    name = (f.get("name") or "").strip()
    active = f.get("active") == "1"
    if not name:
        return "missing name", 400
    try:
        db.set_mechanic_active(name, active)
    except Exception as e:
        return f"toggle failed: {e}", 400
    return redirect(f.get("back", "/mechanics"))


@app.route("/mechanics/save", methods=["POST"])
def mechanics_save():
    """Edit a mechanic's roster fields (display name, trade, home site, notes)."""
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        return "missing name", 400
    try:
        db.upsert_mechanic(
            name=name,
            display_name=f.get("display_name") or None,
            hospital_code=f.get("hospital_code") or None,
            trade=f.get("trade") or None,
            notes=f.get("notes") or None,
        )
    except Exception as e:
        return f"save failed: {e}", 400
    return redirect(f.get("back", "/mechanics"))


@app.route("/contracts")
def contracts():
    try:
        db.init_db()
        rows = db.list_contracts()
        sites = db.closed_today_by_site()
    except Exception as e:
        return f"DB not ready: {e}", 200
    return render_template("contracts.html", tab="contracts",
                           contracts=rows, sites=sites,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/contracts/add", methods=["POST"])
def contracts_add():
    f = request.form
    try:
        db.add_contract(
            vendor=f.get("vendor"),
            hospital_code=f.get("hospital_code") or None,
            scope=f.get("scope"),
            start_date=f.get("start_date") or None,
            end_date=f.get("end_date") or None,
            notes=f.get("notes"),
        )
    except Exception as e:
        return f"Contract save failed: {e}", 400
    return redirect("/contracts")


@app.route("/reports")
def reports():
    selected = request.args.get("hospital")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        queue = db.qc_queue(hospital_code=selected, limit=500)
    except Exception as e:
        return f"DB not ready: {e}", 200
    return render_template("reports.html", tab="reports", sites=sites,
                           selected=selected, queue=queue,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/ping")
def ping():
    return "PMWATCH is running."


@app.route("/migrate")
def migrate():
    """Run the schema/migration and report per-statement results.
    Token-gated. Use to confirm columns/tables applied on the live DB."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        report = db.init_db(verbose=True)
        cols = db.table_columns("closed_pms")
        return jsonify({
            "ran": len(report),
            "failures": [r for r in report if not r.get("ok")],
            "closed_pms_columns": cols,
            "report": report,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/enrich")
def enrich():
    """Standalone resumable enrichment: fill in mechanic + close_date +
    system for unenriched WOs (newest first). Safe to call repeatedly; each
    call chips away at the backlog. ?limit=N (default 40), ?hospital=CODE."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        limit = int(request.args.get("limit", "40"))
    except ValueError:
        limit = 40
    hospital = request.args.get("hospital")
    direct = request.args.get("direct", "1") != "0"
    return jsonify(scraper.enrich_backlog(limit=limit, hospital=hospital,
                                          prefer_direct=direct))


@app.route("/stats")
def stats():
    """Coverage stats: how much of the data is enriched (mechanic + close
    date + system) per site. Tells us if the pipeline is actually feeding
    the mechanic/date/system tracking the dashboard needs."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        db.init_db()
        return jsonify(db.coverage_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    """Liveness + DB connectivity check."""
    out = {"app": "ok"}
    try:
        db.init_db()  # idempotent: creates closed_pms + indexes if missing
        out["stored_pms"] = db.count_pms()
        out["db"] = "ok"
    except Exception as e:
        out["db"] = "error"
        out["db_error"] = str(e)
    return jsonify(out)


@app.route("/test-login")
def test_login():
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    return jsonify(scraper.test_login())


@app.route("/discover")
def discover():
    """Step 2 discovery: dump MC's real list/nav structure for one hospital."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    rc = request.args.get("repaircenter", "52626")
    return jsonify(scraper.discover(repaircenter=rc))


@app.route("/scrape")
def scrape():
    """Step 2: scrape closed PMs for one hospital into Neon.
    Default hospital 52626. ?store=0 to dry-run without writing."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    hospital = request.args.get("hospital", "52626")
    store = request.args.get("store", "1") != "0"
    enrich = request.args.get("enrich", "1") != "0"
    try:
        enrich_limit = int(request.args.get("enrich_limit", "15"))
    except ValueError:
        enrich_limit = 15
    try:
        enrich_offset = int(request.args.get("enrich_offset", "0"))
    except ValueError:
        enrich_offset = 0
    return jsonify(scraper.scrape_hospital(
        hospital_code=hospital, store=store, enrich=enrich,
        enrich_limit=enrich_limit, enrich_offset=enrich_offset))


@app.route("/backfill-names")
def backfill_names():
    """Write hospital names for all rows from the known code->name map.
    Fixes sites that stored a bare code because live-name capture missed."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        db.init_db()
        updated = db.backfill_hospital_names(scraper.HOSPITAL_NAMES)
        return jsonify({"updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/probe-paging")
def probe_paging():
    """Diagnostic: scrape ONE hospital with store off and return the paging
    controls + record count + row count so we can see MC's real pagination."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    hospital = request.args.get("hospital", "52626")
    out = scraper.scrape_hospital(hospital_code=hospital, store=False,
                                  enrich=False)
    return jsonify({
        "hospital": hospital,
        "raw_row_count": out.get("raw_row_count"),
        "parsed_count": out.get("parsed_count"),
        "paging": out.get("paging"),
        "paging_error": out.get("paging_error"),
        "show_all_error": out.get("show_all_error"),
        "list_url": out.get("list_url"),
        "last_step": out.get("last_step"),
        "error": out.get("error"),
    })


@app.route("/scrape-all")
def scrape_all():
    """Scrape CLOSED PMs for EVERY hospital in the portfolio in one login.
    This is what the cron should hit so all 10 hospitals stay current.
    ?store=0 dry-run. ?enrich=0 skip detail enrichment.
    ?enrich_limit=N detail fetches per hospital (default 8)."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    store = request.args.get("store", "1") != "0"
    enrich = request.args.get("enrich", "1") != "0"
    try:
        enrich_limit = int(request.args.get("enrich_limit", "8"))
    except ValueError:
        enrich_limit = 8
    only = request.args.get("hospitals")  # optional CSV subset
    hospitals = [h.strip() for h in only.split(",")] if only else None
    return jsonify(scraper.scrape_all(
        store=store, enrich=enrich, enrich_limit=enrich_limit,
        hospitals=hospitals))


@app.route("/pms")
def pms():
    """Inspect stored closed PMs."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    hospital = request.args.get("hospital")
    return jsonify({
        "count": db.count_pms(hospital),
        "recent": db.recent_pms(limit=50, hospital_code=hospital),
    })
