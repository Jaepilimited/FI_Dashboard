# Monthly Report 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 경영진용 월간 재무 스코어카드 리포트를 `/report` 라우트로 서빙하는 독립 HTML 페이지 구현

**Architecture:** 기존 Flask + BigQuery 인프라 위에 새 라우트와 템플릿만 추가. 데이터는 클라이언트 JS가 기존 `/api/*` 엔드포인트를 호출해 렌더링. 전월은 JS가 자동 계산.

**Tech Stack:** Flask (Python), Jinja2, Vanilla JS (fetch API), Pretendard 폰트 (기존 대시보드와 동일)

**Spec:** `docs/superpowers/specs/2026-06-10-monthly-report-design.md`

---

## 파일 맵

| 파일 | 작업 |
|------|------|
| `app.py` | `/report` 라우트 추가 (5줄) |
| `templates/report.html` | 신규 생성 — 전체 리포트 템플릿 |
| `tests/test_report_route.py` | 신규 생성 — 라우트 테스트 |

---

## Task 1: Flask 라우트 추가 + 테스트

**Files:**
- Modify: `app.py` (대시보드 라우트 근처, 약 298~300번 라인)
- Create: `tests/test_report_route.py`

- [ ] **Step 1: 테스트 파일 작성**

`tests/test_report_route.py` 를 생성:

```python
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.config['SECRET_KEY'] = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def test_report_redirects_when_not_logged_in(client):
    resp = client.get('/report')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_report_renders_when_logged_in(client):
    with client.session_transaction() as sess:
        sess['user'] = {'username': 'testuser', 'display_name': 'Test', 'role': 'viewer'}
    resp = client.get('/report')
    assert resp.status_code == 200
    assert '월간 재무 성과 리포트'.encode() in resp.data
```

- [ ] **Step 2: 테스트 실행 — 실패 확인 (라우트 없으므로 404 예상)**

```bash
cd "C:/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
python -m pytest tests/test_report_route.py -v
```

Expected: FAIL — `assert 404 == 302` 또는 ImportError

- [ ] **Step 3: `app.py`에 라우트 추가**

`app.py` 의 대시보드 라우트 바로 아래(약 300번 라인)에 추가:

```python
@app.route('/report')
@login_required
def report():
    return render_template('report.html', user=session['user'])
```

- [ ] **Step 4: 빈 템플릿 생성 (테스트 통과용 최소)**

`templates/report.html` 생성:

```html
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>월간 재무 성과 리포트</title></head>
<body>월간 재무 성과 리포트</body>
</html>
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
python -m pytest tests/test_report_route.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 6: 커밋**

```bash
git add app.py templates/report.html tests/test_report_route.py
git commit -m "feat: add /report route with login guard and minimal template"
```

---

## Task 2: 리포트 HTML 뼈대 — CSS + 레이아웃 구조

**Files:**
- Modify: `templates/report.html` (전체 재작성)

- [ ] **Step 1: 전체 HTML 뼈대 작성**

`templates/report.html` 을 아래로 교체:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>월간 재무 성과 리포트 — FI Dashboard</title>
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Pretendard Variable','Pretendard','Segoe UI',sans-serif;background:#f3f4f6;color:#111827;min-height:100vh;padding:24px 16px}

/* ── Wrap ── */
.report-wrap{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}

/* ── Header ── */
.report-header{padding:22px 28px 16px;border-bottom:2px solid #111827;display:flex;justify-content:space-between;align-items:flex-end;gap:16px}
.report-title-group{}
.report-title{font-size:18px;font-weight:800;letter-spacing:-.3px}
.report-sub{font-size:11px;color:#6b7280;margin-top:3px;letter-spacing:.2px}
.report-controls{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.month-row{display:flex;align-items:center;gap:8px}
.month-label{font-size:10px;color:#6b7280}
#monthSelect{font-size:12px;font-family:inherit;border:1px solid #d1d5db;border-radius:4px;padding:5px 10px;color:#374151;background:#f9fafb;cursor:pointer;font-weight:600}
#monthSelect:focus{outline:2px solid #374151;outline-offset:1px}
.report-generated{font-size:10px;color:#9ca3af}

/* ── Body ── */
.report-body{padding:22px 28px}

/* ── Section label ── */
.section-label{font-size:10px;font-weight:700;color:#6b7280;letter-spacing:1px;text-transform:uppercase;margin-bottom:12px}

/* ── KPI grid ── */
.kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:24px}
.kpi-card{border:1px solid #e5e7eb;border-radius:6px;padding:14px 10px;text-align:center;position:relative;overflow:hidden}
.kpi-card-name{font-size:10px;color:#6b7280;margin-bottom:8px}
.kpi-card-value{font-size:18px;font-weight:800;color:#111827;letter-spacing:-.5px}
.kpi-card-diff{font-size:12px;font-weight:700;margin-top:5px}
.kpi-card-prev{font-size:9px;color:#9ca3af;margin-top:3px}
.kpi-card-bar{position:absolute;top:0;left:0;right:0;height:2px}

/* ── Divider ── */
.divider{border:none;border-top:1px solid #f3f4f6;margin:0 0 22px}

/* ── 2x2 Analysis grid ── */
.analysis-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.analysis-card{border:1px solid #e5e7eb;border-radius:6px;overflow:hidden}
.analysis-card-header{padding:11px 14px;border-bottom:1px solid #f3f4f6;display:flex;justify-content:space-between;align-items:center;background:#fafafa}
.analysis-card-title{font-size:11px;font-weight:700;color:#374151}
.analysis-card-hint{font-size:9px;color:#9ca3af}

/* ── Tables ── */
table{width:100%;border-collapse:collapse;font-size:11px}
thead th{padding:8px 10px;text-align:right;color:#6b7280;font-weight:600;font-size:10px;background:#f9fafb;border-bottom:1px solid #e5e7eb}
thead th:first-child{text-align:left}
tbody td{padding:8px 10px;text-align:right;border-bottom:1px solid #f9fafb;color:#374151}
tbody td:first-child{text-align:left;font-weight:600;color:#111827}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#fafafa}

/* ── Rank badge ── */
.rank{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;border-radius:3px;font-size:9px;font-weight:700;margin-right:4px;vertical-align:middle;flex-shrink:0}
.rank-1{background:#111827;color:#fff}
.rank-2{background:#374151;color:#fff}
.rank-3{background:#6b7280;color:#fff}
.rank-n{background:#f3f4f6;color:#9ca3af}

/* ── Mini bar ── */
.bar-cell{display:flex;align-items:center;gap:5px;justify-content:flex-end}
.bar-bg{width:60px;height:5px;background:#f3f4f6;border-radius:3px;overflow:hidden;flex-shrink:0}
.bar-fill{height:100%;background:#374151;border-radius:3px}
.bar-pct{font-size:9px;color:#6b7280;min-width:28px;text-align:right}

/* ── Up / Down colors ── */
.up{color:#16a34a}
.dn{color:#dc2626}
.neu{color:#6b7280}

/* ── Loading skeleton ── */
.skeleton{background:linear-gradient(90deg,#f3f4f6 25%,#e9ebee 50%,#f3f4f6 75%);background-size:200% 100%;animation:shimmer 1.2s infinite;border-radius:4px;display:inline-block}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.skeleton-row td{padding:8px 10px}
.skeleton-cell{height:12px;width:80%}

/* ── Error state ── */
.section-error{padding:16px;text-align:center;color:#9ca3af;font-size:11px}

/* ── B2B/B2C sub-table ── */
.sub-table-wrap{border-top:1px solid #f3f4f6}
.sub-table-label{padding:8px 14px 4px;font-size:9px;color:#9ca3af;font-weight:600;letter-spacing:.5px}

/* ── Footer ── */
.report-footer{padding:12px 28px;border-top:1px solid #f3f4f6;display:flex;justify-content:space-between;align-items:center;background:#fafafa}
.footer-note{font-size:10px;color:#9ca3af}
.footer-brand{font-size:11px;font-weight:700;color:#d1d5db;letter-spacing:.5px}

/* ── Back link ── */
.back-link{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#6b7280;text-decoration:none;margin-bottom:16px;font-weight:500}
.back-link:hover{color:#111827}
</style>
</head>
<body>

<a href="/dashboard" class="back-link">← 대시보드로 돌아가기</a>

<div class="report-wrap">

  <!-- ── HEADER ── -->
  <div class="report-header">
    <div class="report-title-group">
      <div class="report-title">월간 재무 성과 리포트</div>
      <div class="report-sub">Financial Intelligence Monthly Scorecard &nbsp;·&nbsp; 전월 대비</div>
    </div>
    <div class="report-controls">
      <div class="month-row">
        <span class="month-label">기준 월</span>
        <select id="monthSelect"><option>로딩 중...</option></select>
      </div>
      <div class="report-generated" id="generatedAt"></div>
    </div>
  </div>

  <!-- ── BODY ── -->
  <div class="report-body">

    <!-- KPI -->
    <div class="section-label">핵심 지표 (전월 대비)</div>
    <div class="kpi-grid" id="kpiGrid">
      <!-- JS로 렌더링 -->
    </div>

    <hr class="divider">

    <!-- 2x2 Grid -->
    <div class="section-label">분석 섹션</div>
    <div class="analysis-grid">

      <!-- 조직별 -->
      <div class="analysis-card">
        <div class="analysis-card-header">
          <span class="analysis-card-title">조직별 (Department)</span>
          <span class="analysis-card-hint">매출 기준</span>
        </div>
        <div id="deptBody"></div>
      </div>

      <!-- 판매유형 -->
      <div class="analysis-card">
        <div class="analysis-card-header">
          <span class="analysis-card-title">판매유형 (B2B / B2C)</span>
          <span class="analysis-card-hint">매출 기준</span>
        </div>
        <div id="salesTypeBody"></div>
      </div>

      <!-- 제품라인 -->
      <div class="analysis-card">
        <div class="analysis-card-header">
          <span class="analysis-card-title">제품라인 (Line)</span>
          <span class="analysis-card-hint">매출 기준</span>
        </div>
        <div id="lineBody"></div>
      </div>

      <!-- 국가별 -->
      <div class="analysis-card">
        <div class="analysis-card-header">
          <span class="analysis-card-title">국가별 (Country)</span>
          <span class="analysis-card-hint">매출 기준 Top 10</span>
        </div>
        <div id="countryBody"></div>
      </div>

    </div>
  </div>

  <!-- ── FOOTER ── -->
  <div class="report-footer">
    <div class="footer-note">단위: 원(₩) &nbsp;·&nbsp; 출처: BigQuery FI 데이터</div>
    <div class="footer-brand">FI DASHBOARD</div>
  </div>

</div>

<script>
// ── 유틸 함수 ────────────────────────────────────────────
function getPrevMonth(ym) {
  const [y, m] = ym.split('-').map(Number);
  if (m === 1) return `${y - 1}-12`;
  return `${y}-${String(m - 1).padStart(2, '0')}`;
}

function fmtAmt(v) {
  if (v == null || isNaN(v)) return '—';
  const n = Math.round(v);
  if (Math.abs(n) >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(0) + 'M';
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(0) + 'K';
  return n.toLocaleString();
}

function fmtPct(v) {
  if (v == null || isNaN(v)) return '—';
  return v.toFixed(1) + '%';
}

function diffClass(v, invert = false) {
  if (v == null || isNaN(v) || v === 0) return 'neu';
  return (v > 0) === !invert ? 'up' : 'dn';
}

function fmtDiff(curr, prev, isPp = false, invert = false) {
  if (curr == null || prev == null || prev === 0) return { text: '—', cls: 'neu' };
  if (isPp) {
    const diff = curr - prev;
    const sign = diff > 0 ? '▲' : (diff < 0 ? '▼' : '');
    return { text: `${sign} ${Math.abs(diff).toFixed(1)}pp`, cls: diffClass(diff, invert) };
  }
  const pct = ((curr - prev) / Math.abs(prev)) * 100;
  const sign = pct > 0 ? '▲' : (pct < 0 ? '▼' : '');
  return { text: `${sign} ${Math.abs(pct).toFixed(1)}%`, cls: diffClass(pct, invert) };
}

function rankBadge(i) {
  const cls = i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : 'rank-n';
  return `<span class="rank ${cls}">${i + 1}</span>`;
}

function skeletonRows(n, cols) {
  return Array.from({length: n}, () =>
    `<tr class="skeleton-row">${Array.from({length: cols}, () =>
      `<td><span class="skeleton skeleton-cell"></span></td>`).join('')}</tr>`
  ).join('');
}

function errorHtml(msg = '데이터를 불러올 수 없습니다') {
  return `<div class="section-error">${msg}</div>`;
}

// ── 상태 ─────────────────────────────────────────────────
let currentMonth = '';
let prevMonth = '';

// ── 초기화 ───────────────────────────────────────────────
async function init() {
  // 생성일 표시
  document.getElementById('generatedAt').textContent =
    `Generated ${new Date().toISOString().slice(0,10)}`;

  // 월 목록 로드
  const filters = await fetch('/api/filters').then(r => r.json()).catch(() => null);
  const months = filters?.months ?? [];

  const sel = document.getElementById('monthSelect');
  sel.innerHTML = months.map(m => `<option value="${m}">${m}</option>`).join('');

  // URL 파라미터 우선
  const params = new URLSearchParams(location.search);
  const qm = params.get('month');
  if (qm && months.includes(qm)) sel.value = qm;
  else if (months.length) sel.value = months[months.length - 1]; // 최신 월

  sel.addEventListener('change', () => {
    const url = new URL(location.href);
    url.searchParams.set('month', sel.value);
    history.pushState({}, '', url);
    loadAll();
  });

  loadAll();
}

function loadAll() {
  const sel = document.getElementById('monthSelect');
  currentMonth = sel.value;
  prevMonth = getPrevMonth(currentMonth);
  loadKpi();
  loadDept();
  loadSalesType();
  loadLine();
  loadCountry();
}

// ── KPI ──────────────────────────────────────────────────
async function loadKpi() {
  const grid = document.getElementById('kpiGrid');
  // 로딩 placeholder
  grid.innerHTML = Array.from({length: 5}, () =>
    `<div class="kpi-card"><div class="skeleton" style="height:12px;width:60%;margin:0 auto 8px"></div>
     <div class="skeleton" style="height:20px;width:80%;margin:0 auto 5px"></div>
     <div class="skeleton" style="height:12px;width:50%;margin:0 auto"></div></div>`
  ).join('');

  const [cur, prv] = await Promise.all([
    fetch(`/api/kpi?months=${currentMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/kpi?months=${prevMonth}`).then(r => r.json()).catch(() => null),
  ]);

  if (!cur) { grid.innerHTML = errorHtml(); return; }

  const cards = [
    {
      name: '매출', val: fmtAmt(cur.sales_amount),
      diff: fmtDiff(cur.sales_amount, prv?.sales_amount),
      prev: prv ? fmtAmt(prv.sales_amount) : '—',
      invert: false,
    },
    {
      name: '매출원가', val: fmtAmt(cur.cost_of_sales),
      diff: fmtDiff(cur.cost_of_sales, prv?.cost_of_sales, false, true),
      prev: prv ? fmtAmt(prv.cost_of_sales) : '—',
    },
    {
      name: '매출총이익률', val: fmtPct(cur.gross_margin),
      diff: fmtDiff(cur.gross_margin, prv?.gross_margin, true),
      prev: prv ? fmtPct(prv.gross_margin) : '—',
      invert: false,
    },
    {
      name: '판관비', val: fmtAmt(cur.sga_expenses),
      diff: fmtDiff(cur.sga_expenses, prv?.sga_expenses, false, true),
      prev: prv ? fmtAmt(prv.sga_expenses) : '—',
    },
    {
      name: '영업이익률', val: fmtPct(cur.operating_margin),
      diff: fmtDiff(cur.operating_margin, prv?.operating_margin, true),
      prev: prv ? fmtPct(prv.operating_margin) : '—',
      invert: false,
    },
  ];

  grid.innerHTML = cards.map(c => {
    const barColor = c.diff.cls === 'up' ? '#16a34a' : c.diff.cls === 'dn' ? '#dc2626' : '#e5e7eb';
    return `<div class="kpi-card">
      <div class="kpi-card-bar" style="background:${barColor}"></div>
      <div class="kpi-card-name">${c.name}</div>
      <div class="kpi-card-value">${c.val}</div>
      <div class="kpi-card-diff ${c.diff.cls}">${c.diff.text}</div>
      <div class="kpi-card-prev">전월 ${c.prev}</div>
    </div>`;
  }).join('');
}

// ── 조직별 ────────────────────────────────────────────────
async function loadDept() {
  const el = document.getElementById('deptBody');
  el.innerHTML = `<table><thead><tr><th>조직</th><th>매출</th><th>전월比</th><th>영업이익률</th></tr></thead>
    <tbody>${skeletonRows(4, 4)}</tbody></table>`;

  const [cur, prv] = await Promise.all([
    fetch(`/api/department?months=${currentMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/department?months=${prevMonth}`).then(r => r.json()).catch(() => null),
  ]);

  if (!cur) { el.innerHTML = errorHtml(); return; }

  const prevMap = Object.fromEntries((prv ?? []).map(r => [r.Department, r]));
  const rows = cur.map((r, i) => {
    const p = prevMap[r.Department];
    const d = fmtDiff(r.sales_amount, p?.sales_amount);
    return `<tr>
      <td>${rankBadge(i)}${r.Department ?? '—'}</td>
      <td>${fmtAmt(r.sales_amount)}</td>
      <td class="${d.cls}">${d.text}</td>
      <td>${fmtPct(r.operating_margin)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table><thead><tr><th>조직</th><th>매출</th><th>전월比</th><th>영업이익률</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="4" class="section-error">데이터 없음</td></tr>'}</tbody></table>`;
}

// ── 판매유형 ──────────────────────────────────────────────
async function loadSalesType() {
  const el = document.getElementById('salesTypeBody');
  el.innerHTML = `<table><thead><tr><th>유형</th><th>매출</th><th>비중</th><th>전월比</th><th>이익률</th></tr></thead>
    <tbody>${skeletonRows(2, 5)}</tbody></table>`;

  const [cur, prv, catCur] = await Promise.all([
    fetch(`/api/sales-type?months=${currentMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/sales-type?months=${prevMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/category?months=${currentMonth}`).then(r => r.json()).catch(() => null),
  ]);

  if (!cur) { el.innerHTML = errorHtml(); return; }

  const totalAmt = cur.reduce((s, r) => s + (r.sales_amount ?? 0), 0);
  const prevMap = Object.fromEntries((prv ?? []).map(r => [r.Sales_Type, r]));

  const rows = cur.map(r => {
    const p = prevMap[r.Sales_Type];
    const d = fmtDiff(r.sales_amount, p?.sales_amount);
    const pct = totalAmt ? (r.sales_amount / totalAmt * 100) : 0;
    return `<tr>
      <td><span class="rank rank-1" style="font-size:8px">${(r.Sales_Type ?? '').slice(0,3)}</span>${r.Sales_Type ?? '—'}</td>
      <td>${fmtAmt(r.sales_amount)}</td>
      <td><div class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:${pct.toFixed(0)}%"></div></div><span class="bar-pct">${pct.toFixed(0)}%</span></div></td>
      <td class="${d.cls}">${d.text}</td>
      <td>${fmtPct(r.operating_margin)}</td>
    </tr>`;
  }).join('');

  // 카테고리 서브테이블
  let catHtml = '';
  if (catCur?.length) {
    const catRows = catCur.slice(0, 5).map((r, i) => {
      return `<tr>
        <td>${rankBadge(i)}${r.Category ?? '—'}</td>
        <td>${fmtAmt(r.sales_amount)}</td>
        <td>${fmtPct(r.gross_margin)}</td>
      </tr>`;
    }).join('');
    catHtml = `<div class="sub-table-wrap">
      <div class="sub-table-label">카테고리별</div>
      <table><thead><tr><th>카테고리</th><th>매출</th><th>총이익률</th></tr></thead>
      <tbody>${catRows}</tbody></table>
    </div>`;
  }

  el.innerHTML = `<table><thead><tr><th>유형</th><th>매출</th><th>비중</th><th>전월比</th><th>이익률</th></tr></thead>
    <tbody>${rows}</tbody></table>${catHtml}`;
}

// ── 제품라인 ──────────────────────────────────────────────
async function loadLine() {
  const el = document.getElementById('lineBody');
  el.innerHTML = `<table><thead><tr><th>라인</th><th>매출</th><th>비중</th><th>전월比</th><th>총이익률</th></tr></thead>
    <tbody>${skeletonRows(4, 5)}</tbody></table>`;

  const [cur, prv] = await Promise.all([
    fetch(`/api/line?months=${currentMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/line?months=${prevMonth}`).then(r => r.json()).catch(() => null),
  ]);

  if (!cur) { el.innerHTML = errorHtml(); return; }

  const total = cur.reduce((s, r) => s + (r.sales_amount ?? 0), 0);
  const prevMap = Object.fromEntries((prv ?? []).map(r => [r.Line, r]));

  const rows = cur.map((r, i) => {
    const p = prevMap[r.Line];
    const d = fmtDiff(r.sales_amount, p?.sales_amount);
    const pct = total ? (r.sales_amount / total * 100) : 0;
    return `<tr>
      <td>${rankBadge(i)}${r.Line ?? '—'}</td>
      <td>${fmtAmt(r.sales_amount)}</td>
      <td><div class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:${pct.toFixed(0)}%"></div></div><span class="bar-pct">${pct.toFixed(0)}%</span></div></td>
      <td class="${d.cls}">${d.text}</td>
      <td>${fmtPct(r.gross_margin)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table><thead><tr><th>라인</th><th>매출</th><th>비중</th><th>전월比</th><th>총이익률</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5" class="section-error">데이터 없음</td></tr>'}</tbody></table>`;
}

// ── 국가별 ────────────────────────────────────────────────
async function loadCountry() {
  const el = document.getElementById('countryBody');
  el.innerHTML = `<table><thead><tr><th>국가</th><th>대륙</th><th>매출</th><th>전월比</th><th>이익률</th></tr></thead>
    <tbody>${skeletonRows(5, 5)}</tbody></table>`;

  const [cur, prv] = await Promise.all([
    fetch(`/api/country?months=${currentMonth}`).then(r => r.json()).catch(() => null),
    fetch(`/api/country?months=${prevMonth}`).then(r => r.json()).catch(() => null),
  ]);

  if (!cur) { el.innerHTML = errorHtml(); return; }

  const prevMap = Object.fromEntries((prv ?? []).map(r => [r.Country, r]));
  const rows = cur.slice(0, 10).map((r, i) => {
    const p = prevMap[r.Country];
    const d = fmtDiff(r.sales_amount, p?.sales_amount);
    return `<tr>
      <td>${rankBadge(i)}${r.Country ?? '—'}</td>
      <td style="color:#9ca3af;font-weight:400">${r.Continent ?? '—'}</td>
      <td>${fmtAmt(r.sales_amount)}</td>
      <td class="${d.cls}">${d.text}</td>
      <td>${fmtPct(r.operating_margin)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table><thead><tr><th>국가</th><th>대륙</th><th>매출</th><th>전월比</th><th>이익률</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5" class="section-error">데이터 없음</td></tr>'}</tbody></table>`;
}

// ── 실행 ─────────────────────────────────────────────────
init();
</script>

</body>
</html>
```

- [ ] **Step 2: Flask 서버 실행 확인**

```bash
python app.py
```

Expected: `Running on http://127.0.0.1:5000`

- [ ] **Step 3: 브라우저에서 수동 검증**

1. `http://localhost:5000/report` 접속 (로그인 상태)
2. 확인 항목:
   - 헤더 제목 표시 ✓
   - 월 드롭다운에 월 목록 로드 ✓
   - KPI 5개 카드 렌더링 ✓
   - 2×2 그리드 4개 섹션 테이블 표시 ✓
   - 월 변경 시 데이터 갱신 ✓
   - 로딩 중 shimmer 효과 ✓
   - `http://localhost:5000/report?month=YYYY-MM` URL 파라미터 작동 ✓

- [ ] **Step 4: 테스트 재실행 — 통과 확인**

```bash
python -m pytest tests/test_report_route.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: 커밋**

```bash
git add templates/report.html
git commit -m "feat: complete monthly report template with KPI scorecard and 2x2 analysis grid"
```

---

## Task 3: 국가 API에 Continent 컬럼 확인 (선택적)

**Files:**
- Read: `app.py:557-574` (`api_country` 함수)

- [ ] **Step 1: country API 응답 확인**

브라우저에서:
```
http://localhost:5000/api/country?months=<가장_최신_월>
```

응답 JSON에 `Continent` 필드가 있는지 확인.

- [ ] **Step 2-A: Continent 있으면 → 완료, 커밋 불필요**

- [ ] **Step 2-B: Continent 없으면 → `api_country` SQL에 추가**

`app.py` 의 `api_country` 함수 SQL 수정:

```python
    sql = f"""
        SELECT
            Country,
            Continent,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Country, Continent ORDER BY sales_amount DESC
        LIMIT 30
    """
```

```bash
git add app.py
git commit -m "fix: add Continent field to country API response"
```

---

## 검증 체크리스트

전체 구현 완료 후 아래를 수동으로 확인:

- [ ] `/report` 미로그인 접근 → `/login` 리다이렉트
- [ ] 월 드롭다운 변경 → URL querystring 업데이트 + 데이터 갱신
- [ ] `?month=` 직접 입력 → 해당 월 데이터 표시
- [ ] KPI: 매출원가·판관비 상승 시 빨강 표시 (비용 역방향 색상)
- [ ] KPI: 전월 데이터 없는 경우 diff `—` 표시
- [ ] 각 섹션 로딩 중 shimmer 표시
- [ ] API 오류 시 "데이터를 불러올 수 없습니다" 표시
- [ ] 국가 테이블 Top 10만 표시
- [ ] 판매유형 섹션 하단 카테고리 서브테이블 표시
- [ ] "← 대시보드로 돌아가기" 링크 작동
