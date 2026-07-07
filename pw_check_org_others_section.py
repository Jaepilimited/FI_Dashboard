"""Playwright 검증: 조직별 P&L Others 섹션 렌더링 + BQ에서 미리 확인한 숫자와 대조.
(BQ 직접 조회로 이미 확인됨: Brand='SK' 매출 322,655백만 / 'UM' 85,886백만 / 'Others' -286백만,
 합계 408,255백만 = KPI 카드 값과 일치)"""
import re
import sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = "http://127.0.0.1:5000"
USER = "jeffrey"
PASSW = "skin1004!"


def parse_val(text):
    first_line = (text or '').split('\n')[0].strip().replace(',', '')
    m = re.match(r'-?\d+', first_line)
    return int(m.group(0)) if m else None


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(f"{URL}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSW)
    page.click("button[type=submit]")
    page.wait_for_url(f"{URL}/dashboard", timeout=10_000)
    page.wait_for_function("window.__rendered === true", timeout=40_000)

    page.click('.cat-tab[data-cat="org"]')
    page.wait_for_selector("#categoryPlSection table.pl-table", timeout=20_000)

    titles = page.locator("#categoryPlSection .pl-section-title span").all_text_contents()
    print("초기 섹션 제목들:", titles)
    assert titles == ['전체', 'SK 브랜드', '유통본부', 'Others'], f"섹션 순서/구성 예상과 다름: {titles}"

    # 전체 테이블(첫 번째)의 매출액 '합계' 값
    all_table = page.locator("#categoryPlSection table.pl-table").first
    all_sales = parse_val(all_table.locator("tbody tr").first.locator("td").nth(1).inner_text())
    print(f"전체 매출액 합계: {all_sales}")
    assert all_sales == 408255, f"전체 매출액 합계가 예상(408255)과 다름: {all_sales}"

    # Others 섹션 펼치기 → 두 번째로 나타나는 table.pl-table이 Others 요약 테이블
    # (전체 테이블 다음, SK/유통은 접혀있어 테이블이 없으므로 두 번째 = Others)
    page.click('[data-org-brand="Others"]')
    page.wait_for_timeout(500)

    titles2 = page.locator("#categoryPlSection .pl-section-title span").all_text_contents()
    print("Others 펼친 후 섹션 제목들:", titles2)
    expected_depts = {'회계/세무', 'FI', '전사', 'LOG', 'SCM', 'Sales Operation', '운영전략1_운영전략'}
    shown_depts = {t.replace('▸ ', '') for t in titles2 if t.startswith('▸ ')}
    assert shown_depts == expected_depts, f"Others 하위 부서 목록이 다름: {shown_depts} vs {expected_depts}"

    others_table = page.locator("#categoryPlSection table.pl-table").nth(1)
    others_sales = parse_val(others_table.locator("tbody tr").first.locator("td").nth(1).inner_text())
    print(f"Others 매출액 합계: {others_sales}")
    assert others_sales == -286, f"Others 매출액 합계가 BQ에서 확인한 값(-286)과 다름: {others_sales}"

    browser.close()

print("\n[OK] Others 섹션 렌더링/부서목록/매출액 전부 BQ 실데이터와 일치 확인됨")
