# 커스텀 분석 탭 (Tableau Builder) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "커스텀 분석" tab to dashboard.html that provides a Tableau-style pivot/chart builder with drag-and-drop shelves, 13 chart types via ECharts, and per-user multi-sheet persistence in MariaDB.

**Architecture:** Backend adds `user_views` table and 6 REST endpoints to `app_v2.py`. Frontend appends CSS + JS to `templates/dashboard.html` following existing patterns (render function returns HTML string, init function wires events, state stored in `state.tableau`).

**Tech Stack:** Python/Flask (backend), Apache ECharts CDN (charts), HTML5 Drag API (DnD), MariaDB JSON column (config storage), BigQuery (data source)

---

## File Map

| File | What changes |
|------|-------------|
| `app_v2.py` | `init_db()` + `_get_tableau_fields()` helper + 6 new routes |
| `templates/dashboard.html` | ECharts CDN, CSS block, `CATEGORY_DEFS` entry, guard updates, `state.tableau`, `renderTableauView()`, `initTableauView()`, chart/pivot renderers, sheet management |

---

## Task 1: Backend — DB Table + Helper + API Endpoints

**Files:**
- Modify: `app_v2.py`

- [ ] **Step 1: Add `user_views` table to `init_db()`**

Inside `init_db()` after the `remember_tokens` CREATE TABLE block, add:

```python
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_views (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    username    VARCHAR(100) NOT NULL,
                    name        VARCHAR(100) NOT NULL DEFAULT '시트 1',
                    config      JSON NOT NULL,
                    sort_order  INT NOT NULL DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_uv_username (username)
                )
            """)
```

- [ ] **Step 2: Add `_get_tableau_fields()` helper**

After the `run_query_cached` function definition, add:

```python
def _get_tableau_fields():
    cache_key = '__tableau_fields__'
    with _cache_lock:
        entry = _query_cache.get(cache_key)
        if entry and time.time() - entry[0] < 3600:
            return entry[1]
    client = get_bq_client()
    table = client.get_table(config.BQ_TABLE)
    dimensions, measures = [], []
    for field in table.schema:
        ftype = field.field_type.upper()
        if ftype in ('STRING', 'DATE', 'DATETIME', 'TIMESTAMP'):
            dimensions.append(field.name)
        elif ftype in ('INT64', 'INTEGER', 'FLOAT64', 'FLOAT', 'NUMERIC', 'BIGNUMERIC'):
            measures.append(field.name)
    result = (dimensions, measures)
    with _cache_lock:
        _query_cache[cache_key] = (time.time(), result)
    return result
```

- [ ] **Step 3: Add `/api/tableau/fields` endpoint**

After the `/api/clear-cache` route:

```python
@app.route('/api/tableau/fields')
@login_required
def api_tableau_fields():
    dims, meas = _get_tableau_fields()
    return jsonify({'dimensions': dims, 'measures': meas})
```

- [ ] **Step 4: Add `/api/views` CRUD endpoints**

```python
@app.route('/api/views')
@login_required
def api_views_list():
    username = session['user']['username']
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT id, name, config, sort_order FROM user_views "
                "WHERE username=%s ORDER BY sort_order ASC, id ASC",
                (username,)
            )
            rows = cur.fetchall()
        for r in rows:
            if isinstance(r['config'], str):
                r['config'] = json.loads(r['config'])
        return jsonify({'views': rows})
    finally:
        db.close()


@app.route('/api/views', methods=['POST'])
@login_required
def api_views_create():
    username = session['user']['username']
    data = request.get_json() or {}
    name = data.get('name', '시트 1')
    cfg = data.get('config', {
        'chartType': 'bar', 'mode': 'chart',
        'rows': [], 'columns': [], 'measures': [],
        'color': None, 'size': None, 'filters': {},
        'sort': 'desc', 'limit': 500
    })
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_ord "
                "FROM user_views WHERE username=%s", (username,)
            )
            next_ord = (cur.fetchone() or {}).get('next_ord', 0)
            cur.execute(
                "INSERT INTO user_views (username, name, config, sort_order) "
                "VALUES (%s,%s,%s,%s)",
                (username, name, json.dumps(cfg), next_ord)
            )
            new_id = cur.lastrowid
        db.commit()
        return jsonify({'id': new_id, 'name': name, 'config': cfg, 'sort_order': next_ord})
    finally:
        db.close()


@app.route('/api/views/<int:view_id>', methods=['PUT'])
@login_required
def api_views_update(view_id):
    username = session['user']['username']
    data = request.get_json() or {}
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT id FROM user_views WHERE id=%s AND username=%s",
                (view_id, username)
            )
            if not cur.fetchone():
                return jsonify({'error': '권한 없음'}), 403
            parts, vals = [], []
            if 'name' in data:
                parts.append('name=%s'); vals.append(data['name'])
            if 'config' in data:
                parts.append('config=%s'); vals.append(json.dumps(data['config']))
            if parts:
                vals.append(view_id)
                cur.execute(f"UPDATE user_views SET {', '.join(parts)} WHERE id=%s", vals)
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()


@app.route('/api/views/<int:view_id>', methods=['DELETE'])
@login_required
def api_views_delete(view_id):
    username = session['user']['username']
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT id FROM user_views WHERE id=%s AND username=%s",
                (view_id, username)
            )
            if not cur.fetchone():
                return jsonify({'error': '권한 없음'}), 403
            cur.execute("DELETE FROM user_views WHERE id=%s", (view_id,))
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
```

- [ ] **Step 5: Add `/api/tableau/query` endpoint**

```python
@app.route('/api/tableau/query', methods=['POST'])
@login_required
def api_tableau_query():
    data = request.get_json() or {}
    cfg = data.get('config', {})
    dims, meas_list = _get_tableau_fields()
    allowed = set(dims + meas_list)

    rows_fields = [f for f in (cfg.get('rows') or []) if f in allowed]
    cols_fields  = [f for f in (cfg.get('columns') or []) if f in allowed]
    measures     = [f for f in (cfg.get('measures') or []) if f in allowed]
    color_field  = cfg.get('color') if cfg.get('color') in allowed else None

    if not measures:
        return jsonify({'error': '측정값을 선택하세요'}), 400

    group_by = list(dict.fromkeys(
        rows_fields + cols_fields + ([color_field] if color_field else [])
    ))
    select_parts = [f'`{f}`' for f in group_by]
    for m in measures:
        select_parts.append(f'SUM(`{m}`) AS `{m}`')

    conditions, params = [], []
    for idx, (field, values) in enumerate((cfg.get('filters') or {}).items()):
        if field not in allowed or not values:
            continue
        pname = f'tf_{idx}'
        conditions.append(f'`{field}` IN UNNEST(@{pname})')
        params.append(bigquery.ArrayQueryParameter(pname, 'STRING', [str(v) for v in values]))

    where_clause = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    group_clause = ('GROUP BY ' + ', '.join(f'`{f}`' for f in group_by)) if group_by else ''
    limit = min(10000, max(1, int(cfg.get('limit', 500))))
    sort_dir = 'DESC' if cfg.get('sort', 'desc') == 'desc' else 'ASC'
    order_clause = (f'ORDER BY `{measures[0]}` {sort_dir}') if group_by and measures else ''

    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM `{config.BQ_TABLE}` "
        f"{where_clause} {group_clause} {order_clause} LIMIT {limit}"
    )
    try:
        result = run_query_cached(sql, params, ttl=300)
        out = []
        for row in result:
            r = {}
            for k, v in row.items():
                r[k] = float(v) if isinstance(v, (int, float)) else (v or '')
            out.append(r)
        return jsonify({
            'columns': group_by + measures,
            'rows': out,
            'group_by': group_by,
            'measures': measures
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 6: Write backend tests**

File: `tests/test_tableau_api.py`

```python
import pytest, json
import app_v2 as flask_app

@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c

def authed(client):
    with client.session_transaction() as s:
        s['user'] = {'username': 'testuser', 'display_name': 'T', 'role': 'viewer'}

def test_views_list_requires_login(client):
    resp = client.get('/api/views')
    assert resp.status_code == 302

def test_tableau_fields_requires_login(client):
    resp = client.get('/api/tableau/fields')
    assert resp.status_code == 302

def test_views_crud_auth_check(client):
    authed(client)
    # PUT on nonexistent id owned by other user → 403
    resp = client.put('/api/views/99999', json={'name': 'x'})
    assert resp.status_code == 403

def test_views_delete_auth_check(client):
    authed(client)
    resp = client.delete('/api/views/99999')
    assert resp.status_code == 403
```

- [ ] **Step 7: Run tests**

```
cd "C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard"
python -m pytest tests/test_tableau_api.py -v
```

Expected: 4 PASS

- [ ] **Step 8: Commit**

```bash
git add app_v2.py tests/test_tableau_api.py
git commit -m "feat: add user_views table and tableau API endpoints"
```

---

## Task 2: ECharts CDN + CSS + Tab Registration + Guard Updates

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add ECharts CDN after Chart.js script tag (line 13)**

Replace:
```html
  <script>if(typeof Chart!=='undefined'){Chart.defaults.animation.duration=320;Chart.defaults.font.family="'Pretendard Variable','Pretendard',sans-serif";if(window.ChartDataLabels){Chart.register(window.ChartDataLabels);Chart.defaults.plugins.datalabels.display=false;}}</script>
```
With:
```html
  <script>if(typeof Chart!=='undefined'){Chart.defaults.animation.duration=320;Chart.defaults.font.family="'Pretendard Variable','Pretendard',sans-serif";if(window.ChartDataLabels){Chart.register(window.ChartDataLabels);Chart.defaults.plugins.datalabels.display=false;}}</script>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
```

- [ ] **Step 2: Add CSS for Tableau Builder**

At the end of the `<style>` block (before `</style>`), append the entire CSS block from the implementation (see Step 2 code below):

```css
/* ─── Tableau Builder ─────────────────────────────────────────────── */
.tbl-wrap{display:flex;flex-direction:column;height:calc(100vh - 120px);overflow:hidden}
.tbl-toolbar{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border);background:var(--surface);flex-shrink:0;flex-wrap:wrap}
.tbl-chart-btns{display:flex;gap:3px;align-items:center}
.tbl-chart-btn{display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:5px;border:1px solid transparent;background:transparent;color:var(--text-tertiary);cursor:pointer;font-size:13px;transition:all 0.15s}
.tbl-chart-btn:hover{background:var(--surface-hover);color:var(--text);border-color:var(--border)}
.tbl-chart-btn.active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.tbl-chart-btn .ic{width:14px;height:14px;stroke-width:1.75}
.tbl-divider{width:1px;height:20px;background:var(--border);margin:0 4px}
.tbl-mode-toggle{display:flex;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.tbl-mode-btn{padding:4px 10px;font-size:11.5px;font-weight:500;background:transparent;border:none;cursor:pointer;color:var(--text-tertiary);transition:all 0.15s}
.tbl-mode-btn:hover{background:var(--surface-hover);color:var(--text)}
.tbl-mode-btn.active{background:var(--accent-soft);color:var(--accent)}
.tbl-sheet-tabs{display:flex;align-items:flex-end;gap:0;margin-left:auto;overflow-x:auto;max-width:40%}
.tbl-sheet-tab{display:flex;align-items:center;gap:5px;padding:4px 10px;font-size:11.5px;border:1px solid var(--border);border-bottom:none;border-radius:5px 5px 0 0;background:var(--surface-hover);color:var(--text-tertiary);cursor:pointer;white-space:nowrap;position:relative;top:1px}
.tbl-sheet-tab.active{background:var(--bg);color:var(--text);border-color:var(--border-strong);z-index:1}
.tbl-sheet-tab:hover:not(.active){background:var(--surface)}
.tbl-sheet-tab-name{outline:none}
.tbl-sheet-tab-del{opacity:0;font-size:12px;line-height:1;cursor:pointer;color:var(--text-tertiary)}
.tbl-sheet-tab:hover .tbl-sheet-tab-del,.tbl-sheet-tab.active .tbl-sheet-tab-del{opacity:1}
.tbl-add-sheet{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border:1px solid var(--border);border-radius:5px;background:transparent;color:var(--text-tertiary);cursor:pointer;font-size:16px;line-height:1;flex-shrink:0}
.tbl-add-sheet:hover{background:var(--surface-hover);color:var(--text)}
.tbl-save-btn{padding:4px 12px;font-size:11.5px;font-weight:600;border-radius:5px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;transition:opacity 0.15s}
.tbl-save-btn:hover{opacity:0.85}
.tbl-save-btn.saved{background:transparent;color:var(--accent)}
.tbl-body{display:flex;flex:1;min-height:0;overflow:hidden}
.tbl-fields{width:190px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;padding:8px 0;background:var(--surface)}
.tbl-fields-section{padding:4px 8px 2px}
.tbl-fields-label{font-size:10px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:var(--text-tertiary);padding:6px 4px 4px}
.tbl-field-chip{display:flex;align-items:center;gap:5px;padding:4px 8px;border-radius:4px;font-size:11.5px;cursor:grab;user-select:none;color:var(--text);transition:background 0.1s}
.tbl-field-chip:hover{background:var(--surface-hover)}
.tbl-field-chip:active{cursor:grabbing}
.tbl-field-chip .ic{width:12px;height:12px;stroke-width:2;flex-shrink:0}
.tbl-field-chip.dim .ic{color:#5b9ef9}
.tbl-field-chip.meas .ic{color:#4ecb71}
.tbl-right{display:flex;flex-direction:column;flex:1;min-width:0;overflow:hidden}
.tbl-shelves{display:flex;flex-wrap:wrap;gap:0;border-bottom:1px solid var(--border);background:var(--surface);flex-shrink:0;padding:6px 8px;gap:4px}
.tbl-shelf{display:flex;align-items:center;gap:4px;min-height:30px;min-width:160px;border:1px solid var(--border);border-radius:5px;padding:3px 6px;background:var(--bg);flex:1;transition:border-color 0.15s,background 0.15s}
.tbl-shelf.drag-over{border-color:var(--accent);background:var(--accent-soft)}
.tbl-shelf-label{font-size:10px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;color:var(--text-tertiary);white-space:nowrap;padding-right:4px;flex-shrink:0}
.tbl-shelf-chips{display:flex;flex-wrap:wrap;gap:3px;align-items:center;flex:1}
.tbl-s-chip{display:flex;align-items:center;gap:3px;padding:2px 6px;border-radius:3px;font-size:11px;background:var(--surface-hover);border:1px solid var(--border);cursor:default}
.tbl-s-chip.dim{border-color:#5b9ef955;color:#5b9ef9}
.tbl-s-chip.meas{border-color:#4ecb7155;color:#4ecb71}
.tbl-s-chip-del{cursor:pointer;opacity:0.6;font-size:11px;line-height:1}
.tbl-s-chip-del:hover{opacity:1}
.tbl-viz{flex:1;min-height:0;overflow:auto;padding:12px;position:relative}
.tbl-viz-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--text-tertiary);text-align:center;gap:8px}
.tbl-viz-empty .ic{width:40px;height:40px;stroke-width:1;opacity:0.3}
.tbl-viz-empty p{font-size:13px}
.tbl-echarts{width:100%;height:100%;min-height:300px}
.tbl-pivot-wrap{overflow:auto;height:100%}
.tbl-pivot-table{border-collapse:separate;border-spacing:0;font-size:11.5px;width:100%}
.tbl-pivot-table th{background:var(--surface);border:1px solid var(--border);padding:5px 8px;font-weight:600;text-align:left;white-space:nowrap;position:sticky;top:0;z-index:1}
.tbl-pivot-table td{border:1px solid var(--border);padding:4px 8px;white-space:nowrap}
.tbl-pivot-table td.num{text-align:right;font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
.tbl-pivot-table tr:hover td{background:var(--surface-hover)}
.tbl-pivot-table .total-row td{background:var(--surface);font-weight:600}
.tbl-filter-popover{position:absolute;z-index:200;background:var(--surface);border:1px solid var(--border-strong);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);min-width:200px;max-width:280px;padding:8px}
.tbl-filter-list{max-height:200px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;margin-top:6px}
.tbl-filter-item{display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:3px;font-size:12px;cursor:pointer}
.tbl-filter-item:hover{background:var(--surface-hover)}
```

- [ ] **Step 3: Add 'tableau' to `CATEGORY_DEFS` (line ~2524)**

Find:
```js
  { id:'rawdata',  label:'원시데이터', icon:'table-2',        path:[]                          },
```
Replace with:
```js
  { id:'rawdata',  label:'원시데이터', icon:'table-2',        path:[]                          },
  { id:'tableau',  label:'커스텀 분석', icon:'layout-dashboard', path:[]                       },
```

- [ ] **Step 4: Update guard checks — add `'tableau'` alongside `'rawdata'`**

Update these 4 locations:

**renderHeroShell (line ~3476):**
```js
  if (state.category === 'rawdata') { shell.style.display = 'none'; return; }
```
→
```js
  if (state.category === 'rawdata' || state.category === 'tableau') { shell.style.display = 'none'; return; }
```

**renderWaterfallShell (line ~3662):**
```js
  if (state.category === 'rawdata' || state.category === 'org' ...
```
→ add `|| state.category === 'tableau'` to same condition

**renderCatFilters (line ~5588):**
```js
  if (cat === 'sales' || cat === 'rawdata' || cat === 'overview') { wrap.innerHTML = ''; return; }
```
→
```js
  if (cat === 'sales' || cat === 'rawdata' || cat === 'overview' || cat === 'tableau') { wrap.innerHTML = ''; return; }
```

**renderCrumb (line ~3306):**
```js
  if (state.category === 'rawdata' || state.category === 'overview') { wrap.innerHTML = ''; return; }
```
→
```js
  if (state.category === 'rawdata' || state.category === 'overview' || state.category === 'tableau') { wrap.innerHTML = ''; return; }
```

- [ ] **Step 5: Add 'tableau' to `_titleMap` (line ~5852)**

```js
const _titleMap = { ..., rawdata:'원시 데이터', tableau:'커스텀 분석' };
```

- [ ] **Step 6: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: register tableau tab, add ECharts CDN, CSS, guards"
```

---

## Task 3: State + renderTableauView Shell + renderMainView Hook

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `tableau` state to the `state` object (line ~2527)**

Inside the `state = { ... }` block, add after `rawFilter`:
```js
  tableau: {
    views: [],
    currentId: null,
    fields: { dimensions: [], measures: [] },
    config: {
      chartType: 'bar', mode: 'chart',
      rows: [], columns: [], measures: [],
      color: null, size: null,
      filters: {}, sort: 'desc', limit: 500
    },
    queryResult: null,
    loading: false,
    saveTimer: null,
    echartsInst: null,
  },
```

- [ ] **Step 2: Add `renderTableauView()` function**

After `renderRawDataView` / `initRawDataView` block, add the new section:

```js
/* ═════════════════════════════════════════════════════════════════════
   TABLEAU BUILDER VIEW
   ═════════════════════════════════════════════════════════════════════ */
function renderTableauView(){
  return `<div class="tbl-wrap" id="tblWrap">
    <div class="tbl-toolbar" id="tblToolbar">
      <div class="tbl-chart-btns" id="tblChartBtns">
        ${[
          ['bar','bar-chart-2','막대'],['stacked_bar','layers','누적막대'],
          ['line','trending-up','선'],['area','activity','영역'],
          ['stacked_area','align-justify','누적영역'],
          ['pie','pie-chart','원형'],['donut','disc','도넛'],
          ['waterfall','bar-chart','폭포수'],
          ['scatter','circle','산점도'],['bubble','git-commit','버블'],
          ['heatmap','grid','히트맵'],['treemap','layout','트리맵'],
          ['combo','bar-chart-4','콤보'],
        ].map(([t,ic,lb])=>`<button class="tbl-chart-btn${state.tableau.config.chartType===t?' active':''}" data-type="${t}" title="${lb}"><i data-lucide="${ic}" class="ic"></i></button>`).join('')}
      </div>
      <div class="tbl-divider"></div>
      <div class="tbl-mode-toggle">
        <button class="tbl-mode-btn${state.tableau.config.mode==='chart'?' active':''}" data-mode="chart">차트</button>
        <button class="tbl-mode-btn${state.tableau.config.mode==='pivot'?' active':''}" data-mode="pivot">피벗</button>
      </div>
      <div class="tbl-divider"></div>
      <div class="tbl-sheet-tabs" id="tblSheetTabs"></div>
      <button class="tbl-add-sheet" id="tblAddSheet" title="새 시트">+</button>
      <button class="tbl-save-btn saved" id="tblSaveBtn">저장됨</button>
    </div>
    <div class="tbl-body">
      <div class="tbl-fields" id="tblFields">
        <div class="tbl-fields-label" style="padding:8px 12px 4px">필드 목록 불러오는 중…</div>
      </div>
      <div class="tbl-right">
        <div class="tbl-shelves" id="tblShelves">
          ${['rows','columns','measures','color','size','filters'].map(s=>`
          <div class="tbl-shelf" id="tblShelf_${s}" data-shelf="${s}">
            <span class="tbl-shelf-label">${{rows:'행',columns:'열',measures:'측정값',color:'색상',size:'크기',filters:'필터'}[s]}</span>
            <div class="tbl-shelf-chips" id="tblChips_${s}"></div>
          </div>`).join('')}
        </div>
        <div class="tbl-viz" id="tblViz">
          <div class="tbl-viz-empty">
            <i data-lucide="layout-dashboard" class="ic"></i>
            <p>필드를 드래그해서 행·열·측정값에 놓으세요</p>
          </div>
        </div>
      </div>
    </div>
  </div>`;
}
```

- [ ] **Step 3: Hook into `renderMainView()`**

In `renderMainView()`, before the rawdata check, add:

```js
  if (state.category === 'tableau') {
    wrap.innerHTML = renderTableauView();
    if (window.lucide) lucide.createIcons();
    initTableauView();
    return;
  }
```

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: add tableau view shell and state"
```

---

## Task 4: Dynamic Field Panel + Drag-and-Drop Shelves

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `initTableauView()` and supporting functions**

After `renderTableauView()`, add:

```js
async function initTableauView(){
  await tblLoadFields();
  await tblLoadViews();
  tblInitDnD();
  tblRenderShelfChips();
}

async function tblLoadFields(){
  try {
    const r = await fetch('/api/tableau/fields').then(r=>r.json());
    state.tableau.fields = r;
    tblRenderFields();
  } catch(e){ console.error('fields load error', e); }
}

function tblRenderFields(){
  const panel = $('#tblFields');
  if (!panel) return;
  const { dimensions, measures } = state.tableau.fields;
  const chip = (f, type) =>
    `<div class="tbl-field-chip ${type}" draggable="true" data-field="${f}" data-ftype="${type}">
       <i data-lucide="${type==='dim'?'tag':'hash'}" class="ic"></i>${f}
     </div>`;
  panel.innerHTML = `
    <div class="tbl-fields-section">
      <div class="tbl-fields-label">차원 (Dimension)</div>
      ${dimensions.map(f=>chip(f,'dim')).join('')}
    </div>
    <div class="tbl-fields-section" style="margin-top:8px">
      <div class="tbl-fields-label">측정값 (Measure)</div>
      ${measures.map(f=>chip(f,'meas')).join('')}
    </div>`;
  if (window.lucide) lucide.createIcons();
  tblInitDnD();
}

function tblInitDnD(){
  // Field chips → draggable
  $$('#tblFields .tbl-field-chip').forEach(chip => {
    chip.ondragstart = e => {
      state.tableau.dragField = { name: chip.dataset.field, ftype: chip.dataset.ftype };
      e.dataTransfer.effectAllowed = 'copy';
    };
    chip.ondragend = () => { state.tableau.dragField = null; };
  });

  // Shelves → drop zones
  $$('.tbl-shelf').forEach(shelf => {
    const shelfId = shelf.dataset.shelf;
    shelf.ondragover = e => { e.preventDefault(); shelf.classList.add('drag-over'); };
    shelf.ondragleave = () => shelf.classList.remove('drag-over');
    shelf.ondrop = e => {
      e.preventDefault();
      shelf.classList.remove('drag-over');
      const f = state.tableau.dragField;
      if (!f) return;
      tblAddToShelf(shelfId, f.name);
    };
  });
}

function tblAddToShelf(shelf, fieldName){
  const cfg = state.tableau.config;
  // Single-value shelves
  if (shelf === 'color' || shelf === 'size') {
    cfg[shelf] = fieldName;
  } else if (shelf === 'filters') {
    if (!cfg.filters[fieldName]) cfg.filters[fieldName] = [];
    tblShowFilterPopover(fieldName);
    return;
  } else {
    // Array shelves: rows, columns, measures
    if (!cfg[shelf]) cfg[shelf] = [];
    if (!cfg[shelf].includes(fieldName)) cfg[shelf].push(fieldName);
  }
  tblRenderShelfChips();
  tblMarkUnsaved();
  tblAutoSave();
  tblExecuteQuery();
}

function tblRemoveFromShelf(shelf, fieldName){
  const cfg = state.tableau.config;
  if (shelf === 'color' || shelf === 'size') {
    cfg[shelf] = null;
  } else if (shelf === 'filters') {
    delete cfg.filters[fieldName];
  } else {
    cfg[shelf] = (cfg[shelf] || []).filter(f => f !== fieldName);
  }
  tblRenderShelfChips();
  tblMarkUnsaved();
  tblAutoSave();
  tblExecuteQuery();
}

function tblRenderShelfChips(){
  const cfg = state.tableau.config;
  const { dimensions } = state.tableau.fields;
  const isDim = f => dimensions.includes(f);

  const renderChips = (shelf, items) => {
    const el = $(`#tblChips_${shelf}`);
    if (!el) return;
    el.innerHTML = items.map(f =>
      `<span class="tbl-s-chip ${isDim(f)?'dim':'meas'}" data-shelf="${shelf}" data-field="${f}">
         ${f}<span class="tbl-s-chip-del" data-shelf="${shelf}" data-field="${f}">×</span>
       </span>`
    ).join('');
    el.querySelectorAll('.tbl-s-chip-del').forEach(btn => {
      btn.onclick = () => tblRemoveFromShelf(btn.dataset.shelf, btn.dataset.field);
    });
  };

  renderChips('rows',    cfg.rows || []);
  renderChips('columns', cfg.columns || []);
  renderChips('measures',cfg.measures || []);
  renderChips('color',   cfg.color ? [cfg.color] : []);
  renderChips('size',    cfg.size  ? [cfg.size]  : []);
  renderChips('filters', Object.keys(cfg.filters || {}));
}
```

- [ ] **Step 2: Wire chart type buttons and mode toggle in initTableauView**

Append to `initTableauView()`:

```js
  // Chart type buttons
  $$('#tblChartBtns .tbl-chart-btn').forEach(btn => {
    btn.onclick = () => {
      state.tableau.config.chartType = btn.dataset.type;
      $$('#tblChartBtns .tbl-chart-btn').forEach(b => b.classList.toggle('active', b===btn));
      tblMarkUnsaved(); tblAutoSave(); tblExecuteQuery();
    };
  });
  // Mode toggle
  $$('.tbl-mode-btn').forEach(btn => {
    btn.onclick = () => {
      state.tableau.config.mode = btn.dataset.mode;
      $$('.tbl-mode-btn').forEach(b => b.classList.toggle('active', b===btn));
      tblMarkUnsaved(); tblAutoSave(); tblRenderViz();
    };
  });
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: field panel, drag-and-drop shelves"
```

---

## Task 5: Query Execution + ECharts Chart Rendering (13 types)

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `tblExecuteQuery()` and `tblRenderViz()`**

```js
async function tblExecuteQuery(){
  const cfg = state.tableau.config;
  const hasData = (cfg.rows.length || cfg.columns.length || cfg.measures.length);
  if (!hasData) { tblRenderViz(); return; }

  state.tableau.loading = true;
  tblSetVizLoading(true);
  try {
    const r = await fetch('/api/tableau/query', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ config: cfg })
    }).then(r=>r.json());
    if (r.error) { tblSetVizError(r.error); return; }
    state.tableau.queryResult = r;
    tblRenderViz();
  } catch(e) {
    tblSetVizError('쿼리 실패: ' + e);
  } finally {
    state.tableau.loading = false;
    tblSetVizLoading(false);
  }
}

function tblSetVizLoading(on){
  const viz = $('#tblViz');
  if (!viz) return;
  if (on) viz.innerHTML = '<div class="tbl-viz-empty"><div class="spinner"></div><p>쿼리 실행 중…</p></div>';
}

function tblSetVizError(msg){
  const viz = $('#tblViz');
  if (viz) viz.innerHTML = `<div class="tbl-viz-empty"><i data-lucide="alert-circle" class="ic"></i><p style="color:var(--danger)">${msg}</p></div>`;
  if (window.lucide) lucide.createIcons();
}

function tblRenderViz(){
  const viz = $('#tblViz');
  if (!viz) return;
  const cfg = state.tableau.config;
  const result = state.tableau.queryResult;
  const empty = !result || !result.rows || !result.rows.length;

  if (empty) {
    viz.innerHTML = '<div class="tbl-viz-empty"><i data-lucide="layout-dashboard" class="ic"></i><p>필드를 드래그해서 행·열·측정값에 놓으세요</p></div>';
    if (window.lucide) lucide.createIcons();
    return;
  }
  if (cfg.mode === 'pivot') { tblRenderPivot(viz, result, cfg); return; }
  tblRenderEChart(viz, result, cfg);
}
```

- [ ] **Step 2: Add `tblRenderEChart()` with all 13 chart types**

```js
function tblRenderEChart(viz, result, cfg){
  viz.innerHTML = '<div class="tbl-echarts" id="tblEChartsEl"></div>';
  const el = $('#tblEChartsEl');
  if (!el || !window.echarts) { viz.innerHTML = '<div class="tbl-viz-empty"><p>ECharts 로딩 중…</p></div>'; return; }

  if (state.tableau.echartsInst) { state.tableau.echartsInst.dispose(); }
  const isDark = document.documentElement.classList.contains('theme-dark');
  const inst = echarts.init(el, isDark ? 'dark' : null, { renderer: 'canvas' });
  state.tableau.echartsInst = inst;

  const rows = result.rows;
  const measures = result.measures || [];
  const groupBy = result.group_by || [];
  const labelField = groupBy[0] || null;
  const colorField = cfg.color && groupBy.includes(cfg.color) ? cfg.color : null;
  const type = cfg.chartType;

  const palette = ['#5b9ef9','#4ecb71','#f7c948','#f9784b','#a78bfa','#34d399','#f472b6','#60a5fa','#fb923c','#a3e635'];

  let option = {};

  // Helper: get unique label values
  const labels = [...new Set(rows.map(r => String(r[labelField] ?? '')))];
  const meas = measures[0] || '';
  const meas2 = measures[1] || meas;

  if (type === 'pie' || type === 'donut') {
    const pieData = rows.map(r => ({ name: String(r[labelField]||''), value: r[meas]||0 }));
    option = {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { color: isDark?'#ccc':'#333' } },
      series: [{ type:'pie', radius: type==='donut'?['45%','70%']:'60%', data: pieData, emphasis:{itemStyle:{shadowBlur:10,shadowOffsetX:0,shadowColor:'rgba(0,0,0,0.5)'}} }]
    };
  } else if (type === 'scatter' || type === 'bubble') {
    const xField = measures[0]||''; const yField = measures[1]||measures[0]||''; const sField = measures[2]||measures[0]||'';
    const maxS = Math.max(...rows.map(r=>r[sField]||0));
    const scatterData = rows.map(r => [r[xField]||0, r[yField]||0, r[sField]||0, String(r[labelField]||'')]);
    option = {
      tooltip: { trigger:'item', formatter: p => `${p.data[3]}<br/>${xField}: ${fmtNum(p.data[0])}<br/>${yField}: ${fmtNum(p.data[1])}` },
      xAxis: { type:'value', name:xField, axisLabel:{color:isDark?'#aaa':'#666'} },
      yAxis: { type:'value', name:yField, axisLabel:{color:isDark?'#aaa':'#666'} },
      series: [{ type:'scatter', data: scatterData,
        symbolSize: type==='bubble' ? d => Math.max(8, Math.sqrt(d[2]/maxS)*60) : 10,
        itemStyle:{ color: p => palette[p.dataIndex % palette.length] }
      }]
    };
  } else if (type === 'heatmap') {
    const xField = groupBy[0]||''; const yField = groupBy[1]||groupBy[0]||'';
    const xs = [...new Set(rows.map(r=>String(r[xField]||'')))];
    const ys = [...new Set(rows.map(r=>String(r[yField]||'')))];
    const hData = rows.map(r=>[xs.indexOf(String(r[xField]||'')), ys.indexOf(String(r[yField]||'')), r[meas]||0]);
    const maxV = Math.max(...hData.map(d=>d[2]));
    option = {
      tooltip: { position:'top', formatter: p=>`${xs[p.data[0]]} / ${ys[p.data[1]]}<br/>${meas}: ${fmtNum(p.data[2])}` },
      xAxis: { type:'category', data:xs, axisLabel:{rotate:45,color:isDark?'#aaa':'#666'} },
      yAxis: { type:'category', data:ys, axisLabel:{color:isDark?'#aaa':'#666'} },
      visualMap: { min:0, max:maxV, calculable:true, orient:'horizontal', bottom:5, left:'center', inRange:{color:['#f0f0f0','#5b9ef9','#1a3a6e']} },
      series: [{ type:'heatmap', data:hData, label:{show:true,formatter:p=>fmtNum(p.data[2])}, emphasis:{itemStyle:{shadowBlur:10}} }]
    };
  } else if (type === 'treemap') {
    const tmData = rows.map(r=>({ name: String(r[labelField]||''), value: r[meas]||0 }));
    option = {
      tooltip: { formatter: p=>`${p.name}: ${fmtNum(p.value)}` },
      series: [{ type:'treemap', data:tmData, label:{show:true,formatter:'{b}\n{c}'}, levels:[{itemStyle:{borderWidth:2}}] }]
    };
  } else if (type === 'waterfall') {
    const wfData = [0];
    const wfHelper = [0];
    rows.forEach((r,i) => {
      const v = r[meas]||0;
      wfHelper.push(i===0?0:Math.min(wfHelper[i]+(rows[i-1][meas]||0), wfHelper[i]+(rows[i-1][meas]||0)));
      wfData.push(v);
    });
    const helperArr = rows.map((_,i)=>i===0?0:rows.slice(0,i).reduce((s,r)=>s+(r[meas]||0),0));
    option = {
      tooltip: { trigger:'axis' },
      xAxis: { type:'category', data:rows.map(r=>String(r[labelField]||'')), axisLabel:{color:isDark?'#aaa':'#666'} },
      yAxis: { type:'value', axisLabel:{color:isDark?'#aaa':'#666',formatter:v=>fmtNum(v)} },
      series: [
        { type:'bar', stack:'wf', data:helperArr.map(v=>({value:v,itemStyle:{opacity:0}})), tooltip:{show:false} },
        { type:'bar', stack:'wf', data:rows.map(r=>r[meas]||0),
          itemStyle:{ color: p => (rows[p.dataIndex][meas]||0)>=0 ? '#4ecb71':'#f9784b' },
          label:{ show:true, position:'top', formatter:p=>fmtNum(p.value) }
        }
      ]
    };
  } else {
    // bar, stacked_bar, line, area, stacked_area, combo
    const isLine = type==='line'||type==='area'||type==='stacked_area';
    const isStacked = type==='stacked_bar'||type==='stacked_area';
    const isArea = type==='area'||type==='stacked_area';
    const isCombo = type==='combo';

    // group by color field if set
    const colorGroups = colorField
      ? [...new Set(rows.map(r=>String(r[colorField]||'')))]
      : null;

    let series = [];
    if (colorGroups) {
      series = colorGroups.map((grp, gi) => {
        const gRows = rows.filter(r=>String(r[colorField]||'')===grp);
        const data = labels.map(lb => {
          const r = gRows.find(r=>String(r[labelField]||'')===lb);
          return r ? (r[meas]||0) : 0;
        });
        const t = isCombo && gi>0 ? 'line' : (isLine?'line':'bar');
        return { name:grp, type:t, data, stack: isStacked?'total':undefined,
          areaStyle: isArea ? {} : undefined, smooth: isLine,
          itemStyle:{ color:palette[gi%palette.length] }
        };
      });
    } else {
      measures.forEach((m, mi) => {
        const data = rows.map(r => r[m]||0);
        const t = isCombo && mi>0 ? 'line' : (isLine?'line':'bar');
        series.push({ name:m, type:t, data,
          stack: isStacked?'total':undefined,
          areaStyle: isArea ? {} : undefined, smooth: isLine,
          yAxisIndex: isCombo && mi>0 ? 1 : 0,
          itemStyle:{ color:palette[mi%palette.length] }
        });
      });
    }

    const yAxes = isCombo && measures.length>1
      ? [ {type:'value',axisLabel:{color:isDark?'#aaa':'#666',formatter:v=>fmtNum(v)}},
          {type:'value',alignTicks:true,opposite:true,axisLabel:{color:isDark?'#aaa':'#666',formatter:v=>fmtNum(v)}} ]
      : [ {type:'value',axisLabel:{color:isDark?'#aaa':'#666',formatter:v=>fmtNum(v)}} ];

    option = {
      tooltip: { trigger:'axis' },
      legend: { show: series.length>1, textStyle:{color:isDark?'#ccc':'#333'} },
      grid: { left:'3%', right:'4%', bottom:'3%', containLabel:true },
      xAxis: { type:'category', data:labels, axisLabel:{color:isDark?'#aaa':'#666',rotate:labels.length>12?30:0} },
      yAxis: yAxes,
      series
    };
  }

  // Apply theme bg
  if (isDark) {
    option.backgroundColor = '#0A0E14';
  }
  inst.setOption(option);
  window.addEventListener('resize', () => inst && inst.resize());
}

function fmtNum(v){
  if (typeof v !== 'number') return v;
  if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(1)+'B';
  if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1)+'M';
  if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(1)+'K';
  return v.toFixed(0);
}
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: ECharts rendering for 13 chart types"
```

---

## Task 6: Pivot Table Mode

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `tblRenderPivot()`**

```js
function tblRenderPivot(viz, result, cfg){
  viz.innerHTML = '<div class="tbl-pivot-wrap"><table class="tbl-pivot-table" id="tblPivotTbl"></table></div>';
  const tbl = $('#tblPivotTbl');
  if (!tbl) return;

  const rows = result.rows;
  const measures = result.measures || [];
  const groupBy = result.group_by || [];

  if (!rows.length) { viz.innerHTML = '<div class="tbl-viz-empty"><p>데이터 없음</p></div>'; return; }

  // Simple flat pivot: group-by columns + measure columns
  const allCols = [...groupBy, ...measures];

  // Header
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  allCols.forEach(col => {
    const th = document.createElement('th');
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  tbl.appendChild(thead);

  // Body
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    allCols.forEach(col => {
      const td = document.createElement('td');
      const val = row[col];
      if (measures.includes(col) && typeof val === 'number') {
        td.className = 'num';
        td.textContent = val.toLocaleString('ko-KR');
      } else {
        td.textContent = val ?? '';
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  // Total row
  if (measures.length) {
    const totalRow = document.createElement('tr');
    totalRow.className = 'total-row';
    allCols.forEach((col, i) => {
      const td = document.createElement('td');
      if (measures.includes(col)) {
        td.className = 'num';
        const total = rows.reduce((s, r) => s + (typeof r[col]==='number'?r[col]:0), 0);
        td.textContent = total.toLocaleString('ko-KR');
      } else {
        td.textContent = i === 0 ? '합계' : '';
      }
      totalRow.appendChild(td);
    });
    tbody.appendChild(totalRow);
  }

  tbl.appendChild(tbody);
}
```

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: pivot table mode"
```

---

## Task 7: Sheet Management (Load, Create, Rename, Delete, Auto-save)

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add sheet management functions**

```js
async function tblLoadViews(){
  try {
    const r = await fetch('/api/views').then(r=>r.json());
    state.tableau.views = r.views || [];
    if (!state.tableau.views.length) {
      // Create default sheet
      const newView = await tblCreateView('시트 1');
      state.tableau.views = [newView];
      state.tableau.currentId = newView.id;
      state.tableau.config = newView.config;
    } else {
      state.tableau.currentId = state.tableau.views[0].id;
      state.tableau.config = JSON.parse(JSON.stringify(state.tableau.views[0].config));
    }
    tblRenderSheetTabs();
    tblRenderShelfChips();
    tblExecuteQuery();
  } catch(e){ console.error('views load error', e); }
}

async function tblCreateView(name){
  const r = await fetch('/api/views', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ name, config: state.tableau.config })
  }).then(r=>r.json());
  return r;
}

function tblRenderSheetTabs(){
  const bar = $('#tblSheetTabs');
  if (!bar) return;
  bar.innerHTML = state.tableau.views.map(v =>
    `<div class="tbl-sheet-tab${v.id===state.tableau.currentId?' active':''}" data-id="${v.id}">
       <span class="tbl-sheet-tab-name" contenteditable="false">${v.name}</span>
       <span class="tbl-sheet-tab-del" data-id="${v.id}" title="삭제">×</span>
     </div>`
  ).join('');

  // Click to switch
  $$('#tblSheetTabs .tbl-sheet-tab').forEach(tab => {
    tab.onclick = e => {
      if (e.target.classList.contains('tbl-sheet-tab-del')) return;
      const id = parseInt(tab.dataset.id);
      if (id === state.tableau.currentId) return;
      tblSwitchView(id);
    };
    // Double-click to rename
    tab.querySelector('.tbl-sheet-tab-name').ondblclick = function(){
      this.contentEditable = 'true';
      this.focus();
      const sel = window.getSelection(), range = document.createRange();
      range.selectNodeContents(this); sel.removeAllRanges(); sel.addRange(range);
      const finish = async () => {
        this.contentEditable = 'false';
        const newName = this.textContent.trim() || '시트';
        const id = parseInt(tab.dataset.id);
        await fetch(`/api/views/${id}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:newName})});
        const v = state.tableau.views.find(v=>v.id===id);
        if (v) v.name = newName;
      };
      this.onblur = finish;
      this.onkeydown = e => { if(e.key==='Enter'){e.preventDefault();this.blur();} };
    };
  });

  // Delete
  $$('#tblSheetTabs .tbl-sheet-tab-del').forEach(btn => {
    btn.onclick = async () => {
      const id = parseInt(btn.dataset.id);
      if (state.tableau.views.length <= 1) { alert('마지막 시트는 삭제할 수 없습니다'); return; }
      if (!confirm('이 시트를 삭제할까요?')) return;
      await fetch(`/api/views/${id}`, {method:'DELETE'});
      state.tableau.views = state.tableau.views.filter(v=>v.id!==id);
      if (state.tableau.currentId === id) {
        state.tableau.currentId = state.tableau.views[0].id;
        state.tableau.config = JSON.parse(JSON.stringify(state.tableau.views[0].config));
      }
      tblRenderSheetTabs();
      tblRenderShelfChips();
      tblExecuteQuery();
    };
  });

  // Add sheet button
  const addBtn = $('#tblAddSheet');
  if (addBtn) addBtn.onclick = async () => {
    const name = `시트 ${state.tableau.views.length + 1}`;
    const emptyConfig = { chartType:'bar', mode:'chart', rows:[], columns:[], measures:[], color:null, size:null, filters:{}, sort:'desc', limit:500 };
    const newView = await fetch('/api/views', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, config: emptyConfig })
    }).then(r=>r.json());
    state.tableau.views.push(newView);
    state.tableau.currentId = newView.id;
    state.tableau.config = JSON.parse(JSON.stringify(emptyConfig));
    tblRenderSheetTabs();
    tblRenderShelfChips();
    tblRenderViz();
  };
}

function tblSwitchView(id){
  const v = state.tableau.views.find(v=>v.id===id);
  if (!v) return;
  state.tableau.currentId = id;
  // Prune fields that no longer exist in schema
  const allowed = new Set([...state.tableau.fields.dimensions, ...state.tableau.fields.measures]);
  const prune = arr => (arr||[]).filter(f=>allowed.has(f));
  const cfg = JSON.parse(JSON.stringify(v.config));
  cfg.rows    = prune(cfg.rows);
  cfg.columns = prune(cfg.columns);
  cfg.measures= prune(cfg.measures);
  if (cfg.color && !allowed.has(cfg.color)) cfg.color = null;
  if (cfg.size  && !allowed.has(cfg.size))  cfg.size  = null;
  state.tableau.config = cfg;
  tblRenderSheetTabs();
  tblRenderShelfChips();
  tblExecuteQuery();
}

function tblMarkUnsaved(){
  const btn = $('#tblSaveBtn');
  if (btn) { btn.textContent = '저장'; btn.classList.remove('saved'); }
}

function tblAutoSave(){
  clearTimeout(state.tableau.saveTimer);
  state.tableau.saveTimer = setTimeout(async () => {
    const id = state.tableau.currentId;
    if (!id) return;
    await fetch(`/api/views/${id}`, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ config: state.tableau.config })
    });
    const v = state.tableau.views.find(v=>v.id===id);
    if (v) v.config = JSON.parse(JSON.stringify(state.tableau.config));
    const btn = $('#tblSaveBtn');
    if (btn) { btn.textContent = '저장됨'; btn.classList.add('saved'); }
  }, 3000);
}
```

- [ ] **Step 2: Wire save button in initTableauView**

```js
  const saveBtn = $('#tblSaveBtn');
  if (saveBtn) saveBtn.onclick = async () => {
    const id = state.tableau.currentId;
    if (!id) return;
    await fetch(`/api/views/${id}`, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ config: state.tableau.config })
    });
    const v = state.tableau.views.find(v=>v.id===id);
    if (v) v.config = JSON.parse(JSON.stringify(state.tableau.config));
    saveBtn.textContent = '저장됨'; saveBtn.classList.add('saved');
  };
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: sheet management — load, create, rename, delete, auto-save"
```

---

## Self-Review Notes

- All 6 API endpoints secured with `@login_required` ✓
- SQL injection prevented via field whitelist in `/api/tableau/query` ✓
- Config graceful degradation on field name mismatch (tblSwitchView prune) ✓
- Auto-save debounce 3s ✓
- ECharts disposed on re-render to prevent memory leak ✓
- Dark/light theme handled in chart rendering ✓
- Single-value shelves (color, size) handled separately from array shelves ✓
- Last sheet deletion prevented ✓
