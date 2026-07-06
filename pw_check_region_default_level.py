"""Playwright 검증: 사이드바에서 지역별 클릭 시 기본 드릴레벨이 국가별(viewLevel=2)인지 확인."""
import sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = "http://127.0.0.1:5000"
USER = "jeffrey"
PASSW = "skin1004!"

failures = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(f"{URL}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSW)
    page.click("button[type=submit]")
    page.wait_for_url(f"{URL}/dashboard", timeout=10_000)
    page.wait_for_function("window.__rendered === true", timeout=40_000)

    page.click('.cat-tab[data-cat="region"]')
    page.wait_for_timeout(1000)

    vl = page.evaluate("state.viewLevel.region")
    print(f"[region] state.viewLevel.region = {vl}")
    if vl != 2:
        failures.append(f"기대값 2, 실제값 {vl}")

    active_label = page.locator("#crumbTrail .crumb-item.current").text_content()
    print(f"[region] 활성 breadcrumb: {active_label}")
    if not active_label or "국가" not in active_label:
        failures.append(f"활성 breadcrumb에 '국가'가 없음: {active_label}")

    browser.close()

if failures:
    print("\n[FAIL]")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\n[OK] 지역별 기본 드릴레벨 = 국가별 확인됨")
