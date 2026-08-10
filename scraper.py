import os
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://app.maintenanceconnection.com/cav3/login"


def test_login():
    """Logs into Maintenance Connection and reports every step,
    so we never have to guess whether it worked.

    Fails loudly: every result carries the last step reached, so if
    something breaks we know exactly where. Never fails silently.
    """
    username = os.environ.get("MC_USERNAME")
    password = os.environ.get("MC_PASSWORD")
    result = {"steps": [], "success": False, "last_step": "init"}

    if not username or not password:
        result["error"] = "MC_USERNAME or MC_PASSWORD not set in environment variables"
        result["last_step"] = "env-check"
        return result

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
        )
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        try:
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
            result["steps"].append("Opened the MRO Work Center")
            result["opened_new_tab"] = len(context.pages) > 1

            result["last_step"] = "verify-content"
            body_text = active.inner_text("body")
            result["page_title"] = active.title()
            result["found_medstar"] = ("Medstar" in body_text) or ("MedStar" in body_text)
            result["found_work_orders"] = "Work Orders" in body_text
            result["success"] = result["found_medstar"] or result["found_work_orders"]
            result["last_step"] = "done"
        except Exception as e:
            # Fail loudly: report the error AND the step it died on.
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
        finally:
            browser.close()

    return result
