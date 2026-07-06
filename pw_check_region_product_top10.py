"""Playwright 검증: 지역별/상품별 P&L 테이블의 '기타' 컬럼 존재 여부,
그리고 렌더링된 DOM 셀 값 기준으로 top10+기타=계 불변식과 top10 랭킹(그 기간 매출 내림차순)이
실제로 맞게 그려졌는지 검증한다. (원본 데이터로만 계산해 자기 자신과 비교하는 방식이 아니라
브라우저가 실제로 그린 셀 텍스트를 파싱해서 비교한다.)"""
import re
import sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = "http://127.0.0.1:5000"
USER = "jeffrey"
PASSW = "skin1004!"

failures = []


# CPL_SEC_DEFS 순서와 동일: 전체(all) / SK(SK) / 유통(UM) — 테이블은 이 순서로 렌더링됨
SECTIONS = [
    (0, 'all', '전체'),
    (1, 'SK', 'SK'),
    (2, 'UM', '유통'),
]


def parse_cell_value(text):
    """fmtMm()이 그린 셀의 렌더 텍스트에서 첫 줄(값 span)만 뽑아 정수로 변환.
    momCell()의 '▲0.7%' 같은 두 번째 줄은 무시한다."""
    first_line = (text or '').split('\n')[0].strip().replace(',', '')
    m = re.match(r'-?\d+', first_line)
    return int(m.group(0)) if m else None


def check_category(page, cat_id, cat_label):
    page.click(f'.cat-tab[data-cat="{cat_id}"]')
    # 탭 전환 시 /api/pl이 새로 로드되는 동안 state.cplData.byNode가 비어있을 수 있으므로,
    # 고정 대기 대신 실제로 데이터가 채워질 때까지 폴링한다 (탭 전환 직후의 레이스 컨디션 방지).
    page.wait_for_function(
        "() => state.cplData && state.cplData.byNode && Object.keys(state.cplData.byNode).length > 0",
        timeout=15_000,
    )
    page.wait_for_selector("#categoryPlSection table.pl-table", timeout=20_000)

    month_ths = page.locator("#categoryPlSection [data-cpl-month]")
    if month_ths.count() == 0:
        print(f"[{cat_label}] 기간 헤더 없음 — 데이터 부족으로 스킵")
        return

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

    # 렌더 직후 seed 로직에 의해 첫 번째 기간(월별 모드에서는 첫 달, months[0])만 열려있다고
    # 가정한다 — 이 스크립트는 각 카테고리 탭에 이 세션에서 처음 진입하므로 그 가정이 성립한다.
    first_month_idx = 0

    for table_idx, sec_key, sec_label in SECTIONS:
        tag = f"{cat_label}/{sec_label}"

        section_table = page.locator("#categoryPlSection table.pl-table").nth(table_idx)
        if section_table.count() == 0:
            failures.append(f"[{tag}] 섹션 테이블(index {table_idx})을 찾을 수 없음")
            continue

        header_row2 = section_table.locator("thead tr").nth(1).locator("th").all_text_contents()
        if "계" not in header_row2:
            failures.append(f"[{tag}] 헤더 2번째 행에 '계'가 없음: {header_row2}")
            continue
        # 첫 번째(열려있는) 기간의 컬럼들 = 첫 '계' 이전 항목들 (국가/상품명들, 마지막에 '기타' 있을 수 있음)
        first_gye_idx = header_row2.index("계")
        period1_cols = header_row2[:first_gye_idx]
        has_others_header = period1_cols and period1_cols[-1] == "기타"
        if not has_others_header:
            failures.append(f"[{tag}] 첫 기간 헤더에 '기타' 컬럼이 없음: {period1_cols}")
            continue
        rendered_top10 = period1_cols[:-1]  # '기타' 제외한 실제 top10 이름들 (렌더링된 순서 그대로)
        print(f"[{tag}] '기타' 헤더 확인됨, 렌더된 top{len(rendered_top10)}: {rendered_top10}")

        # 1) 랭킹 검증: 렌더된 top10 이름 집합/순서가, 그 기간(month idx 0) 매출 기준
        #    원본 데이터로 독립 계산한 내림차순 top10과 정확히 일치하는지
        def sales_at(name, idx, _sec_key=sec_key):
            node = byNode.get(name) or {}
            sec = node.get(_sec_key) or {}
            arr = sec.get('sales') or []
            return arr[idx] if idx < len(arr) else 0

        expected_top10 = sorted(names, key=lambda n: sales_at(n, first_month_idx), reverse=True)[:len(rendered_top10)]
        if rendered_top10 != expected_top10:
            failures.append(
                f"[{tag}] 렌더된 top10 랭킹이 기대값과 다름: rendered={rendered_top10} expected={expected_top10}"
            )
        else:
            print(f"[{tag}] top10 랭킹(그 기간 매출 내림차순) 일치 확인됨")

        # 2) 렌더된 DOM 셀 값으로 top10+기타 == 계 검증 (매출액 행, 첫 번째 열린 기간)
        sales_row = section_table.locator("tbody tr").first
        cell_texts = sales_row.locator("td").all_text_contents()
        # cell_texts[0] = 라벨(구분), [1] = 합계, [2:2+len(period1_cols)] = 이 기간의 top10+기타,
        # 그 다음이 이 기간의 '계' 셀
        period_cells = cell_texts[2:2 + len(period1_cols)]
        gye_cell = cell_texts[2 + len(period1_cols)] if len(cell_texts) > 2 + len(period1_cols) else None
        values = [parse_cell_value(t) for t in period_cells]
        gye_value = parse_cell_value(gye_cell)
        if any(v is None for v in values) or gye_value is None:
            failures.append(f"[{tag}] 매출액 행 셀 파싱 실패: period_cells={period_cells!r} gye_cell={gye_cell!r}")
            continue
        rendered_sum = sum(values)
        diff = abs(rendered_sum - gye_value)
        # fmtMm()은 셀마다 독립적으로 백만원 단위 반올림하므로, 반올림된 부분들의 합이
        # 반올림된 전체 합과 최대 ±(셀 수) 오차 이내로 어긋날 수 있다 (원본 미반올림 값은
        # curOther = pTot - sumTop 로 정확히 일치함이 코드상 보장됨 — 이건 표시 단위 오차일 뿐).
        tolerance = len(values)
        print(f"[{tag}] 렌더된 top10+기타 합={rendered_sum}, 렌더된 계={gye_value} (차이={diff}, 허용오차={tolerance})")
        if diff > tolerance:
            failures.append(
                f"[{tag}] 렌더된 top10+기타 합({rendered_sum})과 계({gye_value})의 차이({diff})가 "
                f"반올림 허용오차({tolerance})를 초과함"
            )


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
print("\n[OK] 렌더된 DOM 기준 top10 랭킹 및 top10+기타=계 불변식 확인됨")
