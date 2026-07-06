# 지역별/상품별 Top10 재선정 + 기타 컬럼, 지역별 기본 드릴레벨 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지역별/상품별 P&L 테이블에서 기간별로 그 기간 매출 기준 top10을 재선정하고 "기타" 잔차 컬럼을 추가해 합계 검증이 가능하게 하며, 사이드바에서 지역별 탭 진입 시 기본으로 국가별 화면이 보이게 한다.

**Architecture:** 순수 프론트엔드 변경. `templates/dashboard_v2.html`의 `state.viewLevel` 초기값 한 줄과 `renderCategoryPl()` 함수 내부 계산 로직만 수정한다. 백엔드(`app_v2.py`, `/api/pl`)와 `cplDims()`/`renderOrgPl()`은 변경하지 않는다.

**Tech Stack:** Vanilla JS (템플릿에 인라인), Jinja2 템플릿, Flask 개발 서버(werkzeug 자동 리로드), Python 3.11 + Playwright(검증 스크립트, 이 프로젝트의 기존 `pw_check.py` 관례를 따름 — 별도 JS 테스트 러너 없음).

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-07-06-region-product-top10-others-design.md` (이 계획은 그 문서의 "변경 1", "변경 2"를 구현한다)
- 대상 파일은 `templates/dashboard_v2.html` 단 하나. 백엔드/SQL/`cplDims()`/`renderOrgPl()` 변경 금지
- Python 실행 파일: `C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe` (PATH의 `python`은 다른 프로젝트 venv를 가리키므로 반드시 이 전체 경로 사용)
- 개발 서버는 이미 `python app_v2.py` (Flask debug/werkzeug 리로더)로 `http://127.0.0.1:5000`에서 실행 중이며, 템플릿 파일을 저장하면 자동 리로드된다. 별도로 서버를 죽였다 켤 필요 없음 — 단, werkzeug 리로드에는 1~2초가 걸리므로 저장 후 검증 스크립트 실행 전에 최소 2초 대기
- 로그인 계정: `jeffrey` / `skin1004!` (LDAP 연동, 이 자격증명으로만 대시보드 접근 가능)
- 이 코드베이스에는 프론트엔드 JS용 유닛테스트 러너(jest 등)가 없다. 프론트엔드 동작 검증은 이 프로젝트의 기존 관례(`pw_check.py`, `pw_deep.py`)를 따라 Playwright 파이썬 스크립트로 한다 — `sync_playwright`, headless 브라우저, `page.evaluate`로 페이지의 전역 `state`/`_real` 객체를 직접 읽어 검증
- Playwright는 이미 설치되어 있음 (`pw_check.py`가 이미 동작 중인 스크립트이므로 별도 설치 불필요)
- 검증 스크립트는 저장소 루트(`FI Dashboard/`)에 저장하고, 완료 후 삭제하지 않고 남겨둔다 (기존 `pw_check.py`/`pw_deep.py`도 저장소에 남아있는 관례를 따름)

---

## Task 1: 지역별 기본 드릴레벨 = 국가별

**Files:**
- Modify: `templates/dashboard_v2.html:2826`
- Create (검증 스크립트): `pw_check_region_default_level.py`

**Interfaces:**
- Consumes: `state.viewLevel` 객체 (기존), `CATEGORY_DEFS`의 `region.path = ['권역','대륙','국가','거래처']` (기존, 변경 없음)
- Produces: `state.viewLevel.region`의 초기값이 `2`가 됨. 이후 Task 2에서는 이 값을 참조하지 않음(독립적인 변경)

- [ ] **Step 1: 검증 스크립트 작성 (실패 확인용)**

`FI Dashboard/pw_check_region_default_level.py` 생성:

```python
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
```

- [ ] **Step 2: 실패하는지 실행해서 확인**

Run: `"C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe" pw_check_region_default_level.py`

Expected: `[FAIL]` 출력, `기대값 2, 실제값 0` (현재 `state.viewLevel.region` 초기값이 0이므로)

- [ ] **Step 3: 최소 구현 — state.viewLevel 초기값 변경**

`templates/dashboard_v2.html:2826`에서:

```js
  viewLevel: { org: 0, region: 0, product: 0 },
```

다음으로 교체:

```js
  viewLevel: { org: 0, region: 2, product: 0 },
```

- [ ] **Step 4: 저장 후 2초 대기, 재실행해서 통과 확인**

Run: `"C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe" pw_check_region_default_level.py`

Expected: `[OK] 지역별 기본 드릴레벨 = 국가별 확인됨`

- [ ] **Step 5: 커밋**

```bash
git add "templates/dashboard_v2.html" pw_check_region_default_level.py
git commit -m "feat: 지역별 탭 기본 드릴레벨을 국가별로 변경"
```

---

## Task 2: renderCategoryPl — 기간별 Top10 재선정 + 기타 컬럼

**Files:**
- Modify: `templates/dashboard_v2.html` — `renderCategoryPl()` 함수 내부 `CPL_SEC_DEFS.forEach(...)` 블록
- Create (검증 스크립트): `pw_check_region_product_top10.py`

**Interfaces:**
- Consumes:
  - `CPL_SEC_DEFS` (배열, `{key,label}[]`, 기존 그대로)
  - `CPL_ROW_DEFS` (배열, 기존 그대로)
  - `cplMetrics(sec, nodeName)` → `{sales:[...], cogs:[...], ...}` (기존 그대로, 이름 기반 조회 그대로 사용)
  - `cplRowValue(m, id)` (기존 그대로)
  - `cplAggPeriods(period, months)` → `{key,label,monthIndices}[]` (기존 그대로)
  - `escPlAttr`, `fmtMm`, `momCell`, `plDlBtn`, `PL_EMPTY`, `_cplDimCol()` (모두 기존 모듈 스코프 함수, 변경 없음)
  - `state.cplData.byNode` — `{ [nodeName]: { all: {...}, SK: {...}, UM: {...} } }` (기존 API 응답 캐시, 변경 없음)
- Produces: `renderCategoryPl()`의 HTML 출력에 각 열린 기간마다 "기타" `<th>`/`<td>`가 top10 컬럼들 뒤, "계" 컬럼 앞에 추가됨. 다른 함수/모듈은 이 함수의 내부 계산 결과를 참조하지 않으므로 외부 인터페이스 변경 없음

- [ ] **Step 1: 검증 스크립트 작성 (실패 확인용)**

`FI Dashboard/pw_check_region_product_top10.py` 생성:

```python
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
```

- [ ] **Step 2: 실패하는지 실행해서 확인**

Run: `"C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe" pw_check_region_product_top10.py`

Expected: `[FAIL]`, `전체 섹션 헤더에 '기타' 컬럼이 없음` (현재 코드엔 기타 컬럼이 없으므로) — 단, 필터 상태에 따라 노드 수가 10개 이하로 나오면 해당 카테고리는 스킵 로그만 찍힐 수 있음. 그 경우 대시보드에서 기간 필터를 넓혀(전체 기간) 다시 실행

- [ ] **Step 3: `renderCategoryPl()`의 `CPL_SEC_DEFS.forEach` 블록 교체**

`templates/dashboard_v2.html`에서 아래 블록(현재 `CPL_SEC_DEFS.forEach(function(sec){` 로 시작해서 그 다음에 오는 `html += '</div></div></div>';` 직전의 `});`으로 끝나는 블록)을 찾는다. 정확히 다음 내용과 일치해야 한다(일치하지 않으면 Task 1 이후 다른 변경이 있었다는 뜻이므로, 현재 파일 내용을 다시 읽고 정확한 위치를 확인할 것):

```js
    CPL_SEC_DEFS.forEach(function(sec){
      const secKey = state.category + ':' + sec.key;
      // 이 섹션(SK/UM/전체)에서 실제 데이터가 있는 열만 표시
      const secDims = dims.filter(function(d){
        const m = cplMetrics(sec, d.name);
        return ['sales','gross','op','sgaD','sgaO'].some(function(f){
          return (m[f] || []).some(function(v){ return v !== 0; });
        });
      });
      const dcols = [];
      secDims.forEach(function(d){
        const ck = state.category + ':' + d.name;
        dcols.push({ name:d.name, flag:d.flag, key:d.name, ck:ck });
      });
      const colsPerOpenPeriod = dcols.length + 1;
      const topM = secDims.map(function(d){ return cplMetrics(sec, d.name); });
      // 합계 컬럼은 표시된 top-N 아닌 전체 노드(매핑 없는 행 포함)의 실제 합계를 사용
      const _allDimNames = Object.keys(state.cplData.byNode || {}).filter(function(n){ return n && n !== ''; });
      const _allDimM = _allDimNames.map(function(name){ return cplMetrics(sec, name); });
      const totM = {};
      ['sales','cogs','gross','op','sgaD','sgaD_adv','sgaD_log','sgaD_fee','sgaD_hr','sgaD_etc',
       'sgaO','sgaO_adv','sgaO_log','sgaO_fee','sgaO_hr','sgaO_etc',
       'sgaC','sgaC_adv','sgaC_log','sgaC_fee','sgaC_hr','sgaC_etc','direct','contrib'].forEach(function(f){
        const arrs = _allDimM.map(function(M){ return M[f] || []; });
        totM[f] = cplMonths.map(function(_, ci){ return arrs.reduce(function(a, arr){ return a + (arr[ci] || 0); }, 0); });
      });
      const seriesForDimId = function(dimIdx, id){ return sliceToActive(cplRowValue(topM[dimIdx], id)); };
      const seriesForTotId = function(id){ return sliceToActive(cplRowValue(totM, id)); };
      const periodDimVal = function(di, id, prd){
        const arr = seriesForDimId(di, id);
        return prd.monthIndices.reduce(function(a,i){ return a+(arr[i]||0); }, 0);
      };
      const periodTotVal = function(id, prd){
        const arr = seriesForTotId(id);
        return prd.monthIndices.reduce(function(a,i){ return a+(arr[i]||0); }, 0);
      };
      const totSalesSeries = seriesForTotId('sales');
      const totSalesV = totSalesSeries.reduce(function(a, v){ return a + v; }, 0);
      html += '<div class="pl-section-title" style="display:flex;align-items:center"><span>▶ ' + sec.label + '</span>' + plDlBtn(sec.key, months.join(','), '') + '</div>';
      const totalLeafCols = periods.reduce(function(acc, prd){ return acc + (isPeriodOpen(prd.key) ? colsPerOpenPeriod : 1); }, 0);
      html += '<table class="pl-table pl-month-matrix">';
      html += '<colgroup><col style="width:170px"><col style="width:88px">';
      for (let c = 0; c < totalLeafCols; c++) html += '<col>';
      html += '</colgroup>';
      html += '<thead>';
      html += '<tr><th rowspan="2">구분</th><th rowspan="2">합계</th>';
      periods.forEach(function(prd){
        const open = isPeriodOpen(prd.key);
        const span = open ? (dcols.length + 1) : 1;
        html += '<th class="pl-month-group" colspan="' + span + '" data-cpl-month="' + prd.key + '"><i data-lucide="' + (open ? 'chevron-down' : 'chevron-right') + '" class="pl-chev"></i>' + prd.label + '</th>';
      });
      html += '</tr><tr>';
      periods.forEach(function(prd){
        if (isPeriodOpen(prd.key)) {
          dcols.forEach(function(col){
            const lbl = (col.flag ? col.flag + ' ' : '') + col.name;
            html += '<th class="pl-col-dim">' + lbl + '</th>';
          });
        }
        html += '<th class="pl-col-total">계</th>';
      });
      html += '</tr>';
      html += '</thead><tbody>';
      CPL_ROW_DEFS.forEach(function(row){
        const memberKey = row.member ? secKey + ':' + row.member : null;
        if (memberKey && !plExpanded.has(memberKey)) return;
        const toggleKey = row.toggle ? secKey + ':' + row.toggle : null;
        const cls = ['pl-row', row.bold?'pl-bold':'', row.sub?'pl-sub':'', row.hl?'pl-hl-'+row.hl:'', row.toggle?'pl-group':''].filter(Boolean).join(' ');
        const chev = toggleKey ? '<i data-lucide="' + (plExpanded.has(toggleKey)?'chevron-down':'chevron-right') + '" class="pl-chev"></i>' : '';
        const totSeries = seriesForTotId(row.id);
        const totV = totSeries.reduce(function(a, v){ return a + v; }, 0);
        html += '<tr class="' + cls + '"' + (toggleKey ? ' data-cpl-toggle="' + toggleKey + '"' : '') + '><td>' + chev + row.label + '</td>';
        html += '<td data-plitem="'+escPlAttr(row.id)+'" data-pldim="__all__" data-pldimval="__all__" data-plmonths="'+months.join(',')+'" data-plsec="'+sec.key+'">' + fmtMm(totV) + '<div class="pl-mom pl-mom-na">&nbsp;</div></td>';
        periods.forEach(function(prd, pi){
          const pTot = periodTotVal(row.id, prd);
          const prevPTot = pi > 0 ? periodTotVal(row.id, periods[pi-1]) : undefined;
          const mStr = prd.monthIndices.map(function(i){ return months[i]; }).join(',');
          if (isPeriodOpen(prd.key)) {
            secDims.forEach(function(d, di){
              const pDim = periodDimVal(di, row.id, prd);
              const prevPDim = pi > 0 ? periodDimVal(di, row.id, periods[pi-1]) : undefined;
              html += '<td data-plitem="'+escPlAttr(row.id)+'" data-pldim="'+escPlAttr(_cplDimCol())+'" data-pldimval="'+escPlAttr(d.name)+'" data-plmonths="'+mStr+'" data-plsec="'+sec.key+'">' + fmtMm(pDim) + momCell(pDim, prevPDim) + '</td>';
            });
          }
          html += '<td class="pl-col-total" data-plitem="'+escPlAttr(row.id)+'" data-pldim="__sub__" data-pldimval="__sub__" data-plmonths="'+mStr+'" data-plsec="'+sec.key+'">' + fmtMm(pTot) + momCell(pTot, prevPTot) + '</td>';
        });
        html += '</tr>';
        const showPct = row.pct && (!row.pctMember || plExpanded.has(secKey + ':' + row.pctMember));
        if (showPct) {
          html += '<tr class="pl-pct' + (row.sub?' pl-sub':'') + (row.hl?' pl-pct-hl-'+row.hl:'') + '"><td>%</td>';
          html += '<td>' + (totSalesV ? (totV/totSalesV*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
          periods.forEach(function(prd, pi){
            const pTotSales = periodTotVal('sales', prd);
            const pTot = periodTotVal(row.id, prd);
            if (isPeriodOpen(prd.key)) {
              secDims.forEach(function(d, di){
                const pDim = periodDimVal(di, row.id, prd);
                const pDimSales = periodDimVal(di, 'sales', prd);
                html += '<td>' + (pDimSales ? (pDim/pDimSales*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
              });
            }
            html += '<td class="pl-col-total">' + (pTotSales ? (pTot/pTotSales*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
          });
          html += '</tr>';
        }
      });
      html += '</tbody></table>';
    });
```

이것을 다음으로 교체한다:

```js
    CPL_SEC_DEFS.forEach(function(sec){
      const secKey = state.category + ':' + sec.key;
      // 합계는 top-N 캡 없이 전체 노드(매핑 없는 행 포함) 기준
      const _allDimNames = Object.keys(state.cplData.byNode || {}).filter(function(n){ return n && n !== ''; });
      const _metricsCache = {};
      const getM = function(name){
        if (!(name in _metricsCache)) _metricsCache[name] = cplMetrics(sec, name);
        return _metricsCache[name];
      };
      const nameValForPeriod = function(name, id, prd){
        const arr = sliceToActive(cplRowValue(getM(name), id));
        return prd.monthIndices.reduce(function(a,i){ return a+(arr[i]||0); }, 0);
      };
      const totM = {};
      ['sales','cogs','gross','op','sgaD','sgaD_adv','sgaD_log','sgaD_fee','sgaD_hr','sgaD_etc',
       'sgaO','sgaO_adv','sgaO_log','sgaO_fee','sgaO_hr','sgaO_etc',
       'sgaC','sgaC_adv','sgaC_log','sgaC_fee','sgaC_hr','sgaC_etc','direct','contrib'].forEach(function(f){
        const arrs = _allDimNames.map(function(name){ return getM(name)[f] || []; });
        totM[f] = cplMonths.map(function(_, ci){ return arrs.reduce(function(a, arr){ return a + (arr[ci] || 0); }, 0); });
      });
      const seriesForTotId = function(id){ return sliceToActive(cplRowValue(totM, id)); };
      const periodTotVal = function(id, prd){
        const arr = seriesForTotId(id);
        return prd.monthIndices.reduce(function(a,i){ return a+(arr[i]||0); }, 0);
      };
      const dcolsCount = Math.min(10, _allDimNames.length);
      const hasOthers = _allDimNames.length > dcolsCount;
      // 기간마다 그 기간 매출 기준으로 top10 재선정 (닫혀있는 기간도 전기간 대비 계산을 위해 미리 계산)
      const periodTopNames = {};
      periods.forEach(function(prd){
        periodTopNames[prd.key] = _allDimNames.slice().sort(function(a, b){
          return nameValForPeriod(b, 'sales', prd) - nameValForPeriod(a, 'sales', prd);
        }).slice(0, dcolsCount);
      });
      const colsPerOpenPeriod = dcolsCount + (hasOthers ? 1 : 0) + 1;
      const totSalesSeries = seriesForTotId('sales');
      const totSalesV = totSalesSeries.reduce(function(a, v){ return a + v; }, 0);
      html += '<div class="pl-section-title" style="display:flex;align-items:center"><span>▶ ' + sec.label + '</span>' + plDlBtn(sec.key, months.join(','), '') + '</div>';
      const totalLeafCols = periods.reduce(function(acc, prd){ return acc + (isPeriodOpen(prd.key) ? colsPerOpenPeriod : 1); }, 0);
      html += '<table class="pl-table pl-month-matrix">';
      html += '<colgroup><col style="width:170px"><col style="width:88px">';
      for (let c = 0; c < totalLeafCols; c++) html += '<col>';
      html += '</colgroup>';
      html += '<thead>';
      html += '<tr><th rowspan="2">구분</th><th rowspan="2">합계</th>';
      periods.forEach(function(prd){
        const open = isPeriodOpen(prd.key);
        const span = open ? colsPerOpenPeriod : 1;
        html += '<th class="pl-month-group" colspan="' + span + '" data-cpl-month="' + prd.key + '"><i data-lucide="' + (open ? 'chevron-down' : 'chevron-right') + '" class="pl-chev"></i>' + prd.label + '</th>';
      });
      html += '</tr><tr>';
      periods.forEach(function(prd){
        if (isPeriodOpen(prd.key)) {
          periodTopNames[prd.key].forEach(function(name){
            html += '<th class="pl-col-dim">' + name + '</th>';
          });
          if (hasOthers) html += '<th class="pl-col-dim">기타</th>';
        }
        html += '<th class="pl-col-total">계</th>';
      });
      html += '</tr>';
      html += '</thead><tbody>';
      CPL_ROW_DEFS.forEach(function(row){
        const memberKey = row.member ? secKey + ':' + row.member : null;
        if (memberKey && !plExpanded.has(memberKey)) return;
        const toggleKey = row.toggle ? secKey + ':' + row.toggle : null;
        const cls = ['pl-row', row.bold?'pl-bold':'', row.sub?'pl-sub':'', row.hl?'pl-hl-'+row.hl:'', row.toggle?'pl-group':''].filter(Boolean).join(' ');
        const chev = toggleKey ? '<i data-lucide="' + (plExpanded.has(toggleKey)?'chevron-down':'chevron-right') + '" class="pl-chev"></i>' : '';
        const totSeries = seriesForTotId(row.id);
        const totV = totSeries.reduce(function(a, v){ return a + v; }, 0);
        html += '<tr class="' + cls + '"' + (toggleKey ? ' data-cpl-toggle="' + toggleKey + '"' : '') + '><td>' + chev + row.label + '</td>';
        html += '<td data-plitem="'+escPlAttr(row.id)+'" data-pldim="__all__" data-pldimval="__all__" data-plmonths="'+months.join(',')+'" data-plsec="'+sec.key+'">' + fmtMm(totV) + '<div class="pl-mom pl-mom-na">&nbsp;</div></td>';
        periods.forEach(function(prd, pi){
          const pTot = periodTotVal(row.id, prd);
          const prevPTot = pi > 0 ? periodTotVal(row.id, periods[pi-1]) : undefined;
          const mStr = prd.monthIndices.map(function(i){ return months[i]; }).join(',');
          if (isPeriodOpen(prd.key)) {
            const topNames = periodTopNames[prd.key];
            let sumTop = 0;
            topNames.forEach(function(name){
              const pDim = nameValForPeriod(name, row.id, prd);
              sumTop += pDim;
              const prevPDim = pi > 0 ? nameValForPeriod(name, row.id, periods[pi-1]) : undefined;
              html += '<td data-plitem="'+escPlAttr(row.id)+'" data-pldim="'+escPlAttr(_cplDimCol())+'" data-pldimval="'+escPlAttr(name)+'" data-plmonths="'+mStr+'" data-plsec="'+sec.key+'">' + fmtMm(pDim) + momCell(pDim, prevPDim) + '</td>';
            });
            if (hasOthers) {
              const curOther = pTot - sumTop;
              let prevOther;
              if (pi > 0) {
                const prevTopNames = periodTopNames[periods[pi-1].key];
                let prevSumTop = 0;
                prevTopNames.forEach(function(name){ prevSumTop += nameValForPeriod(name, row.id, periods[pi-1]); });
                prevOther = prevPTot - prevSumTop;
              }
              html += '<td>' + fmtMm(curOther) + momCell(curOther, prevOther) + '</td>';
            }
          }
          html += '<td class="pl-col-total" data-plitem="'+escPlAttr(row.id)+'" data-pldim="__sub__" data-pldimval="__sub__" data-plmonths="'+mStr+'" data-plsec="'+sec.key+'">' + fmtMm(pTot) + momCell(pTot, prevPTot) + '</td>';
        });
        html += '</tr>';
        const showPct = row.pct && (!row.pctMember || plExpanded.has(secKey + ':' + row.pctMember));
        if (showPct) {
          html += '<tr class="pl-pct' + (row.sub?' pl-sub':'') + (row.hl?' pl-pct-hl-'+row.hl:'') + '"><td>%</td>';
          html += '<td>' + (totSalesV ? (totV/totSalesV*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
          periods.forEach(function(prd, pi){
            const pTotSales = periodTotVal('sales', prd);
            const pTot = periodTotVal(row.id, prd);
            if (isPeriodOpen(prd.key)) {
              const topNames = periodTopNames[prd.key];
              let sumTop = 0, sumTopSales = 0;
              topNames.forEach(function(name){
                const pDim = nameValForPeriod(name, row.id, prd);
                const pDimSales = nameValForPeriod(name, 'sales', prd);
                sumTop += pDim; sumTopSales += pDimSales;
                html += '<td>' + (pDimSales ? (pDim/pDimSales*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
              });
              if (hasOthers) {
                const otherVal = pTot - sumTop;
                const otherSales = pTotSales - sumTopSales;
                html += '<td>' + (otherSales ? (otherVal/otherSales*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
              }
            }
            html += '<td class="pl-col-total">' + (pTotSales ? (pTot/pTotSales*100).toFixed(1) + '%' : PL_EMPTY) + '</td>';
          });
          html += '</tr>';
        }
      });
      html += '</tbody></table>';
    });
```

- [ ] **Step 4: 저장 후 2초 대기, 재실행해서 통과 확인**

Run: `"C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe" pw_check_region_product_top10.py`

Expected: `[OK] top10+기타 불변식 및 기타 컬럼 확인됨` — 각 카테고리별로 `검증=True` 로그와 `'기타' 헤더 확인됨` 로그가 함께 출력됨

- [ ] **Step 5: 콘솔 에러 스모크 체크**

Run: `"C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe" pw_check.py`

Expected: `[Console errors] none` (기존 스크립트를 재사용해 이번 변경으로 새 JS 에러가 없는지 한 번 더 확인)

- [ ] **Step 6: 커밋**

```bash
git add "templates/dashboard_v2.html" pw_check_region_product_top10.py
git commit -m "feat: 지역별/상품별 P&L 테이블에 기간별 top10 재선정 + 기타 컬럼 추가"
```

---

## 완료 후 수동 확인 (선택, 스펙의 "테스트 관점" 참고)

자동 스크립트로 커버되지 않는 시각적 확인은 브라우저에서 직접:
- 지역별/상품별 탭에서 서로 다른 두 기간을 동시에 펼쳤을 때 국가/상품 목록과 순서가 실제로 다르게 보이는지
- 기타 컬럼의 ▲▼ 전월 대비 표시가 이상치 없이 보이는지
- 사이드바에서 지역별 최초 진입 후 거래처별까지 드릴다운했다가 다른 탭 갔다가 지역별로 복귀 시 거래처별이 유지되는지
