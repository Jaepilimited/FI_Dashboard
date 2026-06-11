# -*- coding: utf-8 -*-
"""커스텀 분석 전체 기능 종합 테스트 (API + UI)"""
import sys, json, time, os
sys.stdout.reconfigure(encoding='utf-8')

BASE  = 'http://172.16.1.250:5000'
SHOTS = r'C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard\pw_shots'
R = []

def check(name, ok, note=''):
    R.append((name, ok, note))
    print(('[OK]   ' if ok else '[FAIL] ') + name + ((' -- ' + str(note)) if note else ''))

# ════════════════ PART 1: API 테스트 ════════════════
print('=' * 60)
print('PART 1: API 테스트')
print('=' * 60)
sys.path.insert(0, r'C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard')
import app_v2 as flask_app
flask_app.app.config['TESTING'] = True
flask_app.app.secret_key = 'test'
api = flask_app.app.test_client()
with api.session_transaction() as s:
    s['user'] = {'id': 1, 'username': 'jeffrey', 'display_name': 'J', 'role': 'admin'}

def q(cfg):
    base = {'chartType':'bar','mode':'chart','rows':[],'columns':[],'measures':['Operating_Income'],
            'color':None,'size':None,'label':None,'detail':[],'filters':{},'measureAggs':{},
            'fieldSorts':[],'sort':'desc','limit':100}
    base.update(cfg)
    r = api.post('/api/tableau/query', data=json.dumps({'config': base}), content_type='application/json')
    return r.status_code, (r.get_json() or {})

# 1. 기본 쿼리
st, d = q({'rows':['Sales_Type']})
check('기본 쿼리', st==200 and len(d.get('rows',[]))>0, f"{len(d.get('rows',[]))} rows")

# 2. 크로스탭
st, d = q({'rows':['Country'],'columns':['Sales_Type']})
check('크로스탭', st==200 and d.get('row_fields')==['Country'] and d.get('col_fields')==['Sales_Type'])

# 3. 색상 필드
st, d = q({'color':'Sales_Type'})
check('색상 필드', st==200 and d.get('color_field')=='Sales_Type' and 'Sales_Type' in d.get('group_by',[]))

# 4. 크기 필드(측정값)
st, d = q({'rows':['Country'],'size':'Sales_Amount'})
check('크기(측정값)', st==200 and d.get('size_field')=='Sales_Amount')

# 5. 크기 필드(차원)
st, d = q({'rows':['Sales_Type'],'size':'Country'})
check('크기(차원)', st==200 and 'Country' in d.get('group_by',[]))

# 6. 레이블/세부정보
st, d = q({'rows':['Sales_Type'],'label':'Operating_Income','detail':['Continent1']})
check('레이블/세부정보', st==200 and d.get('label_field')=='Operating_Income' and d.get('detail_fields')==['Continent1'])

# 7. 다중 정렬
st, d = q({'rows':['Country','Sales_Type'],'fieldSorts':[{'field':'Country','dir':'asc'},{'field':'Sales_Type','dir':'desc'}]})
check('다중 정렬', st==200 and len(d.get('rows',[]))>0)

# 8. 값 필터
st, d = q({'rows':['Country'],'filters':{'Sales_Type':['B2B']}})
check('값 필터', st==200 and len(d.get('rows',[]))>0)

# 9. 와일드카드 필터 (포함)
st, d = q({'rows':['Country'],'filters':{'__wc__Country':{'field':'Country','patterns':['한'],'exclude':False}}})
rows = d.get('rows',[])
check('와일드카드(포함)', st==200 and len(rows)==1 and rows[0]['Country']=='한국', str([r['Country'] for r in rows]))

# 10. 와일드카드 필터 (제외)
st, d = q({'rows':['Country'],'filters':{'__wc__Country':{'field':'Country','patterns':['한'],'exclude':True}},'limit':500})
rows = d.get('rows',[])
check('와일드카드(제외)', st==200 and len(rows)>100 and all(r['Country']!='한국' for r in rows), f"{len(rows)} rows")

# 11. Top-N
st, d = q({'rows':['Country'],'topN':{'n':5,'measure':'Operating_Income','dir':'desc'}})
check('Top-N(5)', st==200 and len(d.get('rows',[]))<=5, f"{len(d.get('rows',[]))} rows")

# 12. 날짜 단위 YEAR
st, d = q({'rows':['Year_Month'],'dateGranularity':{'Year_Month':'YEAR'},'sort':'asc'})
rows = d.get('rows',[])
check('날짜 YEAR', st==200 and rows and len(str(rows[0]['Year_Month']))==4, str(rows[:1]))

# 13. 날짜 단위 QUARTER
st, d = q({'rows':['Year_Month'],'dateGranularity':{'Year_Month':'QUARTER'},'sort':'asc'})
rows = d.get('rows',[])
check('날짜 QUARTER', st==200 and rows and 'Q' in str(rows[0]['Year_Month']), str(rows[:1]))

# 14. 집계 AVG
st, d = q({'rows':['Sales_Type'],'measures':['Sales_Amount'],'measureAggs':{'Sales_Amount':'AVG'}})
check('집계 AVG', st==200 and len(d.get('rows',[]))>0)

# 15. 집계 COUNTD
st, d = q({'rows':['Sales_Type'],'measures':['Sales_Amount'],'measureAggs':{'Sales_Amount':'COUNTD'}})
check('집계 COUNTD', st==200 and len(d.get('rows',[]))>0)

# 16. limit
st, d = q({'rows':['Customer'],'limit':7})
check('행수 제한(7)', st==200 and len(d.get('rows',[]))<=7, f"{len(d.get('rows',[]))} rows")

# 17. 측정값 없음 → 400
st, d = q({'measures':[]})
check('측정값 없음→400', st==400)

# 18. 잘못된 필드 무시
st, d = q({'rows':['__hack__; DROP TABLE x;--'],'measures':['Operating_Income']})
check('인젝션 필드 무시', st==200 and '__hack__; DROP TABLE x;--' not in d.get('group_by',[]))

# ════════════════ PART 2: UI 테스트 (Playwright) ════════════════
print()
print('=' * 60)
print('PART 2: UI 테스트 (Playwright)')
print('=' * 60)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    br = p.chromium.launch(headless=True)
    page = br.new_context(viewport={'width':1600,'height':900}).new_page()
    js_errors = []
    page.on('pageerror', lambda e: js_errors.append(str(e)))

    # 로그인
    page.goto(BASE+'/login', wait_until='networkidle')
    page.fill('input[name="username"]', 'jeffrey')
    page.fill('input[name="password"]', 'skin1004!')
    page.click('button[type="submit"]')
    page.wait_for_url('**/dashboard', timeout=10000)
    time.sleep(2.5)
    check('로그인', True)

    # 커스텀 분석 탭
    page.click('[data-cat="tableau"]')
    time.sleep(2.5)
    check('커스텀 분석 탭 진입', page.locator('#tblWrap').count()>0)

    # 결정적 시작 상태 세팅 (이전 테스트가 남긴 저장 뷰 상태에 의존하지 않도록)
    page.evaluate('''() => {
        const c = state.tableau.config;
        c.chartType='bar'; c.mode='chart';
        c.rows=['Brand']; c.columns=['Year_Month']; c.measures=['Operating_Income'];
        c.color=null; c.size=null; c.label=null; c.detail=[];
        c.filters={'Sales_Type':[]}; c.measureAggs={Operating_Income:'SUM'}; c.tableCalcs={};
        c.fieldSorts=[]; c.sort='desc'; c.limit=500;
        c.dateGranularity={}; c.showRefLine=false; c.topN=null;
        state.tableau.history=[JSON.stringify(c)]; state.tableau.historyIndex=0;
        tblRenderShelfChips(); tblSyncToolbar(); tblExecuteQuery();
    }''')
    time.sleep(2.5)

    # 선반 8개
    for shelf in ['rows','columns','measures','color','size','label','detail','filters']:
        check(f'선반: {shelf}', page.locator(f'[data-shelf="{shelf}"]').count()>0)

    # 툴바 버튼
    check('Undo 버튼', page.locator('#tblUndo').count()>0)
    check('Redo 버튼', page.locator('#tblRedo').count()>0)
    check('Swap 버튼', page.locator('#tblSwapAxes').count()>0)
    check('기준선 버튼', page.locator('#tblRefLine').count()>0)

    # Swap 동작: 행/열 칩 교환 확인
    rows_before = page.locator('#tblChips_rows .tbl-s-chip').count()
    cols_before = page.locator('#tblChips_columns .tbl-s-chip').count()
    page.click('#tblSwapAxes')
    time.sleep(1.5)
    rows_after = page.locator('#tblChips_rows .tbl-s-chip').count()
    cols_after = page.locator('#tblChips_columns .tbl-s-chip').count()
    check('Swap 동작', rows_after==cols_before and cols_after==rows_before,
          f"before r{rows_before}/c{cols_before} after r{rows_after}/c{cols_after}")
    # 원복
    page.click('#tblSwapAxes')
    time.sleep(1)

    # Undo 활성화 확인 (swap 2회 했으므로)
    check('Undo 활성화됨', not page.locator('#tblUndo').is_disabled())

    # 기준선 토글
    page.click('#tblRefLine')
    time.sleep(0.8)
    check('기준선 활성 클래스', 'active' in (page.locator('#tblRefLine').get_attribute('class') or ''))
    page.click('#tblRefLine')
    time.sleep(0.5)

    # 피벗 모드 → pivot-mode 클래스 + 차트버튼 비활성 스타일
    page.click('.tbl-mode-btn[data-mode="pivot"]')
    time.sleep(1.5)
    check('피벗 모드 클래스', 'pivot-mode' in (page.locator('#tblWrap').get_attribute('class') or ''))
    # 음수 빨간색 셀
    neg_cells = page.locator('.tbl-pivot-table td.num.neg').count()
    check('피벗 음수 빨간색', neg_cells > 0, f"{neg_cells} neg cells")
    page.screenshot(path=os.path.join(SHOTS,'t01_pivot_neg.png'))

    # 차트 모드 복귀
    page.click('.tbl-mode-btn[data-mode="chart"]')
    time.sleep(1.5)
    check('차트 모드 복귀', 'pivot-mode' not in (page.locator('#tblWrap').get_attribute('class') or ''))

    # 날짜 단위 배지 사이클 (Year_Month 칩이 columns에 있다고 가정)
    gran = page.locator('.tbl-gran-badge').first
    if gran.count():
        before_g = gran.text_content()
        gran.click()
        time.sleep(1.5)
        after_g = page.locator('.tbl-gran-badge').first.text_content()
        check('날짜 단위 사이클', before_g != after_g, f"{before_g} → {after_g}")
        # 원복 위해 3번 더 클릭 (4단계 사이클)
        for _ in range(3):
            page.locator('.tbl-gran-badge').first.click()
            time.sleep(1.2)
    else:
        check('날짜 단위 사이클', False, 'gran badge 없음')

    # agg 메뉴: 테이블 계산 옵션 존재
    badge = page.locator('.tbl-agg-badge').first
    if badge.count():
        badge.click()
        time.sleep(0.6)
        has_calc = page.locator('#tblAggDrop [data-calc="pct_total"]').count() > 0
        check('테이블 계산 메뉴', has_calc)
        # % of total 적용
        if has_calc:
            page.click('#tblAggDrop [data-calc="pct_total"]')
            time.sleep(1)
            check('계산 배지 표시', page.locator('.tbl-calc-badge').count() > 0)
            page.screenshot(path=os.path.join(SHOTS,'t02_pct_total.png'))
            # 기본 집계로 복원
            page.locator('.tbl-agg-badge').first.click()
            time.sleep(0.5)
            page.click('#tblAggDrop [data-calc="none"]')
            time.sleep(0.8)
    else:
        check('테이블 계산 메뉴', False, 'agg badge 없음')

    # 필터 팝업 탭
    fchip = page.locator('#tblChips_filters .tbl-s-chip').first
    if fchip.count():
        fchip.click()
        time.sleep(1.5)
        check('필터 팝업 열림', page.locator('#tblFilterOverlay').is_visible())
        check('탭: 값 선택', page.locator('.tbl-ftab[data-tab="values"]').count()>0)
        check('탭: Top N', page.locator('.tbl-ftab[data-tab="topn"]').count()>0)
        check('탭: 와일드카드', page.locator('.tbl-ftab[data-tab="wildcard"]').count()>0)
        # Top N 탭 전환
        page.click('.tbl-ftab[data-tab="topn"]')
        time.sleep(0.4)
        check('Top N 탭 표시', page.locator('#tblFiltTabTopn').is_visible())
        page.click('#tblFiltClose')
        time.sleep(0.3)
    else:
        check('필터 팝업', False, '필터 칩 없음')

    # 정렬 셀렉트 비활성화 (fieldSorts 있을 때)
    has_sorts = page.evaluate('state.tableau.config.fieldSorts.length > 0')
    sort_disabled = page.locator('#tblSortSel').is_disabled()
    check('정렬 셀렉트 상태 일치', has_sorts == sort_disabled, f"sorts={has_sorts} disabled={sort_disabled}")

    # 칩 텍스트 ellipsis 클래스
    check('칩 텍스트 span', page.locator('.tbl-chip-txt').count() > 0)

    # 1024 좁은 화면에서 칩 세로 깨짐 없는지 (필터 칩 높이 검사)
    page.set_viewport_size({'width':1024,'height':768})
    time.sleep(1)
    fc = page.locator('.tbl-filter-count').first
    if fc.count():
        box = fc.bounding_box()
        check('필터 배지 한 줄 유지(1024px)', box and box['height'] < 30, f"h={box['height'] if box else 'N/A'}")
    page.screenshot(path=os.path.join(SHOTS,'t03_narrow_1024.png'))
    page.set_viewport_size({'width':1600,'height':900})
    time.sleep(0.8)

    # 차트 유형 전환 (파이, 히트맵, 트리맵) — JS 에러 없이 렌더
    for ct in ['pie','heatmap','treemap','scatter','bar']:
        page.click(f'.tbl-chart-btn[data-type="{ct}"]')
        time.sleep(1.5)
    check('차트 5종 전환 무에러', len(js_errors)==0, '; '.join(js_errors[:3]))

    # CSV 내보내기 (다운로드 트리거)
    with page.expect_download(timeout=8000) as dl:
        page.click('#tblExportCSV')
    check('CSV 다운로드', dl.value is not None)

    # 최종 JS 에러 체크
    check('전체 JS 에러 없음', len(js_errors)==0, '; '.join(js_errors[:5]))
    page.screenshot(path=os.path.join(SHOTS,'t04_final.png'))
    br.close()

# ════════════════ 결과 ════════════════
print()
print('=' * 60)
passed = sum(1 for _,ok,_ in R if ok)
failed = [(n,note) for n,ok,note in R if not ok]
print(f'결과: PASS {passed}/{len(R)}')
if failed:
    print('FAILED:')
    for n, note in failed:
        print(f'  - {n}' + (f' ({note})' if note else ''))
sys.exit(0 if not failed else 1)
