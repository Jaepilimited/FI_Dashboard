"""Playwright diagnostic: login -> check API responses and console errors."""
import sys, time
from playwright.sync_api import sync_playwright

# Force UTF-8 output to avoid cp949 encoding errors
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL   = "http://127.0.0.1:5000"
USER  = "jeffrey"
PASSW = "skin1004!"

api_log = []        # list of {url, status}
console_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=200)
    page = browser.new_page()

    # Collect console errors - also grab location URL for "Failed to load resource" errors
    def on_console(msg):
        if msg.type in ("error", "warning"):
            loc = msg.location
            loc_str = f" @ {loc['url']}" if loc and loc.get('url') else ""
            console_errors.append(f"[{msg.type}] {msg.text}{loc_str}")
    page.on("console", on_console)

    # Collect only url + status in the response handler (NO body read here)
    def on_response(resp):
        if resp.status >= 400:
            api_log.append({"url": resp.url, "status": resp.status})
        elif "/api/" in resp.url:
            api_log.append({"url": resp.url.replace(URL, ""), "status": resp.status})
    page.on("response", on_response)

    # Login
    page.goto(f"{URL}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSW)
    page.click("button[type=submit]")
    page.wait_for_url(f"{URL}/dashboard", timeout=10_000)

    # Wait for dashboard to render (max 40s)
    print("Dashboard loading...")
    try:
        page.wait_for_function("window.__rendered === true", timeout=40_000)
        print("[OK] Render complete")
    except Exception as e:
        print(f"[WARN] Render timeout: {e}")

    time.sleep(3)

    # KPI card text check
    kpi_texts = page.locator(".kpi-value").all_text_contents()
    print(f"\n[KPI values] {kpi_texts}")

    # Re-fetch API response bodies now (page is idle, responses are fully received)
    print("\n[API responses]")
    for entry in api_log:
        print(f"  {entry['status']} {entry['url']}")

    # Use page.evaluate to check what _real contains
    real_snapshot = page.evaluate("""() => {
        try {
            return {
                kpi: typeof _real !== 'undefined' ? JSON.stringify(_real.kpi).slice(0,400) : 'UNDEF',
                trend_len: typeof _real !== 'undefined' ? (_real.trend?.all?.length ?? 'null') : 'UNDEF',
                breakdown_len: typeof _real !== 'undefined' ? (_real.breakdown?.length ?? 'null') : 'UNDEF',
            };
        } catch(e) { return {error: String(e)}; }
    }""")
    print(f"\n[_real snapshot]")
    for k, v in real_snapshot.items():
        print(f"  {k}: {v}")

    # Check window.__rendered and any error state
    rendered = page.evaluate("() => window.__rendered")
    print(f"\n[window.__rendered] = {rendered}")

    # Console errors
    if console_errors:
        print("\n[Console errors/warnings]")
        for e in console_errors:
            print(f"  {e}")
    else:
        print("\n[Console errors] none")

    # Screenshot
    page.screenshot(path="pw_screenshot.png", full_page=False)
    print("\nScreenshot saved: pw_screenshot.png")

    browser.close()
