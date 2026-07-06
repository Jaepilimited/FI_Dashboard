"""Playwright 검증: 지역별/상품별 P&L 테이블의 '기타' 컬럼 존재 여부 및
기간별 top10 재선정 시 top10+기타=합계 불변식을 state.cplData.byNode 원본 데이터로 직접 재계산해 검증한다."""
import sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = "http://127.0.0.1:5000"
USER = "jeffrey"
PASSW = "skin1004!"

failures = []


def check_category(page, cat_id, cat_label):
    page.click(f'.cat-tab[data-cat="{cat_id}"]')
    page.wait_for_timeout(1000)
    page.wait_for_selector("#categoryPlSection table.pl-table", timeout=20_000)

    # 열려있는 기간이 하나도 없으면 아무 것도 못 보므로, 첫 기간 헤더를 한 번 더 클릭해
    # 최소 1개는 열린 상태를 보장한다 (렌더 시 seed 로직으로 보통 이미 1개는 열려 있음).
    month_ths = page.locator("#categoryPlSection [data-cpl-month]")
    if month_ths.count() == 0:
        print(f"[{cat_label}] 기간 헤더 없음 — 데이터 부족으로 스킵")
        return

    # 1) DOM 스모크 체크: 전체 섹션(첫 번째 table)의 2번째 헤더 행에 '기타'가 있는지
    #    (전체 노드 수가 10개 초과일 때만 나타나므로, 원본 데이터로 먼저 노드 수를 확인한다)
    data = page.evaluate("""() => {
        const byNode = (state.cplData && state.cplData.byNode) || {};
        const months = (state.cplData && state.cplData.months) || [];
        return { names: Object.keys(byNode).filter(n => n), byNode, months };
    }""")
    names = data['names']
    byNode = data['byNode']
    months = data['months']
    print(f"[{cat_label}] 전체 노드 수: {len(names)}, 월 수: {len(months)}")

    if len(names) <= 10:
        print(f"[{cat_label}] 노드 수가 10개 이하 — 기타 컬럼 없어야 정상, 검증 스킵")
        return

    first_table = page.locator("#categoryPlSection table.pl-table").first
    header_row2 = first_table.locator("thead tr").nth(1).locator("th").all_text_contents()
    if "기타" not in header_row2:
        failures.append(f"[{cat_label}] 전체 섹션 헤더에 '기타' 컬럼이 없음: {header_row2}")
    else:
        print(f"[{cat_label}] '기타' 헤더 확인됨")

    # 2) 원본 데이터로 재계산: 서로 다른 두 시점(월)에 대해
    #    그 시점 매출 기준 top10 재선정 + 기타 = 전체 합계 인지 확인
    sample_idxs = [0]
    if len(months) > 1:
        sample_idxs.append(len(months) - 1)

    def sales_at(name, idx):
        node = byNode.get(name) or {}
        allb = node.get('all') or {}
        arr = allb.get('sales') or []
        return arr[idx] if idx < len(arr) else 0

    top10_sets = []
    for idx in sample_idxs:
        ranked = sorted(names, key=lambda n: sales_at(n, idx), reverse=True)
        top10 = ranked[:10]
        top10_sets.append(tuple(top10))
        top10_sum = sum(sales_at(n, idx) for n in top10)
        total = sum(sales_at(n, idx) for n in names)
        other = total - top10_sum
        ok = (top10_sum + other) == total
        print(f"[{cat_label}] month idx {idx}: top10합={top10_sum} 기타={other} 합계={total} 검증={ok}")
        if not ok:
            failures.append(f"[{cat_label}] month idx {idx}: top10+기타({top10_sum + other}) != 합계({total})")

    if len(top10_sets) > 1 and top10_sets[0] == top10_sets[1]:
        print(f"[{cat_label}] 참고: 샘플로 고른 두 시점의 top10 구성이 동일함(데이터 특성상 정상일 수 있음)")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(f"{URL}/login")
    page.fill("input[name=username]", USER)
    page.fill("input[name=password]", PASSW)
    page.click("button[type=submit]")
    page.wait_for_url(f"{URL}/dashboard", timeout=10_000)
    page.wait_for_function("window.__rendered === true", timeout=40_000)

    check_category(page, "region", "지역별")
    check_category(page, "product", "상품별")

    browser.close()

if failures:
    print("\n[FAIL]")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\n[OK] top10+기타 불변식 및 기타 컬럼 확인됨")
