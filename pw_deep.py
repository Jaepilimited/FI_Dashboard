"""Deep diagnostic: check all 4 category tabs, breakdown, raw table."""
import sys, time, json
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL   = "http://127.0.0.1:5000"
USER  = "jeffrey"
PASSW = "skin1004!"

api_calls = []

def on_response(resp):
    if "/api/" in resp.url:
        api_calls.append({"url": resp.url.replace(URL, ""), "status": resp.status})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=150)
    page = browser.new_page()
    page.on("response", on_response)

    # Login
    page.goto(f"{URL}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSW)
    page.click("button[type=submit]")
    page.wait_for_url(f"{URL}/dashboard", timeout=10_000)

    # Wait for initial render
    page.wait_for_function("window.__rendered === true", timeout=40_000)
    time.sleep(1)

    # ── 1. 조직별 탭 (default) ──────────────────────────────────────
    print("=" * 60)
    print("[TAB 1] 조직별")
    print("=" * 60)

    def snapshot(label):
        s = page.evaluate("""() => {
            try {
                return {
                    kpi_sales: _real.kpi?.all?.sales_amount ?? null,
                    trend_months: (_real.trend?.all ?? []).map(r => r.Year_Month),
                    breakdown_count: (_real.breakdown ?? []).length,
                    breakdown_sample: (_real.breakdown ?? []).slice(0,2).map(r => ({
                        name: r.name ?? '(no name field)',
                        raw_keys: Object.keys(r).slice(0,5),
                        sales: r.sales_amount ?? null
                    })),
                    raw_count: document.querySelectorAll('#rawBody tr').length,
                };
            } catch(e) { return {error: String(e)}; }
        }""")
        print(f"\n  [{label}]")
        print(f"    kpi sales      : {s.get('kpi_sales')}")
        print(f"    trend months   : {s.get('trend_months')}")
        print(f"    breakdown count: {s.get('breakdown_count')}")
        print(f"    breakdown[0:2] : {s.get('breakdown_sample')}")
        print(f"    raw table rows : {s.get('raw_count')}")

    snapshot("조직별 초기")

    # Take full-page screenshot of 조직별
    page.screenshot(path="pw_org.png", full_page=True)
    print("  -> pw_org.png 저장")

    # ── 2. 지역별 탭 ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[TAB 2] 지역별")
    print("=" * 60)
    api_calls.clear()
    page.locator(".cat-tab").nth(1).click()
    time.sleep(0.5)
    try:
        page.wait_for_function("window.__rendered === true", timeout=15_000)
    except:
        pass
    time.sleep(2)
    snapshot("지역별 로드 후")
    page.screenshot(path="pw_geo.png", full_page=True)
    print("  -> pw_geo.png 저장")
    print("  API calls:", [c['url'][:80] for c in api_calls])

    # ── 3. 상품별 탭 ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[TAB 3] 상품별")
    print("=" * 60)
    api_calls.clear()
    page.locator(".cat-tab").nth(2).click()
    time.sleep(0.5)
    try:
        page.wait_for_function("window.__rendered === true", timeout=15_000)
    except:
        pass
    time.sleep(2)
    snapshot("상품별 로드 후")
    page.screenshot(path="pw_product.png", full_page=True)
    print("  -> pw_product.png 저장")
    print("  API calls:", [c['url'][:80] for c in api_calls])

    # ── 4. 판매유형 탭 ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[TAB 4] 판매유형")
    print("=" * 60)
    api_calls.clear()
    page.locator(".cat-tab").nth(3).click()
    time.sleep(0.5)
    try:
        page.wait_for_function("window.__rendered === true", timeout=15_000)
    except:
        pass
    time.sleep(2)
    snapshot("판매유형 로드 후")
    page.screenshot(path="pw_salestype.png", full_page=True)
    print("  -> pw_salestype.png 저장")
    print("  API calls:", [c['url'][:80] for c in api_calls])

    # ── 5. 원본 데이터 테이블 확인 ──────────────────────────────────
    print("\n" + "=" * 60)
    print("[RAW TABLE] 원본 데이터 탭")
    print("=" * 60)
    api_calls.clear()
    # Click on raw data tab if it exists
    raw_tab = page.locator("[data-tab='raw'], #rawTab, .raw-tab").first
    if raw_tab.count() > 0:
        raw_tab.click()
        time.sleep(2)
    else:
        # Try scrolling down to find raw table
        page.keyboard.press("End")
        time.sleep(1)
    raw_rows = page.locator("#rawBody tr").count()
    print(f"  Raw table rows visible: {raw_rows}")
    print("  API calls:", [c['url'][:80] for c in api_calls])
    page.screenshot(path="pw_raw.png", full_page=True)
    print("  -> pw_raw.png 저장")

    browser.close()

print("\n=== 진단 완료 ===")
