import os
import re
import db
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://app.maintenanceconnection.com/cav3/login"

# Base of the internal frameset app discovered during Step 1.
APP_BASE = "https://app.maintenanceconnection.com/mcv18/mapp_v2026.8"

# Discovered in Step 2: MC's internal repaircenter IDs keyed by hospital code.
# 52626 (MedStar Washington Hospital Center) => internal id 4.
REPAIRCENTER_IDS = {
    "52626": "4",
    "52625": "2",
    "52624": "8",
    "52623": "12",
    "52622": "11",
    "52621": "9",
    "52620": "10",
    "52619": "5",
    "52618": "7",
    "52617": "6",
    "52604": "24",
}

# Known MedStar facility names keyed by hospital code. Used as a fallback
# label; the scraper also captures the live name from the Repair Center
# dropdown and stores whatever it finds. Update any of these if the portal
# shows a different official name.
HOSPITAL_NAMES = {
    "52626": "MedStar Washington Hospital Center",
    "52625": "MedStar Georgetown University Hospital",
    "52624": "MedStar Southern Maryland Hospital Center",
    "52623": "MedStar St. Mary's Hospital",
    "52622": "MedStar Harbor Hospital",
    "52621": "MedStar Good Samaritan Hospital",
    "52620": "MedStar Union Memorial Hospital",
    "52619": "MedStar Franklin Square Medical Center",
    "52618": "MedStar Montgomery Medical Center",
    "52617": "MedStar National Rehabilitation Hospital",
    "52604": "MedStar Health",
}

# All portfolio hospital codes, in the order we want to scrape them.
ALL_HOSPITALS = [
    "52626", "52625", "52624", "52623", "52622",
    "52621", "52620", "52619", "52618", "52617",
]


def _launch(p):
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
    )
    context = browser.new_context(viewport={"width": 1500, "height": 950})
    return browser, context


def _login(context, result):
    """Runs the verified 2-step login + app picker, returns the active
    Work Center page. Appends progress to result['steps'] and updates
    result['last_step'] so any failure names the exact step. Never silent.
    """
    username = os.environ.get("MC_USERNAME")
    password = os.environ.get("MC_PASSWORD")
    if not username or not password:
        raise RuntimeError("MC_USERNAME or MC_PASSWORD not set in environment variables")

    page = context.new_page()

    result["last_step"] = "goto-login"
    page.goto(LOGIN_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=60000)
    result["steps"].append("Opened login page")

    result["last_step"] = "enter-member-id"
    id_box = page.locator(
        "input[type='text']:visible, input[type='email']:visible"
    ).first
    id_box.wait_for(state="visible", timeout=30000)
    id_box.fill(username)
    page.get_by_role("button", name="Next").click()
    result["steps"].append("Entered Member ID, clicked Next")

    result["last_step"] = "enter-password"
    pw_box = page.locator("input[type='password']")
    pw_box.wait_for(state="visible", timeout=30000)
    pw_box.fill(password)
    page.get_by_role("button", name="Next").click()
    result["steps"].append("Entered password, clicked Next")

    result["last_step"] = "application-picker"
    picker = page.get_by_text("Operations Work Center")
    picker.wait_for(state="visible", timeout=30000)
    result["steps"].append("Reached the application picker")
    picker.click()

    result["last_step"] = "open-work-center"
    page.wait_for_timeout(8000)
    active = context.pages[-1]
    active.wait_for_load_state("domcontentloaded", timeout=60000)
    try:
        active.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    active.wait_for_timeout(6000)
    result["steps"].append("Opened the MRO Work Center")
    return active


def test_login():
    """Step 1 proof: login and confirm we reached the Work Center."""
    result = {"steps": [], "success": False, "last_step": "init"}
    with sync_playwright() as p:
        browser, context = _launch(p)
        try:
            active = _login(context, result)
            result["last_step"] = "verify-content"
            result["page_title"] = active.title()
            result["url"] = active.url
            texts = []
            for fr in active.frames:
                try:
                    texts.append(fr.inner_text("body"))
                except Exception:
                    pass
            all_text = "\n".join(texts).lower()
            result["found_medstar"] = "medstar" in all_text
            result["found_work_orders"] = "work order" in all_text
            result["found_repair_center"] = "repair center" in all_text
            result["success"] = (
                result["found_medstar"]
                or result["found_work_orders"]
                or result["found_repair_center"]
            )
            result["last_step"] = "done"
        except Exception as e:
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
        finally:
            browser.close()
    return result


def _frame_for(active, needle):
    """Return the first frame whose URL contains needle, else None."""
    for fr in active.frames:
        if needle in (fr.url or ""):
            return fr
    return None


def discover(repaircenter="52626"):
    """Step 2 discovery pass.

    Logs into the Work Center and DUMPS the real structure we need to
    scrape closed PMs for one hospital: the Repair Center options, the
    saved-view/status options, and the work-order list frame's columns
    and first rows. This tells us MC's actual labels/selectors so the
    extraction step is built on facts, not guesses. Fails loudly.
    """
    result = {"steps": [], "success": False, "last_step": "init",
              "target_repaircenter": repaircenter}
    with sync_playwright() as p:
        browser, context = _launch(p)
        try:
            active = _login(context, result)

            # --- Map every frame so we know the app layout ---
            result["last_step"] = "map-frames"
            frames = []
            for fr in active.frames:
                url = fr.url or ""
                try:
                    txt = fr.inner_text("body")
                except Exception:
                    txt = ""
                frames.append({"url": url, "chars": len(txt)})
            result["frames"] = frames

            # --- Find the work-order list frame (mc_list.asp) ---
            result["last_step"] = "find-list-frame"
            list_fr = _frame_for(active, "mc_list.asp")
            result["list_frame_found"] = list_fr is not None
            if list_fr:
                result["list_frame_url"] = list_fr.url

                # Column headers of the WO list table.
                try:
                    headers = list_fr.eval_on_selector_all(
                        "th, .listheader, .gridheader, table tr:first-child td",
                        "els => els.map(e => (e.innerText||'').trim()).filter(Boolean).slice(0,40)",
                    )
                except Exception as e:
                    headers = [f"<header read error: {e}>"]
                result["list_headers"] = headers

                # First several data rows as raw text, so we see real values.
                try:
                    rows = list_fr.eval_on_selector_all(
                        "table tr",
                        "els => els.slice(0,8).map(tr => "
                        "Array.from(tr.querySelectorAll('td,th'))"
                        ".map(td => (td.innerText||'').trim()))",
                    )
                except Exception as e:
                    rows = [[f"<row read error: {e}>"]]
                result["list_sample_rows"] = rows

                # The raw query string tells us status/repaircenter params.
                m = re.search(r"\?(.*)$", list_fr.url)
                result["list_query"] = m.group(1) if m else None

            # --- Find the toc/nav frame with saved-view + repair center controls ---
            result["last_step"] = "find-nav-frame"
            toc_fr = _frame_for(active, "toctop.asp") or _frame_for(active, "toc.asp")
            if toc_fr:
                result["nav_frame_url"] = toc_fr.url
                try:
                    selects = toc_fr.eval_on_selector_all(
                        "select",
                        "els => els.map(s => ({name: s.name||s.id||'', "
                        "options: Array.from(s.options).map(o => "
                        "({text:(o.text||'').trim(), value:o.value})).slice(0,60)}))",
                    )
                except Exception as e:
                    selects = [{"error": str(e)}]
                result["nav_selects"] = selects

            # --- Look across ALL frames for any <select> (repair center / views) ---
            result["last_step"] = "scan-all-selects"
            all_selects = []
            for fr in active.frames:
                try:
                    sels = fr.eval_on_selector_all(
                        "select",
                        "els => els.map(s => ({name: s.name||s.id||'', "
                        "count: s.options.length, "
                        "options: Array.from(s.options).map(o => "
                        "({text:(o.text||'').trim(), value:o.value})).slice(0,40)}))",
                    )
                    for s in sels:
                        s["frame"] = fr.url
                    all_selects.extend(sels)
                except Exception:
                    pass
            result["all_selects"] = all_selects

            result["success"] = list_fr is not None
            result["last_step"] = "done"
        except Exception as e:
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
        finally:
            browser.close()
    return result


def _build_closed_pm_url(list_url, repaircenter_id):
    """Rewrite the live mc_list.asp URL to fetch CLOSED PREVENTIVE WOs
    for one repair center. Preserves session params (userpk etc.),
    overrides only the filter params we control.

    status=CLOSEDALL  -> all closed work orders
    wotype=PM         -> preventive only (correctives excluded at source)
    """
    parts = urlsplit(list_url)
    q = parse_qs(parts.query, keep_blank_values=True)
    # Flatten single-value lists.
    q = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
    q["status"] = "CLOSEDALL"
    q["repaircenter"] = str(repaircenter_id)
    q["wotype"] = "PM"
    q["pagesize"] = "2000"
    q["page"] = "1"
    q["sortfield"] = "CLOSEDATE DESC"
    q["init"] = "y"
    q["initdd"] = "y"
    new_query = urlencode(q, safe=" %")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


def _build_show_all_url(list_url):
    """Rewrite the live mc_list.asp URL to render ALL closed PMs on one page.

    MC paginates the grid (~48 rows/page). Its URL already knows the real
    record count via pagesize; we set a large pagesize, jump to page 1, and
    flip sallpages=1 (MC's 'show all pages' flag) so every row renders and
    can be read in a single pass. Preserves all session/filter params.
    """
    if not list_url or "mc_list.asp" not in list_url:
        return None
    parts = urlsplit(list_url)
    q = parse_qs(parts.query, keep_blank_values=True)
    q = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
    # Keep MC's own pagesize if it's already large; otherwise force big.
    try:
        cur_ps = int(q.get("pagesize", "0"))
    except ValueError:
        cur_ps = 0
    q["pagesize"] = str(max(cur_ps, 5000))
    q["page"] = "1"
    q["sallpages"] = "1"        # show-all flag observed in the paging DOM
    q["init"] = "n"
    q["initdd"] = "n"
    new_query = urlencode(q, safe=" %")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _try_set_pm_type(nav_fr, result):
    """Find the nav <select> whose options include Preventive/PM and set it,
    so the list is PM-ONLY at the source. Discovers the select by its
    OPTIONS (never guesses a name). Records what it found either way."""
    try:
        info = nav_fr.evaluate(
            """() => Array.from(document.querySelectorAll('select')).map(s => ({
                   name: s.name || s.id || '',
                   opts: Array.from(s.options).map(o => ({
                       t: (o.text||'').trim(), v: o.value })).slice(0, 40)
               }))"""
        )
    except Exception as e:
        result["pm_type_error"] = f"scan: {e}"
        return False
    target, val, label = None, None, None
    for s in info or []:
        nm = (s.get("name") or "").lower()
        if "repaircenter" in nm or "status" in nm:
            continue
        for o in s.get("opts") or []:
            t = (o.get("t") or "").strip().lower()
            v = (o.get("v") or "").strip()
            if t in ("pm", "preventive", "preventative") or                "preventive" in t or "preventative" in t or v.upper() == "PM":
                target, val, label = s.get("name"), o.get("v"), o.get("t")
                break
        if target:
            break
    result["pm_type_select"] = target
    result["pm_type_option"] = label
    if not target:
        return False
    try:
        nav_fr.evaluate(
            """(a) => {
                const s = document.querySelector(`select[name='${a.n}']`)
                       || document.getElementById(a.n);
                if (s) { s.value = a.v;
                    s.dispatchEvent(new Event('change', {bubbles:true}));
                    if (typeof checksearch === 'function') {
                        try { checksearch(s); } catch(e){} } }
            }""",
            {"n": target, "v": val},
        )
        result["pm_type_set"] = val
        return True
    except Exception as e:
        result["pm_type_error"] = f"set: {e}"
        return False


def _grid_total(list_fr):
    """Read MC's OWN record count from the grid ('x - y of N' or 'N records').
    This is the ground truth we prove our row count against."""
    try:
        return list_fr.evaluate(
            r"""() => {
                const b = document.body.innerText || '';
                // Only a real pager pattern counts: '1 - 355 of 2489'.
                let m = b.match(/\d[\d,]*\s*-\s*\d[\d,]*\s+of\s+(\d[\d,]*)/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                m = b.match(/(\d[\d,]*)\s+records?\b/i);
                if (m) return parseInt(m[1].replace(/,/g, ''));
                return null; }"""
        )
    except Exception:
        return None


def _build_page_url(list_url, page):
    """Same list URL, specific page, show-all OFF (so paging works)."""
    if not list_url or "mc_list.asp" not in list_url:
        return None
    parts = urlsplit(list_url)
    q = parse_qs(parts.query, keep_blank_values=True)
    q = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
    q["page"] = str(page)
    q["sallpages"] = "0"
    q["init"] = "n"
    q["initdd"] = "n"
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(q, safe=" %"), ""))


_ROW_READ_JS = r"""els => els.map(tr => {
    const cb = tr.querySelector("input[name='mckeyvalues']");
    const cells = Array.from(tr.querySelectorAll('td.browsedatacol'))
        .map(td => (td.innerText||'').trim());
    return {kv: cb ? cb.value : null,
            title: tr.getAttribute('title') || '',
            cells: cells};
}).filter(r => r.kv && r.cells.length <= 12)"""


def scrape_hospital(hospital_code="52626", store=True, enrich=True,
                    enrich_limit=15, enrich_offset=0):
    """Scrape CLOSED preventive-maintenance work orders for one hospital
    into the database. Logs in, then delegates to _scrape_one_hospital.
    """
    result = {"steps": [], "success": False, "last_step": "init",
              "hospital_code": hospital_code}
    rc_id = REPAIRCENTER_IDS.get(hospital_code)
    if not rc_id:
        result["error"] = f"No internal repaircenter id known for {hospital_code}"
        result["last_step"] = "resolve-repaircenter"
        return result
    result["repaircenter_id"] = rc_id

    with sync_playwright() as p:
        browser, context = _launch(p)
        try:
            active = _login(context, result)
            _scrape_one_hospital(active, hospital_code, rc_id, result,
                                 store=store, enrich=enrich,
                                 enrich_limit=enrich_limit,
                                 enrich_offset=enrich_offset)
            result["success"] = True
            result["last_step"] = "done"
        except Exception as e:
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
        finally:
            browser.close()
    return result


def scrape_all(store=True, enrich=True, enrich_limit=8, hospitals=None):
    """Scrape CLOSED PMs for EVERY hospital in the portfolio in ONE browser
    session (single login). Loops the Repair Center dropdown per hospital so
    the whole portfolio is covered by a single cron trigger.

    enrich_limit is kept small per-hospital so 10 hospitals fit inside
    Render's request/timeout window; successive cron runs fill in the rest.
    """
    codes = hospitals or ALL_HOSPITALS
    summary = {"steps": [], "success": False, "last_step": "init",
               "hospitals": {}, "order": codes}
    with sync_playwright() as p:
        browser, context = _launch(p)
        try:
            active = _login(context, summary)
            for code in codes:
                rc_id = REPAIRCENTER_IDS.get(code)
                sub = {"steps": [], "success": False, "last_step": "init",
                       "hospital_code": code, "repaircenter_id": rc_id}
                if not rc_id:
                    sub["error"] = f"No repaircenter id for {code}"
                    summary["hospitals"][code] = sub
                    continue
                try:
                    _scrape_one_hospital(active, code, rc_id, sub,
                                         store=store, enrich=enrich,
                                         enrich_limit=enrich_limit,
                                         enrich_offset=0)
                    sub["success"] = True
                    sub["last_step"] = "done"
                except Exception as e:
                    sub["error"] = str(e)
                    sub["error_type"] = type(e).__name__
                summary["hospitals"][code] = {
                    "success": sub.get("success"),
                    "raw_row_count": sub.get("raw_row_count"),
                    "parsed_count": sub.get("parsed_count"),
                    "enriched": sub.get("enriched"),
                    "db": sub.get("db"),
                    "error": sub.get("error"),
                    "last_step": sub.get("last_step"),
                }
            summary["success"] = True
            summary["last_step"] = "done"
        except Exception as e:
            summary["error"] = str(e)
            summary["error_type"] = type(e).__name__
        finally:
            browser.close()
    return summary


def enrich_backlog(limit=40, hospital=None, prefer_direct=True):
    """Standalone, RESUMABLE enrichment pass. Pulls unenriched WOs from the
    DB (newest close/target first so 'today/this week' lights up first),
    logs in once, opens each hospital's list, and enriches the WOs that
    belong to the currently-loaded site. Tries fast direct-fetch, falls
    back to double-click. Bounded by `limit` so it fits the HTTP window.
    """
    summary = {"steps": [], "success": False, "last_step": "init",
               "requested": limit, "enriched": 0, "via_direct": 0,
               "via_click": 0, "by_site": {}}
    targets = db.unenriched_kvs(limit=limit, hospital_code=hospital)
    summary["found"] = len(targets)
    if not targets:
        summary["success"] = True
        summary["last_step"] = "nothing-to-do"
        return summary
    # Group by hospital so we set each Repair Center once.
    by_site = {}
    for t in targets:
        by_site.setdefault(t["hospital_code"], []).append(t)

    with sync_playwright() as p:
        browser, context = _launch(p)
        try:
            active = _login(context, summary)
            for code, items in by_site.items():
                rc_id = REPAIRCENTER_IDS.get(code)
                if not rc_id:
                    continue
                site_res = {"steps": [], "last_step": "init",
                            "hospital_code": code}
                try:
                    # Load this site's closed list (reuses the scrape setup).
                    _load_closed_list(active, code, rc_id, site_res)
                    list_fr = _frame_for(active, "mc_list.asp")
                    done = 0
                    for it in items:
                        kv = it["kv"] or it["wo_number"]
                        det = {}
                        if prefer_direct:
                            det = _fetch_wo_detail_direct(active, list_fr, it["kv"])
                            if det:
                                summary["via_direct"] += 1
                        if not det:
                            try:
                                det = _fetch_wo_detail_by_click(active, list_fr, it["kv"])
                                if det.get("closed_by") or det.get("close_date"):
                                    summary["via_click"] += 1
                            except Exception as e:
                                det = {"error": str(e)}
                        if det.get("closed_by") or det.get("close_date"):
                            db.upsert_pms([{
                                "wo_number": it["wo_number"],
                                "hospital_code": code,
                                "hospital_name": HOSPITAL_NAMES.get(code),
                                "closed_by": det.get("closed_by"),
                                "close_date": det.get("close_date"),
                                "system": det.get("pm_name"),
                                "procedure": det.get("procedure"),
                                "asset_name": det.get("asset_name"),
                                "asset_model": det.get("asset_model"),
                                "asset_serial": det.get("asset_serial"),
                                "wo_type": "PM",
                                "raw": {"detail": det, "kv": it["kv"]},
                            }])
                            summary["enriched"] += 1
                            done += 1
                    summary["by_site"][code] = done
                except Exception as e:
                    summary["by_site"][code] = f"err: {e}"
            summary["success"] = True
            summary["last_step"] = "done"
        except Exception as e:
            summary["error"] = str(e)
            summary["error_type"] = type(e).__name__
        finally:
            browser.close()
    return summary


def _load_closed_list(active, hospital_code, rc_id, result):
    """Set Repair Center + All-Closed view + show-all, leaving the list frame
    populated. Shared by scrape + enrich. Raises on hard failure."""
    list_fr = _frame_for(active, "mc_list.asp")
    nav_fr = _frame_for(active, "toctop.asp")
    if not list_fr or not nav_fr:
        raise RuntimeError("list/nav frame not found")
    nav_fr.evaluate(
        """(rc) => {
            const s = document.querySelector("select[name='wo_repaircenter']");
            if (s) { s.value = rc; s.dispatchEvent(new Event('change',{bubbles:true}));
                if (typeof checksearch==='function'){try{checksearch(s);}catch(e){}} }
        }""", str(rc_id))
    nav_fr.wait_for_timeout(1500)
    nav_fr.evaluate(
        """() => {
            const s = document.querySelector("select[name='wo_status']");
            if (s) { s.value='CLOSEDALL'; s.dispatchEvent(new Event('change',{bubbles:true}));
                if (typeof checksearch==='function'){try{checksearch(s);}catch(e){}} }
        }""")
    active.wait_for_timeout(5000)
    list_fr = _frame_for(active, "mc_list.asp") or list_fr
    try:
        list_fr.wait_for_load_state("networkidle", timeout=40000)
    except Exception:
        pass
    list_fr.wait_for_timeout(2500)
    show_url = _build_show_all_url(list_fr.url or "")
    if show_url:
        try:
            list_fr.goto(show_url, timeout=60000)
            list_fr.wait_for_timeout(2500)
        except Exception:
            pass
    result["last_step"] = "list-loaded"


def _scrape_one_hospital(active, hospital_code, rc_id, result, store=True,
                         enrich=True, enrich_limit=15, enrich_offset=0):
    """Scrape one hospital using an already-logged-in Work Center page.
    Sets the Repair Center + Closed view, reads rows, enriches, stores.
    Mutates `result` in place. Raises on hard failure.
    """
    if True:  # noqa: retained block indent for a large ported body
        if True:
            result["last_step"] = "find-frames"
            list_fr = _frame_for(active, "mc_list.asp")
            nav_fr = _frame_for(active, "toctop.asp")
            if not list_fr:
                raise RuntimeError("work-order list frame (mc_list.asp) not found")
            if not nav_fr:
                raise RuntimeError("nav frame (toctop.asp) not found")

            # Drive the UI like a user: set Repair Center + Closed view in the
            # nav frame, which makes MC populate the list grid. Direct-URL
            # navigation returns an empty frame (grid is JS/POST-driven).
            result["last_step"] = "set-repaircenter"
            # The select is a hidden styled dropdown, so Playwright's
            # visibility-gated select_option times out. Set the value via JS
            # and fire the onchange MC listens for. Non-fatal.
            try:
                nav_fr.evaluate(
                    """(rc) => {
                        const s = document.querySelector("select[name='wo_repaircenter']");
                        if (s) { s.value = rc;
                            s.dispatchEvent(new Event('change', {bubbles:true}));
                            if (typeof checksearch === 'function') { try { checksearch(s); } catch(e){} }
                        }
                    }""",
                    str(rc_id),
                )
                nav_fr.wait_for_timeout(2000)
                result["steps"].append(f"Set Repair Center to {rc_id}")
                # Read the value BACK so a silent no-op can never pass as done.
                try:
                    rc_now = nav_fr.evaluate(
                        """() => { const s = document.querySelector(
                               "select[name='wo_repaircenter']");
                               return s ? s.value : null; }""")
                    result["repaircenter_after_set"] = rc_now
                    if str(rc_now) != str(rc_id):
                        raise RuntimeError(
                            f"repair center did not switch (wanted {rc_id}, "
                            f"got {rc_now})")
                except RuntimeError:
                    raise
                except Exception:
                    pass
            except RuntimeError:
                raise
            except Exception as e:
                result["set_rc_error"] = str(e)

            # Capture the live hospital name straight from the dropdown so the
            # stored name is authoritative (not just our hardcoded fallback).
            try:
                live_name = nav_fr.evaluate(
                    """(rc) => {
                        const s = document.querySelector("select[name='wo_repaircenter']");
                        if (!s) return null;
                        const opt = Array.from(s.options).find(o => o.value == rc);
                        return opt ? (opt.text||'').trim() : null;
                    }""",
                    str(rc_id),
                )
                if live_name:
                    result["live_hospital_name"] = live_name
            except Exception:
                pass

            result["last_step"] = "set-closed-view"
            # wo_status 'CLOSEDALL' = All Closed. Selecting it triggers onchange
            # which reloads the list frame with closed WOs.
            try:
                nav_fr.evaluate(
                    """() => {
                        const s = document.querySelector("select[name='wo_status']");
                        if (s) { s.value = 'CLOSEDALL';
                            s.dispatchEvent(new Event('change', {bubbles:true}));
                            if (typeof checksearch === 'function') { try { checksearch(s); } catch(e){} }
                        }
                    }"""
                )
                result["steps"].append("Set view to All Closed")
            except Exception as e:
                result["set_status_error"] = str(e)

            # PM-ONLY at the source: find + set the work-order-type select.
            result["last_step"] = "set-pm-type"
            if _try_set_pm_type(nav_fr, result):
                result["steps"].append(
                    f"Set type filter to PM via {result.get('pm_type_select')}")
                active.wait_for_timeout(4000)

            result["last_step"] = "wait-list-reload"
            active.wait_for_timeout(6000)
            # Re-resolve the list frame (it may have reloaded to a new URL).
            list_fr = _frame_for(active, "mc_list.asp") or list_fr
            try:
                list_fr.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                pass
            list_fr.wait_for_timeout(4000)
            result["list_url"] = list_fr.url

            # DIAGNOSTIC: find where the WO numbers actually live in the DOM.
            result["last_step"] = "probe-dom"
            try:
                result["dom_probe"] = list_fr.evaluate(
                    r"""() => {
                        const out = {};
                        // Any element whose text starts like a WO number.
                        const woRe = /^\s*\d{4,6}-\d+/;
                        const walker = document.createElement('div');
                        const hits = [];
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.children.length === 0) {
                                const t = (el.innerText||'').trim();
                                if (woRe.test(t)) {
                                    hits.push({tag: el.tagName,
                                              cls: el.className||'',
                                              text: t.slice(0,40),
                                              parentTag: el.parentElement ? el.parentElement.tagName : '',
                                              parentCls: el.parentElement ? (el.parentElement.className||'') : ''});
                                }
                            }
                            if (hits.length >= 6) break;
                        }
                        out.wo_hits = hits;
                        out.tables = document.querySelectorAll('table').length;
                        out.grid_divs = document.querySelectorAll('[class*=grid],[class*=Grid],[class*=list],[class*=List],[class*=row],[class*=Row]').length;
                        out.body_sample = (document.body.innerText||'').slice(0,800);
                        // Class names of the biggest containers, to spot the grid.
                        const big = [];
                        for (const el of document.querySelectorAll('div,table,tbody')) {
                            const t = (el.innerText||'').trim();
                            if (t.length > 100) big.push({tag: el.tagName, cls: (el.className||'').slice(0,60), len: t.length});
                        }
                        out.big_containers = big.sort((a,b)=>b.len-a.len).slice(0,8);
                        out.html_len = document.body.innerHTML.length;
                        return out;
                    }"""
                )
            except Exception as e:
                result["dom_probe_error"] = str(e)

            # PAGING: MC's grid shows only the first page (~48 rows) by
            # default, so "Total" was really "first page count". Capture the
            # paging controls + record count, then force the grid to show all
            # rows before reading.
            result["last_step"] = "probe-paging"
            try:
                result["paging"] = list_fr.evaluate(
                    r"""() => {
                        const out = {selects:[], inputs:[], counts:[]};
                        // page-size / paging <select>s
                        for (const s of document.querySelectorAll('select')) {
                            out.selects.push({name: s.name||s.id||'',
                                value: s.value,
                                options: Array.from(s.options).map(o=>o.value).slice(0,20)});
                        }
                        // paging inputs (page number, page size)
                        for (const i of document.querySelectorAll("input[type='text'],input[type='hidden']")) {
                            const nm=(i.name||i.id||'');
                            if (/page|size|rows|rec/i.test(nm)) out.inputs.push({name:nm, value:i.value});
                        }
                        // any 'x of y' / 'records' text
                        const body=(document.body.innerText||'');
                        const m=body.match(/(\d+)\s*(?:-|to)\s*(\d+)\s*of\s*(\d+)/i);
                        if (m) out.range={from:m[1],to:m[2],total:m[3]};
                        const rm=body.match(/(\d+)\s+records?/i);
                        if (rm) out.records=rm[1];
                        // global functions MC exposes for paging
                        out.fns = ['gotopage','setpagesize','showall','doPaging','changePageSize']
                            .filter(f => typeof window[f] === 'function');
                        return out;
                    }"""
                )
            except Exception as e:
                result["paging_error"] = str(e)

            # Force "show all rows": MC's grid renders one page (~48) by
            # default. Its own list URL already carries the true pagesize
            # (e.g. 696) plus a 'sallpages' flag. We navigate the list frame
            # to that same URL with page=1, a large pagesize, and sallpages=1
            # so every closed PM renders and gets read in one pass.
            result["last_step"] = "force-show-all"
            try:
                cur_url = list_fr.url or ""
                show_url = _build_show_all_url(cur_url)
                result["show_all_url"] = show_url
                if show_url:
                    list_fr.goto(show_url, timeout=60000)
                    try:
                        list_fr.wait_for_load_state("networkidle", timeout=45000)
                    except Exception:
                        pass
                    list_fr.wait_for_timeout(3000)
                    # Re-resolve in case MC swapped the frame.
                    list_fr = _frame_for(active, "mc_list.asp") or list_fr
            except Exception as e:
                result["show_all_error"] = str(e)

            # Extract each row's WO number + internal key (kv) from the
            # checkbox value, plus the visible cells. The kv lets us fetch
            # the WO detail page for close date + completed-by enrichment.
            # MC's own record count = the number we must match.
            result["last_step"] = "read-grid-total"
            mc_total = _grid_total(list_fr)
            result["mc_reported_total"] = mc_total

            result["last_step"] = "read-rows"
            rows = list_fr.eval_on_selector_all(
                "tr:has(td.browsedatacol)", _ROW_READ_JS)

            # MC render-caps the grid (~355 rows per load), so ALWAYS page
            # through until a page adds nothing new. MC's own total, when
            # readable, is a cross-check on the result — never the trigger.
            result["last_step"] = "paginate"
            seen_kv = {r["kv"] for r in rows}
            base_url = list_fr.url or ""
            pages_read = 1
            for pg in range(2, 61):
                if mc_total and len(rows) >= mc_total:
                    break
                purl = _build_page_url(base_url, pg)
                if not purl:
                    break
                try:
                    list_fr.goto(purl, timeout=60000)
                    list_fr.wait_for_timeout(1800)
                    list_fr = _frame_for(active, "mc_list.asp") or list_fr
                    more = list_fr.eval_on_selector_all(
                        "tr:has(td.browsedatacol)", _ROW_READ_JS)
                except Exception as e:
                    result["paginate_error"] = f"page {pg}: {e}"
                    break
                added = 0
                for r in more:
                    if r["kv"] not in seen_kv:
                        seen_kv.add(r["kv"])
                        rows.append(r)
                        added += 1
                pages_read = pg
                if added == 0:
                    break
            result["pages_read"] = pages_read
            result["raw_row_count"] = len(rows)
            if mc_total is not None:
                result["matches_mc_total"] = (len(rows) == mc_total)
            # Surface MC's date window (e.g. LN6M = last 6 months) so the
            # dashboard's "total" is always understood in its true scope.
            wm = re.search(r"withindate=([A-Za-z0-9]+)", base_url)
            if wm:
                result["mc_date_window"] = wm.group(1)

            result["last_step"] = "parse-rows"
            hosp_name = (result.get("live_hospital_name")
                         or HOSPITAL_NAMES.get(hospital_code))
            parsed = _parse_kv_rows(rows, hospital_code, hospital_name=hosp_name)
            # Guard: WO numbers are prefixed with their hospital code. Any row
            # whose prefix disagrees with the site we THINK we're scraping is
            # contamination from a failed switch — drop it and say so loudly.
            kept = [p for p in parsed
                    if p["wo_number"].split("-")[0] == str(hospital_code)]
            result["prefix_mismatch_dropped"] = len(parsed) - len(kept)
            parsed = kept
            result["parsed_count"] = len(parsed)

            # Enrichment: fetch WO detail for close date + completed-by.
            # Bounded per run (enrich_limit) so Render free tier never times
            # out; the 15-min cron fills in the rest over successive runs.
            if enrich and parsed:
                result["last_step"] = "enrich-details"
                enriched = 0
                _slice = parsed[enrich_offset:enrich_offset + enrich_limit]
                for rec in _slice:
                    kv = rec.get("_kv")
                    if not kv:
                        continue
                    try:
                        det = _fetch_wo_detail_by_click(active, list_fr, kv)
                        if det.get("closed_by"):
                            rec["closed_by"] = det["closed_by"]
                        if det.get("close_date"):
                            rec["close_date"] = det["close_date"]
                        if det.get("asset_name") and not rec.get("asset_name"):
                            rec["asset_name"] = det["asset_name"]
                        if det.get("asset_model"):
                            rec["asset_model"] = det["asset_model"]
                        if det.get("asset_serial"):
                            rec["asset_serial"] = det["asset_serial"]
                        # system = PM name (Supply-Chilled H2O Coil, etc.)
                        if det.get("pm_name"):
                            rec["system"] = det["pm_name"]
                        if det.get("procedure"):
                            rec["procedure"] = det["procedure"]
                        rec["raw"]["detail"] = det
                        enriched += 1
                    except Exception as e:
                        rec["raw"]["detail_error"] = str(e)
                result["enriched"] = enriched

            # Sample the enriched slice so we can verify enrichment worked.
            if enrich and parsed:
                result["sample_parsed"] = parsed[enrich_offset:enrich_offset + 3]
            else:
                result["sample_parsed"] = parsed[:3]

            # Strip internal-only fields before storing.
            for rec in parsed:
                rec.pop("_kv", None)

            if store and parsed:
                result["last_step"] = "store-db"
                result["db"] = db.upsert_pms(parsed)

            return result


# WO number pattern: <hospitalcode>-<number>, e.g. 52626-012345
_WO_RE = re.compile(r"^\d{4,6}-\d+")


# Asset cells often embed the MC asset id like "Booster Pump 03 (52626-14510)".
_ASSET_ID_RE = re.compile(r"\(([0-9]{4,6}-[0-9]+)\)\s*$")


def _clean_cells(row):
    """Drop MC's empty spacer cells, collapse whitespace."""
    return [_norm(c) for c in row if _norm(c)]


def _parse_kv_rows(rows, hospital_code, hospital_name=None):
    """Map MC 'All Closed' rows (with kv + browsedatacol cells) to records.

    Each row: {kv, title, cells:[WO#, Reason, Target, Procedure, Dept,
    Asset/Location, Location]}. We keep the internal kv (_kv) for detail
    enrichment, then strip it before storing.
    """
    out = []
    seen = set()
    for row in rows:
        cells = [_norm(c) for c in (row.get("cells") or [])]
        kv = row.get("kv")
        # WO number is the first cell that matches the pattern.
        wo = None
        for c in cells:
            if _WO_RE.match(c):
                wo = c.split()[0]
                break
        if not wo or wo in seen:
            continue
        seen.add(wo)

        nonempty = [c for c in cells if c]
        after = nonempty[1:] if nonempty else []
        reason = after[0] if after else None
        target = None
        for c in after:
            d = _to_date(c)
            if d:
                target = d
                break
        asset_name = None
        asset_id = None
        for c in after:
            m = _ASSET_ID_RE.search(c)
            if m:
                asset_name = c
                asset_id = m.group(1)
                break
        location = after[-1] if after else None

        out.append({
            "_kv": kv,
            "wo_number": wo,
            "hospital_code": hospital_code,
            "hospital_name": hospital_name or HOSPITAL_NAMES.get(hospital_code),
            "closed_by": None,      # filled by detail enrichment
            "close_date": None,     # filled by detail enrichment (real close date)
            "close_ts": None,
            "asset_name": asset_name,
            "asset_model": None,
            "asset_serial": None,
            "wo_type": "PM",
            "raw": {
                "kv": kv,
                "cells": cells,
                "reason": reason,
                "target_date": target,
                "asset_id": asset_id,
                "location": location,
                "title": row.get("title") or None,
            },
        })
    return out


# WO detail lives at _workorder_UDF_POM.asp?kv=<key>&justdata=y
_DETAIL_PATH = APP_BASE + "/modules/workorder/_workorder_UDF_POM.asp"


def _fetch_wo_detail(active, kv):
    """Fetch one WO's detail page and extract close date + completed-by
    from the Assignments section, plus asset name and status.

    The Assignments block looks like:  "Lee, Augusta   8/31/2026  0 hr"
    which gives us the mechanic and the completion date.
    """
    return _fetch_wo_detail_by_click(active, None, kv)


def _fetch_wo_detail_direct(active, list_fr, kv):
    """FAST enrichment: fetch the WO detail HTML via an in-page fetch() from
    an authenticated frame (carries session cookies), instead of a slow
    double-click. If MC returns real content we parse it the same way.
    Returns {} on empty/blocked so caller can fall back to click.
    """
    fr = list_fr or _frame_for(active, "mc_list.asp")
    if fr is None:
        return {}
    base = _DETAIL_PATH
    # Try a few known param shapes MC uses for the detail body.
    urls = [
        f"{base}?kv={kv}&justdata=y",
        f"{base}?kv={kv}",
        f"{base}?mckeyvalues={kv}&justdata=y",
    ]
    for u in urls:
        try:
            text = fr.evaluate(
                """async (u) => {
                    try {
                        const r = await fetch(u, {credentials:'include'});
                        if (!r.ok) return '';
                        return await r.text();
                    } catch(e) { return ''; }
                }""",
                u,
            )
        except Exception:
            text = ""
        if text and len(text) > 400:
            # Strip tags to plain text for the existing parser.
            plain = re.sub(r"<[^>]+>", " ", text)
            plain = re.sub(r"&nbsp;", " ", plain)
            det = _parse_detail_text(_norm(plain))
            if det.get("closed_by") or det.get("close_date"):
                det["_via"] = "direct"
                return det
    return {}


def _detail_text_from_frames(active):
    """Read WO detail text from whichever frame MC rendered it in."""
    best = ""
    for fr in active.frames:
        u = fr.url or ""
        if "_workorder_UDF_POM.asp" in u and "mc_list" not in u:
            try:
                t = fr.inner_text("body")
                if len(t) > len(best):
                    best = t
            except Exception:
                pass
    return best


def _parse_detail_text(text):
    """Extract closed_by, close_date, asset, pm, procedure from detail text."""
    out = {"raw_len": len(text)}
    if not text:
        return out
    out["raw_head"] = text[:900]

    # Assignments block: "Lee, Augusta   8/31/2026   0 hr"
    m = re.search(r"Assignments\s*Action(.*?)(Indicators|Page 1|$)",
                  text, re.S | re.I)
    if m:
        block = m.group(1)
        name_m = re.search(r"([A-Z][A-Za-z.'\-]+\s*,\s*[A-Z][A-Za-z.'\-]+)", block)
        if name_m:
            out["closed_by"] = _norm(name_m.group(1).replace("\u00a0", " "))
        dm = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", block)
        if dm:
            out["close_date"] = _to_date(dm.group(1))

    # Status block Closed date fallback.
    sm = re.search(r"Closed\b[^\d]{0,20}(\d{1,2}/\d{1,2}/\d{2,4})", text, re.I)
    if sm and not out.get("close_date"):
        out["close_date"] = _to_date(sm.group(1))

    am = re.search(r"([^\n]*\(\d{4,6}-\d+\))", text)
    if am:
        out["asset_name"] = _norm(am.group(1))
    pm = re.search(r"PM:\s*([^\n]+)", text)
    if pm:
        out["pm_name"] = _norm(pm.group(1))
    pr = re.search(r"Procedure:\s*\n?\s*([^\n]+)", text)
    if pr:
        out["procedure"] = _norm(pr.group(1))
    # Asset model / serial. Labels vary ("Model", "Model #", "Model No"), so
    # match the label plus a short token value; skip if the "value" is just
    # another label word.
    mm = re.search(r"Model\s*(?:#|No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/\.]{1,29})",
                   text, re.I)
    if mm and mm.group(1).lower() not in ("serial", "number", "no"):
        out["asset_model"] = _norm(mm.group(1))
    sn = re.search(r"Serial\s*(?:#|No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/\.]{1,29})",
                   text, re.I)
    if sn and sn.group(1).lower() not in ("model", "number", "no"):
        out["asset_serial"] = _norm(sn.group(1))
    return out


def _fetch_wo_detail_by_click(active, list_fr, kv):
    """Open a WO's detail by double-clicking its list row (MC populates the
    detail frame with session context), then parse it. Direct-URL fetch
    returns an empty body, so we must drive the UI.
    """
    if list_fr is None:
        list_fr = _frame_for(active, "mc_list.asp")
    if list_fr is None:
        return {"error": "list frame gone"}
    row = list_fr.locator(
        f"tr:has(input[name='mckeyvalues'][value='{kv}'])"
    ).first
    row.dblclick(timeout=15000)
    active.wait_for_timeout(3500)
    text = _detail_text_from_frames(active)
    return _parse_detail_text(text)


def _to_date(s):
    """Parse common MC date formats to YYYY-MM-DD, else None."""
    if not s:
        return None
    s = _norm(s)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mo, d, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    return None
