import os
import re
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://app.maintenanceconnection.com/cav3/login"

# Base of the internal frameset app discovered during Step 1.
APP_BASE = "https://app.maintenanceconnection.com/mcv18/mapp_v2026.8"


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
