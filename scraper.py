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

HOSPITAL_NAMES = {
    "52626": "Medstar Washington Hospital Center",
}


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


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def scrape_hospital(hospital_code="52626", store=True):
    """Step 2: scrape CLOSED preventive-maintenance work orders for one
    hospital into the database. Correctives are excluded at the source
    (wotype=PM). Deduplicates on wo_number. Fails loudly with the step.
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
            try:
                nav_fr.select_option("select[name='wo_repaircenter']", value=str(rc_id))
                nav_fr.wait_for_timeout(1500)
                result["steps"].append(f"Set Repair Center to {rc_id}")
            except Exception as e:
                result["set_rc_error"] = str(e)

            result["last_step"] = "set-closed-view"
            # wo_status 'CLOSEDALL' = All Closed. Selecting it triggers onchange
            # which reloads the list frame with closed WOs.
            try:
                nav_fr.select_option("select[name='wo_status']", value="CLOSEDALL")
                result["steps"].append("Set view to All Closed")
            except Exception as e:
                result["set_status_error"] = str(e)

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

            result["last_step"] = "read-headers"
            headers = list_fr.eval_on_selector_all(
                "table tr:first-child td, table th, .listheader td, .gridheader td",
                "els => els.map(e => (e.innerText||'').trim()).filter(Boolean).slice(0,40)",
            )
            result["headers"] = headers

            result["last_step"] = "read-rows"
            # Grab every table row's cell text. MC list rows carry the WO id
            # in the first data cell (e.g. 52626-01234).
            raw_rows = list_fr.eval_on_selector_all(
                "table tr",
                "els => els.map(tr => Array.from(tr.querySelectorAll('td'))"
                ".map(td => (td.innerText||'').trim())).filter(r => r.length)",
            )
            result["raw_row_count"] = len(raw_rows)
            result["sample_rows"] = raw_rows[:5]

            result["last_step"] = "parse-rows"
            parsed = _parse_rows(raw_rows, headers, hospital_code)
            result["parsed_count"] = len(parsed)
            result["sample_parsed"] = parsed[:5]

            if store and parsed:
                result["last_step"] = "store-db"
                result["db"] = db.upsert_pms(parsed)

            result["success"] = True
            result["last_step"] = "done"
        except Exception as e:
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
        finally:
            browser.close()
    return result


# WO number pattern: <hospitalcode>-<number>, e.g. 52626-012345
_WO_RE = re.compile(r"^\d{4,6}-\d+")


def _parse_rows(raw_rows, headers, hospital_code):
    """Map MC list rows to closed_pms records. Header-driven where
    possible, defensive everywhere: we always keep the WO number and
    the full raw row so nothing is lost even if a column shifts.
    """
    # Build a case-insensitive header index.
    hidx = {}
    for i, h in enumerate(headers or []):
        key = _norm(h).lower()
        if key and key not in hidx:
            hidx[key] = i

    def col(row, *names):
        for n in names:
            i = hidx.get(n)
            if i is not None and i < len(row):
                val = _norm(row[i])
                if val:
                    return val
        return None

    out = []
    for row in raw_rows:
        if not row:
            continue
        # Find the WO number cell anywhere in the row.
        wo = None
        for cell in row:
            c = _norm(cell)
            if _WO_RE.match(c):
                wo = c.split()[0]
                break
        if not wo:
            continue  # header/spacer/non-data row

        rec = {
            "wo_number": wo,
            "hospital_code": hospital_code,
            "hospital_name": HOSPITAL_NAMES.get(hospital_code),
            "closed_by": col(row, "closed by", "completed by", "assigned to", "labor"),
            "close_date": _to_date(col(row, "close date", "date closed",
                                        "completed", "completed date", "closed")),
            "close_ts": None,
            "asset_name": col(row, "asset", "asset name", "equipment"),
            "asset_model": col(row, "model", "model number"),
            "asset_serial": col(row, "serial", "serial number"),
            "wo_type": col(row, "type", "wo type") or "PM",
            "raw": {"cells": row, "headers": headers},
        }
        out.append(rec)
    return out


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
