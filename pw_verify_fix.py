# -*- coding: utf-8 -*-
"""데이터 레이블 수정 + 초기화 버튼 + 디자인 검증"""
import sys, time, os
sys.stdout.reconfigure(encoding='utf-8')
BASE = 'http://127.0.0.1:5000'
SHOTS = r'C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard\pw_shots'
from playwright.sync_api import sync_playwright

R = []
def check(name, ok, note=''):
    R.append((name, ok, note))
    print(('[OK]   ' if ok else '[FAIL] ') + name + ((' -- ' + str(note)) if note else ''))

SET_CFG = '''(label) => {
    const c = state.tableau.config;
    c.chartType='bar'; c.mode='chart';
    c.rows=['Brand']; c.columns=['Year_Month']; c.measures=['Operating_Income'];
    c.color=null; c.size=null; c.label=label; c.detail=[];
    c.filters={}; c.measureAggs={Operating_Income:'SUM'}; c.tableCalcs={};
    c.fieldSorts=[]; c.sort='desc'; c.limit=500;
    c.dateGranularity={}; c.showRefLine=false; c.topN=null;
    tblRenderShelfChips(); tblSyncToolbar(); tblExecuteQuery();
}'''

with sync_playwright() as p:
    br = p.chromium.launch(headless=True)
    page = br.new_context(viewport={'width':1600,'height':900}).new_page()
    js_errors = []
    page.on('pageerror', lambda e: js_errors.append(str(e)))

    page.goto(BASE+'/login', wait_until='networkidle')
    page.fill('input[name="username"]', 'jeffrey')
    page.fill('input[name="password"]', 'skin1004!')
    page.click('button[type="submit"]')
    page.wait_for_url('**/dashboard', timeout=10000)
    time.sleep(2.5)
    page.click('[data-cat="tableau"]')
    time.sleep(2.5)

    # ── 1. 크로스탭 + 레이블 선반 → 데이터 레이블 표시 ──
    page.evaluate(SET_CFG, 'Operating_Income')
    time.sleep(3.5)
    label_show = page.evaluate('''() => {
        const inst = state.tableau.echartsInst;
        if (!inst) return 'no-inst';
        return (inst.getOption().series||[]).map(s => !!(s.label && s.label.show)).join(',');
    }''')
    check('크로스탭 데이터 레이블', 'true' in str(label_show) and 'false' not in str(label_show), label_show)
    page.screenshot(path=os.path.join(SHOTS,'after_label_crosstab.png'))

    # ── 2. 단일 차원(비크로스탭) 레이블 ──
    page.evaluate('''() => {
        const c = state.tableau.config;
        c.rows=['Brand']; c.columns=[]; c.label='Operating_Income';
        tblRenderShelfChips(); tblExecuteQuery();
    }''')
    time.sleep(3)
    label_show2 = page.evaluate('''() => {
        const s = state.tableau.echartsInst.getOption().series||[];
        return s.map(x => !!(x.label && x.label.show)).join(',');
    }''')
    check('단일차원 데이터 레이블', 'true' in str(label_show2), label_show2)

    # ── 3. 파이 차트 레이블 ──
    page.evaluate('''() => {
        state.tableau.config.chartType='pie';
        tblSyncToolbar(); tblExecuteQuery();
    }''')
    time.sleep(3)
    pie_fmt = page.evaluate('''() => {
        const s = (state.tableau.echartsInst.getOption().series||[])[0];
        return s && s.label && typeof s.label.formatter === 'function';
    }''')
    check('파이 레이블 포맷터', bool(pie_fmt), str(pie_fmt))
    page.screenshot(path=os.path.join(SHOTS,'after_label_pie.png'))

    # ── 4. 산점도 (레이블+툴팁 p.value 마이그레이션) ──
    page.evaluate('''() => {
        const c = state.tableau.config;
        c.chartType='scatter'; c.measures=['Sales_Amount','Operating_Income']; c.label='Brand';
        tblRenderShelfChips(); tblSyncToolbar(); tblExecuteQuery();
    }''')
    time.sleep(3.5)
    sc = page.evaluate('''() => {
        const s = (state.tableau.echartsInst.getOption().series||[])[0];
        if (!s) return 'no-series';
        const d = s.data && s.data[0];
        return JSON.stringify({label: !!(s.label && s.label.show), hasRow: !!(d && d.__row), isObj: !!(d && d.value)});
    }''')
    check('산점도 레이블+__row', '"label":true' in str(sc) and '"hasRow":true' in str(sc), sc)
    page.screenshot(path=os.path.join(SHOTS,'after_label_scatter.png'))

    # ── 5. 초기화 버튼 ──
    page.evaluate(SET_CFG, None)
    time.sleep(3)
    check('초기화 버튼 존재', page.locator('#tblResetAll').count() > 0)
    page.on('dialog', lambda d: d.accept())
    page.click('#tblResetAll')
    time.sleep(1.5)
    after_reset = page.evaluate('''() => {
        const c = state.tableau.config;
        return JSON.stringify({rows:c.rows, cols:c.columns, meas:c.measures, label:c.label,
            chips: document.querySelectorAll('.tbl-s-chip').length,
            empty: !!document.querySelector('#tblViz .tbl-viz-empty')});
    }''')
    ok_reset = '"rows":[]' in after_reset and '"meas":[]' in after_reset and '"chips":0' in after_reset and '"empty":true' in after_reset
    check('초기화 동작', ok_reset, after_reset)
    page.screenshot(path=os.path.join(SHOTS,'after_reset.png'))

    # ── 6. Undo 로 복원 가능 ──
    page.keyboard.press('Control+z')
    time.sleep(2.5)
    undo_rows = page.evaluate('state.tableau.config.rows.length')
    check('초기화 후 Undo 복원', undo_rows > 0, f'rows={undo_rows}')

    # ── 7. 차트 5종 전환 + 스택바 inside 레이블 ──
    page.evaluate(SET_CFG, 'Operating_Income')
    time.sleep(3)
    page.evaluate('''() => { state.tableau.config.chartType='stacked_bar'; tblSyncToolbar(); tblExecuteQuery(); }''')
    time.sleep(3)
    stacked_pos = page.evaluate('''() => {
        const s = (state.tableau.echartsInst.getOption().series||[])[0];
        return s && s.label && s.label.position;
    }''')
    check('스택바 inside 레이블', stacked_pos == 'inside', str(stacked_pos))
    page.screenshot(path=os.path.join(SHOTS,'after_stacked_label.png'))

    for ct in ['heatmap','treemap','bubble','donut','bar']:
        page.evaluate('''(t) => { state.tableau.config.chartType=t; tblSyncToolbar(); tblExecuteQuery(); }''', ct)
        time.sleep(2.2)
    check('차트 전환 무에러', len(js_errors)==0, '; '.join(js_errors[:3]))

    # ── 8. 디자인 스크린샷 (최종) ──
    page.evaluate(SET_CFG, 'Operating_Income')
    time.sleep(3.5)
    page.screenshot(path=os.path.join(SHOTS,'after_design_light.png'))
    # 다크 테마
    page.evaluate('''() => { document.documentElement.classList.add('theme-dark'); document.documentElement.classList.remove('theme-light'); tblExecuteQuery(); }''')
    time.sleep(3)
    page.screenshot(path=os.path.join(SHOTS,'after_design_dark.png'))

    check('전체 JS 에러 없음', len(js_errors)==0, '; '.join(js_errors[:5]))
    br.close()

print()
passed = sum(1 for _,ok,_ in R if ok)
failed = [(n,note) for n,ok,note in R if not ok]
print(f'결과: PASS {passed}/{len(R)}')
for n, note in failed:
    print(f'  FAIL - {n}' + (f' ({note})' if note else ''))
sys.exit(0 if not failed else 1)
