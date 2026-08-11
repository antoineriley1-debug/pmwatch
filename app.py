import io
import os
import calendar as pycalendar
from datetime import datetime, date, timedelta
from urllib.parse import quote
from flask import (Flask, jsonify, request, render_template, redirect,
                   session, Response, send_file)
import scraper
import db
import checklists

app = Flask(__name__)

# Session signing key. Set APP_SECRET in Render so logins survive restarts;
# falls back to SCRAPE_TOKEN so sessions still work before it's set.
app.secret_key = (os.environ.get("APP_SECRET")
                  or os.environ.get("SCRAPE_TOKEN")
                  or "pmwatch-local-dev")
app.permanent_session_lifetime = timedelta(days=31)

# Paths that never require the password: login itself, liveness pings.
_OPEN_PATHS = {"/login", "/logout", "/ping", "/health"}


@app.before_request
def _require_auth():
    """Password gate for every UI page. Automation (cron/scrape/enrich)
    passes with ?token=SCRAPE_TOKEN as before. If APP_PASSWORD isn't set
    yet, the gate stays open so a missing env var can't lock you out."""
    p = request.path or "/"
    if p in _OPEN_PATHS or p.startswith("/static"):
        return None
    if _check_token():
        return None
    expected = os.environ.get("APP_PASSWORD", "").strip()
    if not expected:
        return None
    if session.get("auth") is True:
        return None
    return redirect("/login?next=" + quote(request.full_path or p, safe=""))


@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    error = None
    if request.method == "POST":
        expected = os.environ.get("APP_PASSWORD", "").strip()
        given = (request.form.get("password") or "").strip()
        if expected and given == expected:
            session.permanent = True
            session["auth"] = True
            return redirect(nxt)
        error = "Wrong password."
    return render_template("login.html", tab=None, error=error, next=nxt,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


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

    # Condense duplicates: identical PM types collapse into ONE row with a
    # count badge. Grouped view is the default; ?view=all shows every row.
    view = request.args.get("view", "grouped")
    groups = []
    if view != "all":
        gmap = {}
        for r in rows:
            key = r.get("system") or r.get("reason") or "(unclassified)"
            g = gmap.get(key)
            if not g:
                g = {"name": key, "count": 0, "sites": set(),
                     "mechanics": set(), "latest": None, "sample": r}
                gmap[key] = g
            g["count"] += 1
            if r.get("hospital_code"):
                g["sites"].add(r["hospital_code"])
            if r.get("closed_by"):
                g["mechanics"].add(r["closed_by"])
            d = r.get("close_date") or r.get("target_date")
            if d and (g["latest"] is None or d > g["latest"]):
                g["latest"] = d
        groups = sorted(gmap.values(),
                        key=lambda g: (-g["count"], g["name"]))
        for g in groups:
            g["sites"] = len(g["sites"])
            g["mechanics"] = sorted(g["mechanics"])[:3]

    # Data freshness: newest scrape timestamp across sites.
    fresh = None
    stamps = [s.get("last_scraped") for s in sites if s.get("last_scraped")]
    if stamps:
        age = (datetime.now() - max(stamps)).total_seconds()
        if age < 90:
            fresh = "just now"
        elif age < 5400:
            fresh = f"{int(age // 60)} min ago"
        else:
            fresh = f"{int(age // 3600)} hr ago"

    return render_template(
        "dashboard.html", view=view, groups=groups, fresh=fresh,
        tab="dashboard", sites=sites, systems=systems, rows=rows,
        selected=selected, order=order, system=system,
        net_today=net_today, net_week=net_week, net_total=net_total,
        updated=datetime.now().strftime("%b %d, %I:%M %p"),
    )


@app.route("/pms-view")
def pms_view():
    """Drill-down list: every clickable dashboard number lands here with a
    period/site/mechanic/system filter. Rows link to the single WO page."""
    selected = request.args.get("hospital")
    period = request.args.get("period")
    mechanic = request.args.get("mechanic")
    system = request.args.get("system")
    day = request.args.get("date")
    reason = request.args.get("reason")
    order = request.args.get("order", "close_date")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        rows = db.list_pms_filtered(hospital_code=selected, period=period,
                                    mechanic=mechanic, system=system,
                                    order=order, limit=1000, date=day,
                                    reason=reason)
    except Exception as e:
        return f"DB not ready: {e}", 200
    labels = {"today": "closed today", "yesterday": "closed yesterday",
              "week": "closed this week", "month": "closed this month"}
    ctx_label = f"closed {day}" if day else labels.get(period, "work orders")
    return render_template("pms_view.html", tab="dashboard", sites=sites,
                           rows=rows, selected=selected, period=period,
                           mechanic=mechanic, system=system, order=order,
                           ctx_label=ctx_label,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/wo/<path:wo_number>")
def wo_detail(wo_number):
    """Single work order: asset, mechanic, tasks/procedure, QC status.
    The drill-down target for every number on the dashboard."""
    try:
        db.init_db()
        wo = db.get_wo(wo_number)
    except Exception as e:
        return f"DB not ready: {e}", 200
    if not wo:
        return render_template("wo.html", tab="dashboard", wo=None,
                               wo_number=wo_number, checklist=None,
                               updated=datetime.now().strftime("%b %d, %I:%M %p")), 404
    # Attach the asset-specific checklist so QC can be done right here.
    atype = wo.get("qc_asset_type") or checklists.classify(
        wo.get("system"), wo.get("procedure"), wo.get("reason"), wo.get("asset_name"))
    clist = checklists.get_checklist(atype)
    back = request.args.get("back", "/")
    try:
        photos = db.photos_for_wo(wo_number)
    except Exception:
        photos = []
    return render_template("wo.html", tab="dashboard", wo=wo, photos=photos,
                           wo_number=wo_number, asset_type=atype,
                           checklist=clist, back=back,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


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
    show = request.args.get("show", "pending")  # pending | done | all
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        queue = db.qc_queue(hospital_code=selected, limit=300)
    except Exception as e:
        return f"DB not ready: {e}", 200
    if show == "pending":
        queue = [r for r in queue if not r.get("qc_result")]
    elif show == "done":
        queue = [r for r in queue if r.get("qc_result")]
    # Attach an asset-specific checklist to each pending item so the QC form
    # shows real things to check, not just pass/fail.
    for r in queue:
        atype = checklists.classify(r.get("system"), r.get("procedure"),
                                    r.get("reason"), r.get("asset_name"))
        r["asset_type"] = atype
        r["checklist"] = checklists.get_checklist(atype)
    return render_template("qc.html", tab="qc", sites=sites,
                           selected=selected, queue=queue, show=show,
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
        qc_id = db.add_qc_review(
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

    # Photo attachments: resize to <=1280px JPEG so Neon's free tier holds
    # plenty; skip anything unreadable rather than failing the whole QC.
    saved, skipped = 0, 0
    for fs in request.files.getlist("photos"):
        if not fs or not fs.filename:
            continue
        try:
            data = _shrink_photo(fs.read())
            if data:
                db.add_qc_photo(wo, data, qc_id=qc_id, caption=fs.filename)
                saved += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    back = f.get("back", "/qc")
    return redirect(back)


def _shrink_photo(raw, max_side=1280, quality=78):
    """Downscale an uploaded image to a small JPEG. Returns bytes or None."""
    if not raw:
        return None
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)          # respect phone orientation
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


@app.route("/photo/<int:photo_id>")
def photo(photo_id):
    got = db.get_qc_photo(photo_id)
    if not got:
        return "not found", 404
    mime, data = got
    return Response(data, mimetype=mime or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@app.route("/mechanics")
def mechanics():
    """Mechanics area: per-mechanic activity + active/inactive management."""
    selected = request.args.get("hospital")
    show = request.args.get("show", "all")  # all | active | inactive
    group = request.args.get("group", "all")  # all | staff | contractors
    focus = request.args.get("who")          # drill into one mechanic
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        include_inactive = show != "active"
        people = db.list_mechanics(hospital_code=selected,
                                   include_inactive=include_inactive)
        if show == "inactive":
            people = [p for p in people if not p.get("active")]
        if group == "staff":
            people = [p for p in people if not p.get("is_contractor")]
        elif group == "contractors":
            people = [p for p in people if p.get("is_contractor")]
        detail = db.mechanic_detail(focus) if focus else None
    except Exception as e:
        return f"DB not ready: {e}", 200

    net_today = sum((p.get("today") or 0) for p in people)
    active_n = sum(1 for p in people if p.get("active"))
    inactive_n = sum(1 for p in people if not p.get("active"))
    return render_template(
        "mechanics.html", tab="mechanics", sites=sites, people=people,
        selected=selected, show=show, group=group, focus=focus, detail=detail,
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
            is_contractor=(f.get("is_contractor") == "1"),
            company=f.get("company") or None,
        )
    except Exception as e:
        return f"save failed: {e}", 400
    return redirect(f.get("back", "/mechanics"))


def _period_start(per):
    """First day of the current month/quarter/year for an obligation
    frequency word. Unknown words default to month (safest, shortest)."""
    today = date.today()
    per = (per or "").strip().lower()
    if per.startswith("year") or per.startswith("annual"):
        return date(today.year, 1, 1), "this year"
    if per.startswith("quarter"):
        qm = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, qm, 1), "this quarter"
    if per.startswith("week"):
        return today - timedelta(days=today.weekday()), "this week"
    return date(today.year, today.month, 1), "this month"


def _parse_obligations(text):
    """Parse obligation lines 'keyword | qty | month/quarter/year' into
    [{keyword, qty, per}]. Lines missing parts get sane defaults. Blank
    lines ignored."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        kw = parts[0]
        if not kw:
            continue
        qty = None
        if len(parts) > 1:
            try:
                qty = int(parts[1])
            except (ValueError, TypeError):
                qty = None
        per = parts[2] if len(parts) > 2 else "month"
        out.append({"keyword": kw, "qty": qty or 1, "per": per})
    return out


def _contract_compliance(c):
    """For one contract, compare each obligation against actual closed-PM
    completions this period. Returns rows + an overall behind/on-track."""
    rows = []
    behind = False
    for ob in (c.get("obligations") or []):
        if not isinstance(ob, dict):
            continue
        kw = ob.get("keyword") or ob.get("asset") or ob.get("system")
        if not kw:
            continue
        qty = ob.get("qty") or 1
        since, period_label = _period_start(ob.get("per") or ob.get("frequency"))
        try:
            done = db.count_matching_pms(kw, hospital_code=c.get("hospital_code"),
                                         since=since)
        except Exception:
            done = None
        gap = (qty - done) if (done is not None) else None
        if gap is not None and gap > 0:
            behind = True
        rows.append({"keyword": kw, "qty": qty, "per": period_label,
                     "done": done, "gap": gap})
    return rows, behind


@app.route("/contracts")
def contracts():
    try:
        db.init_db()
        rows = db.list_contracts()
        sites = db.closed_today_by_site()
    except Exception as e:
        return f"DB not ready: {e}", 200
    # Obligated vs completed for every contract that has obligations.
    for c in rows:
        c["compliance"], c["behind"] = _contract_compliance(c)
    return render_template("contracts.html", tab="contracts",
                           contracts=rows, sites=sites,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/contracts/add", methods=["POST"])
def contracts_add():
    f = request.form
    obligations = _parse_obligations(f.get("obligations"))
    try:
        db.add_contract(
            vendor=f.get("vendor"),
            hospital_code=f.get("hospital_code") or None,
            scope=f.get("scope"),
            start_date=f.get("start_date") or None,
            end_date=f.get("end_date") or None,
            obligations=obligations or None,
            notes=f.get("notes"),
        )
    except Exception as e:
        return f"Contract save failed: {e}", 400
    return redirect("/contracts")


@app.route("/contracts/delete", methods=["POST"])
def contracts_delete():
    try:
        cid = int(request.form.get("id", "0"))
        db.delete_contract(cid)
    except Exception as e:
        return f"Delete failed: {e}", 400
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


@app.route("/search")
def search():
    """Global work-order search from the header box."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect("/")
    try:
        db.init_db()
        rows = db.search_wos(q)
        sites = db.closed_today_by_site()
    except Exception as e:
        return f"DB not ready: {e}", 200
    # One exact WO-number hit -> jump straight to it.
    if len(rows) == 1 or (rows and rows[0]["wo_number"].lower() == q.lower()):
        return redirect(f"/wo/{rows[0]['wo_number']}?back=/")
    return render_template("pms_view.html", tab="dashboard", sites=sites,
                           rows=rows, selected=None, period=None,
                           mechanic=None, system=None, order="close_date",
                           ctx_label=f'matching "{q}"',
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


@app.route("/insights")
def insights():
    """Scorecard: which sites are doing well/weak, which systems are
    failing QC. The 'notice stuff' view."""
    selected = request.args.get("hospital")
    try:
        db.init_db()
        sites = db.closed_today_by_site()
        site_cards = db.site_scorecard()
        systems = db.system_scorecard(hospital_code=selected)
    except Exception as e:
        return f"DB not ready: {e}", 200
    # Fraud/training flags: implausible daily volume + idle active mechanics.
    # Threshold configurable via FLAG_DAILY_PMS (default 12/day).
    try:
        thr = int(os.environ.get("FLAG_DAILY_PMS", "12"))
    except ValueError:
        thr = 12
    try:
        volume_flags = db.mechanic_daily_volumes(threshold=thr, days=60)
    except Exception:
        volume_flags = []
    try:
        idle = db.idle_active_mechanics()
    except Exception:
        idle = []

    # Flag weak/failing: pass_rate < 70 or fail count high.
    flags = []
    for s in site_cards:
        if s.get("pass_rate") is not None and s["pass_rate"] < 70:
            flags.append(f"{s.get('hospital_name') or s['hospital_code']} QC pass rate {s['pass_rate']}%")
    for sy in systems:
        if sy.get("pass_rate") is not None and sy["pass_rate"] < 70 and (sy.get("qc_done") or 0) >= 2:
            flags.append(f"System '{sy['system']}' failing QC ({sy['pass_rate']}% pass)")
    return render_template("insights.html", tab="insights", sites=sites,
                           selected=selected, site_cards=site_cards,
                           systems=systems, flags=flags,
                           volume_flags=volume_flags, idle=idle, thr=thr,
                           updated=datetime.now().strftime("%b %d, %I:%M %p"))


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
    mp = request.args.get("pages")
    max_pages = int(mp) if (mp or "").isdigit() else None
    return jsonify(scraper.scrape_hospital(
        hospital_code=hospital, store=store, enrich=enrich,
        enrich_limit=enrich_limit, enrich_offset=enrich_offset,
        max_pages=max_pages))


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
    mp = request.args.get("pages")  # light mode: newest N pages per site
    max_pages = int(mp) if (mp or "").isdigit() else None
    return jsonify(scraper.scrape_all(
        store=store, enrich=enrich, enrich_limit=enrich_limit,
        hospitals=hospitals, max_pages=max_pages))


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


@app.route("/calendar")
def calendar_view():
    """Per-hospital month calendar: each closed PM lands on its completion
    date, mechanic named on the tile. Prev/next month navigation."""
    sites = []
    try:
        db.init_db()
        sites = db.closed_today_by_site()
    except Exception as e:
        return f"DB not ready: {e}", 200
    selected = request.args.get("hospital") or (
        sites[0]["hospital_code"] if sites else "52626")
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month
    month = min(max(month, 1), 12)

    first = date(year, month, 1)
    last = date(year, month, pycalendar.monthrange(year, month)[1])
    items = db.pms_in_range(selected, first, last)

    by_day = {}
    for it in items:
        d = it.get("close_date")
        if d:
            by_day.setdefault(d.day, []).append(it)

    weeks = pycalendar.Calendar(firstweekday=6).monthdayscalendar(year, month)

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    sel_name = next((s.get("hospital_name") for s in sites
                     if s.get("hospital_code") == selected), None) or selected

    return render_template(
        "calendar.html", tab="calendar", sites=sites, selected=selected,
        sel_name=sel_name, year=year, month=month,
        month_name=first.strftime("%B %Y"), weeks=weeks, by_day=by_day,
        today=today, prev_y=prev_y, prev_m=prev_m, next_y=next_y,
        next_m=next_m, total=len(items),
        updated=datetime.now().strftime("%b %d, %I:%M %p"))


@app.route("/reports/pdf")
def reports_pdf():
    """Per-hospital QC report in the Crothall / MedStar layout:
    navy-and-gold branded title block (logo slots), executive summary
    written to the site's benefit, QC results table, findings, and
    captioned photo evidence."""
    selected = request.args.get("hospital")
    try:
        db.init_db()
        queue = db.qc_queue(hospital_code=selected, limit=500)
    except Exception as e:
        return f"DB not ready: {e}", 200

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, Image as RLImage,
                                    HRFlowable)

    NAVY = colors.HexColor("#1B3764")
    GOLD = colors.HexColor("#F2A900")
    LIGHT = colors.HexColor("#F4F6F8")

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           leading=10)
    h_title = ParagraphStyle("h_title", parent=styles["Title"], fontSize=20,
                             textColor=NAVY, spaceAfter=2)
    h_sub = ParagraphStyle("h_sub", parent=styles["Normal"], fontSize=11,
                           textColor=NAVY)
    h_sec = ParagraphStyle("h_sec", parent=styles["Heading2"], fontSize=13,
                           textColor=NAVY, spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10,
                          leading=14)
    cap = ParagraphStyle("cap", parent=styles["Normal"], fontSize=8,
                         textColor=colors.HexColor("#555555"))

    site_label = "All Sites"
    for s in db.closed_today_by_site():
        if selected and s.get("hospital_code") == selected:
            site_label = s.get("hospital_name") or selected
            break

    passc = sum(1 for r in queue if r.get("qc_result") == "pass")
    failc = sum(1 for r in queue if r.get("qc_result") == "fail")
    reviewed = passc + failc
    rate = round(100 * passc / reviewed) if reviewed else 0

    prepared_by = os.environ.get(
        "REPORT_PREPARED_BY",
        "Antoine W. Riley Sr — Director of System Maintenance, "
        "Crothall Healthcare")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.55 * inch,
                            bottomMargin=0.6 * inch, leftMargin=0.65 * inch,
                            rightMargin=0.65 * inch)
    story = []

    # ---- Title block with logo slots (drop medstar.png / crothall.png
    # into /static and they render automatically) ----
    def _logo(fname, w):
        p = os.path.join(app.static_folder or "static", fname)
        if os.path.exists(p):
            try:
                img = RLImage(p)
                scale = min(w / img.imageWidth, (0.6 * inch) / img.imageHeight)
                img.drawWidth = img.imageWidth * scale
                img.drawHeight = img.imageHeight * scale
                return img
            except Exception:
                return None
        return None

    ms = _logo("medstar.png", 1.9 * inch)
    cr = _logo("crothall.png", 1.9 * inch)
    if ms or cr:
        story.append(Table(
            [[ms or "", cr or ""]],
            colWidths=[3.6 * inch, 3.6 * inch],
            style=TableStyle([
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ])))
        story.append(Spacer(1, 8))
    else:
        story.append(Paragraph(
            "<b>MedStar Health</b> &nbsp;|&nbsp; <b>Crothall Healthcare</b>",
            h_sub))
        story.append(Spacer(1, 4))

    story.append(HRFlowable(width="100%", thickness=3, color=GOLD))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Preventative Maintenance", h_title))
    story.append(Paragraph("Quality Control Report", h_title))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>{site_label}</b>", h_sub))
    story.append(Paragraph(
        datetime.now().strftime("%B %d, %Y"), body))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Prepared by: {prepared_by}", cap))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY))

    # ---- Executive summary (written to the site's benefit) ----
    story.append(Paragraph("Executive Summary", h_sec))
    if reviewed:
        summary = (
            f"During this reporting period, <b>{len(queue)}</b> preventative "
            f"maintenance work orders were completed at {site_label}. Of "
            f"these, <b>{reviewed}</b> received a documented quality-control "
            f"review with an overall pass rate of <b>{rate}%</b> "
            f"({passc} pass / {failc} requiring follow-up). The preventative "
            f"maintenance program remains active and producing, and the "
            f"items identified below have been documented for corrective "
            f"follow-up and coaching.")
    else:
        summary = (
            f"During this reporting period, <b>{len(queue)}</b> preventative "
            f"maintenance work orders were completed at {site_label}. "
            f"Quality-control reviews are underway; results will populate "
            f"this report as they are documented.")
    story.append(Paragraph(summary, body))

    # ---- Portfolio scorecard (executive rollup, all-sites report) ----
    if not selected:
        try:
            cards = db.site_scorecard()
        except Exception:
            cards = []
        if cards:
            story.append(Paragraph("Portfolio Scorecard", h_sec))
            sdata = [["Site", "Completed", "QC'd", "Pass", "Fail",
                      "Pass Rate", "Avg Score"]]
            for s in cards:
                pr = s.get("pass_rate")
                sdata.append([
                    Paragraph(str(s.get("hospital_name")
                                  or s.get("hospital_code")), small),
                    Paragraph(str(s.get("total") or 0), small),
                    Paragraph(str(s.get("qc_done") or 0), small),
                    Paragraph(str(s.get("qc_pass") or 0), small),
                    Paragraph(str(s.get("qc_fail") or 0), small),
                    Paragraph("—" if pr is None else f"{pr}%", small),
                    Paragraph("—" if s.get("avg_score") is None
                              else str(int(s["avg_score"])), small),
                ])
            stable = Table(sdata, colWidths=[2.3 * inch, 0.8 * inch,
                                             0.6 * inch, 0.55 * inch,
                                             0.55 * inch, 0.8 * inch,
                                             0.8 * inch], repeatRows=1)
            stable.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, GOLD),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, LIGHT]),
            ]))
            story.append(stable)

    # ---- Results table ----
    story.append(Paragraph("QC Results", h_sec))
    data = [["WO #", "System / Task", "Mechanic", "Closed", "QC", "Score"]]
    for r in queue:
        data.append([
            Paragraph(str(r.get("wo_number") or ""), small),
            Paragraph(str(r.get("system") or r.get("reason") or "—")[:70],
                      small),
            Paragraph(str(r.get("closed_by") or "—"), small),
            Paragraph(str(r.get("close_date") or "—"), small),
            Paragraph((r.get("qc_result") or "pending").upper(), small),
            Paragraph("" if r.get("qc_score") is None else str(r["qc_score"]),
                      small),
        ])
    table = Table(data, colWidths=[1.0 * inch, 2.5 * inch, 1.4 * inch,
                                   0.8 * inch, 0.7 * inch, 0.5 * inch],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, GOLD),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]))
    story.append(table)

    # ---- Findings (failed QCs with notes) ----
    fails = [r for r in queue if r.get("qc_result") == "fail"]
    if fails:
        story.append(Paragraph("Findings &amp; Follow-Up Items", h_sec))
        for r in fails:
            wo = db.get_wo(r["wo_number"]) or {}
            note = wo.get("qc_notes") or "Documented during QC review."
            story.append(Paragraph(
                f"<b>{r['wo_number']}</b> — "
                f"{r.get('system') or r.get('reason') or 'PM'}: {note}",
                body))
            story.append(Spacer(1, 3))

    # ---- QC Activity Log: the executive audit trail ----
    try:
        log = db.qc_activity_log(hospital_code=selected, limit=300)
    except Exception:
        log = []
    if log:
        story.append(Paragraph("QC Activity Log — Review Audit Trail", h_sec))
        story.append(Paragraph(
            "Chronological record of quality-control reviews performed, "
            "documenting the reviewer, verdict, and timing of each "
            "inspection.", cap))
        story.append(Spacer(1, 4))
        ldata = [["Date / Time", "WO #", "Site", "Task", "Mechanic",
                  "Verdict", "Reviewer"]]
        for e in log:
            ts = e.get("created_at")
            ts_s = ts.strftime("%m/%d/%y %I:%M %p") if ts else "—"
            verdict = (e.get("result") or "").upper()
            if e.get("score") is not None:
                verdict += f" ({e['score']})"
            ldata.append([
                Paragraph(ts_s, small),
                Paragraph(str(e.get("wo_number") or ""), small),
                Paragraph(str(e.get("hospital_code") or ""), small),
                Paragraph(str(e.get("system") or e.get("reason")
                              or "—")[:50], small),
                Paragraph(str(e.get("closed_by") or "—"), small),
                Paragraph(verdict, small),
                Paragraph(str(e.get("reviewer") or "director"), small),
            ])
        ltable = Table(ldata, colWidths=[0.95 * inch, 0.95 * inch,
                                         0.5 * inch, 1.8 * inch,
                                         1.15 * inch, 0.75 * inch,
                                         0.8 * inch], repeatRows=1)
        ltable.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, GOLD),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ]))
        story.append(ltable)

    # ---- Photo evidence, captioned in the tour-report style ----
    wo_nums = [r["wo_number"] for r in queue if r.get("qc_result")]
    counts = db.photo_counts(wo_nums) if wo_nums else {}
    added = 0
    if any(counts.values()):
        story.append(Paragraph("Photo Documentation", h_sec))
    for wo_num in wo_nums:
        if added >= 40:
            break
        if not counts.get(wo_num):
            continue
        meta = db.photos_for_wo(wo_num)[:4]
        row_imgs, row_caps = [], []
        for ph in meta:
            got = db.get_qc_photo(ph["id"])
            if not got:
                continue
            _, raw = got
            img = RLImage(io.BytesIO(raw))
            scale = min((3.3 * inch) / img.imageWidth,
                        (2.5 * inch) / img.imageHeight, 1)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
            row_imgs.append(img)
            row_caps.append(Paragraph(
                f"WO {wo_num}" + (f" — {ph['caption']}" if ph.get("caption")
                                  else ""), cap))
            added += 1
        if row_imgs:
            story.append(Spacer(1, 6))
            story.append(Table([row_imgs, row_caps]))

    # ---- Footer line ----
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY))
    story.append(Paragraph(
        "Generated by PMWATCH — Crothall Healthcare Systems Maintenance, "
        "MedStar Health portfolio · "
        + datetime.now().strftime("%m/%d/%Y %I:%M %p"), cap))

    doc.build(story)
    buf.seek(0)
    fname = (f"QC_Report_{(site_label or 'All').replace(' ', '_')}_"
             f"{date.today().isoformat()}.pdf")
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=fname)


@app.route("/audit")
def audit():
    """Accuracy audit: per-site stored totals + prefix-mismatch counts +
    per-site MC ground truth is compared during /scrape (mc_reported_total).
    Token-gated."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        db.init_db()
        return jsonify({
            "prefix_report": db.prefix_mismatch_report(),
            "coverage": db.coverage_stats(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/cleanup-mismatch")
def cleanup_mismatch():
    """Delete rows whose WO prefix disagrees with their hospital_code
    (contamination from a failed site switch). Token-gated."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    try:
        deleted = db.delete_prefix_mismatches()
        return jsonify({"deleted": deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/wipe-all")
def wipe_all():
    """Full reset of scraped PM data for a clean, accurate re-scrape.
    Requires ?confirm=WIPE on top of the token. QC reviews on wiped rows
    are removed too — use only before real QC work has accumulated."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    if request.args.get("confirm") != "WIPE":
        return jsonify({"error": "add &confirm=WIPE to really do this"}), 400
    try:
        deleted = db.wipe_all_pms()
        return jsonify({"deleted": deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
