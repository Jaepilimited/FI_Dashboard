# PL View Editor (조직별 파일럿) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 조직별(org) 손익계산서 화면에서 행(계정 항목) 표시/숨김·순서 변경, 커스텀 계산식 행 추가, 섹션(전체/SK/유통) 표시·순서 편집이 가능하게 하고, 개인별로 이름 붙여 서버에 저장한 여러 "뷰"를 전환할 수 있게 만든다. 다른 사용자는 항상 하드코딩된 "기본" 화면을 본다.

**Architecture:** 기존 커스텀 분석탭이 쓰는 `user_views` 테이블을 `kind`/`screen_id` 컬럼으로 확장해 재사용한다(신규 테이블 없음). 프론트는 `renderOrgPl()`이 `state.plViewConfig.org`(선택된 뷰의 설정, `null`=기본)를 참조해 `CPL_ROW_DEFS`/섹션 목록을 파생시키는 방식으로, 기존 렌더링 코드 경로를 건드리지 않고 위에 얹는다. 드래그앤드롭은 HTML5 Drag API로 직접 구현(외부 라이브러리 없음, 기존 커스텀 분석탭과 동일 접근이나 별도 CSS 네임스페이스 `pl-edit-*`).

**Tech Stack:** Flask + PyMySQL (백엔드, `app_v2.py`), Jinja 템플릿 안의 순수 JS (`templates/dashboard_v2.html`, 프레임워크 없음), pytest (백엔드 테스트), gstack `browse` 스킬(프론트 수동 검증 — 이 프로젝트에 JS 유닛테스트 러너가 없으므로 기존 관례를 따름).

## Global Constraints

- 커스텀 계산식 행은 기존 22개 P&L metric id만 토큰으로 허용 (`sales`,`cogs`,`gross`,`op`,`direct`,`contrib`,`sgaD`,`sgaD.adv/.log/.fee/.hr/.etc`,`sgaO`+동일 5종,`sgaC`+동일 5종). `eval`/`new Function` 사용 금지 — 반드시 화이트리스트 토크나이저+파서로 평가.
- `bold:true` 8개 행(`sales`,`gross`,`sgaD`,`direct`,`sgaO`,`contrib`,`sgaC`,`op`) + `cogs`는 숨김 불가.
- 서브 행 재배치는 `sgaD`/`sgaO`/`sgaC` 각 그룹 내부(`adv`/`log`/`fee`/`hr`/`etc` 5개)로만 한정. `cogs`는 `gross`와 순서 고정.
- 다른 사용자는 항상 하드코딩된 "기본" 렌더링을 본다 — 커스텀 뷰는 본인 로그인 세션에서만 적용.
- 이 프로젝트는 라이브 운영 서버(Flask 디버그 리로더가 `app_v2.py` 저장 시 자동 재시작)이므로, 백엔드 테스트는 리로더 타이밍에 의존하지 않도록 테스트 자체에서 `init_db()`를 명시적으로 호출한다 (Task 1 참조).
- 커밋마다 `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q` 통과 확인 (기존 커스텀 분석탭 회귀 방지).

---

## File Structure

| 파일 | 책임 |
|------|------|
| `app_v2.py` | `init_db()`에 `user_views` 컬럼 확장, `/api/views` GET·POST에 `kind`/`screen` 파라미터 |
| `templates/dashboard_v2.html` | 편집 토글 버튼, 뷰 CRUD, 행/섹션 편집 패널·드래그앤드롭, 수식 파서, `renderOrgPl()` config-aware 렌더링, `pl-edit-*` CSS |
| `tests/test_pl_views_api.py` (신규) | `kind=pl` 뷰 CRUD·격리 백엔드 테스트 |

---

## Task 1: 백엔드 — `user_views`에 `kind`/`screen_id` 추가

**Files:**
- Modify: `app_v2.py:215-226` (`init_db()`)
- Modify: `app_v2.py:593-643` (`api_views_list`, `api_views_create`)
- Test: `tests/test_pl_views_api.py` (신규)

**Interfaces:**
- Produces: `GET /api/views?kind=pl&screen=<id>` → `{views:[{id,name,config,sort_order}]}` (해당 kind+screen 소유 뷰만). `kind` 생략 시 기존과 동일하게 `kind='tableau'`로 동작(하위호환).
- Produces: `POST /api/views` body `{kind?, screen?, name, config}` → `kind='pl'`이면 `screen` 필수(없으면 400).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pl_views_api.py` 신규 생성:

```python
import pytest
import app_v2 as flask_app

TEST_USER = 'testuser_pl_views'


@pytest.fixture(scope='session', autouse=True)
def _ensure_schema():
    # 라이브 리로더 재시작 타이밍에 의존하지 않도록 테스트에서 직접 스키마 보장
    flask_app.init_db()


def _cleanup():
    db = flask_app.get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM user_views WHERE username=%s", (TEST_USER,))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_test_rows():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def authed(client):
    with client.session_transaction() as s:
        s['user'] = {'username': TEST_USER, 'display_name': 'T', 'role': 'viewer'}


def test_pl_views_list_empty_for_new_screen(client):
    authed(client)
    resp = client.get('/api/views?kind=pl&screen=org')
    assert resp.status_code == 200
    assert resp.get_json()['views'] == []


def test_pl_views_create_requires_screen(client):
    authed(client)
    resp = client.post('/api/views', json={'kind': 'pl', 'name': '내 뷰', 'config': {}})
    assert resp.status_code == 400


def test_pl_views_create_and_list_roundtrip(client):
    authed(client)
    create = client.post('/api/views', json={
        'kind': 'pl', 'screen': 'org', 'name': '내 뷰',
        'config': {'rows': {'hidden': ['sgaD.fee']}}
    })
    assert create.status_code == 200
    view_id = create.get_json()['id']

    listed = client.get('/api/views?kind=pl&screen=org').get_json()['views']
    assert len(listed) == 1
    assert listed[0]['id'] == view_id
    assert listed[0]['config']['rows']['hidden'] == ['sgaD.fee']


def test_pl_views_do_not_leak_into_tableau_list(client):
    authed(client)
    client.post('/api/views', json={'kind': 'pl', 'screen': 'org', 'name': 'PL 뷰', 'config': {}})
    tableau_views = client.get('/api/views').get_json()['views']
    assert all(v['name'] != 'PL 뷰' for v in tableau_views)


def test_pl_views_scoped_by_screen(client):
    authed(client)
    client.post('/api/views', json={'kind': 'pl', 'screen': 'org', 'name': 'Org 뷰', 'config': {}})
    product_views = client.get('/api/views?kind=pl&screen=product').get_json()['views']
    assert product_views == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_pl_views_api.py -v`
Expected: `test_pl_views_list_empty_for_new_screen` 등이 `kind`/`screen_id` 컬럼이 없어 SQL 에러(500) 또는 빈 결과가 기대와 달라 실패.

- [ ] **Step 3: `init_db()`에 컬럼 추가**

`app_v2.py:215-226`을 다음으로 교체:

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
            cur.execute("ALTER TABLE user_views ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'tableau'")
            cur.execute("ALTER TABLE user_views ADD COLUMN IF NOT EXISTS screen_id VARCHAR(20) DEFAULT NULL")
```

(바로 아래 `db.commit()`은 그대로 둔다.)

- [ ] **Step 4: `/api/views` GET·POST에 kind/screen 반영**

`app_v2.py:593-611` (`api_views_list`) 교체:

```python
@app.route('/api/views')
@login_required
def api_views_list():
    username = session['user']['username']
    kind = request.args.get('kind', 'tableau').strip()
    screen = request.args.get('screen', '').strip()
    if kind == 'pl' and not screen:
        return jsonify({'error': 'screen required for kind=pl'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            if kind == 'pl':
                cur.execute(
                    "SELECT id, name, config, sort_order FROM user_views "
                    "WHERE username=%s AND kind=%s AND screen_id=%s ORDER BY sort_order ASC, id ASC",
                    (username, kind, screen)
                )
            else:
                cur.execute(
                    "SELECT id, name, config, sort_order FROM user_views "
                    "WHERE username=%s AND kind=%s ORDER BY sort_order ASC, id ASC",
                    (username, kind)
                )
            rows = cur.fetchall()
        for r in rows:
            if isinstance(r['config'], str):
                r['config'] = json.loads(r['config'])
        return jsonify({'views': rows})
    finally:
        db.close()
```

`app_v2.py:614-643` (`api_views_create`) 교체:

```python
@app.route('/api/views', methods=['POST'])
@login_required
def api_views_create():
    username = session['user']['username']
    data = request.get_json() or {}
    kind = (data.get('kind') or 'tableau').strip()
    screen = (data.get('screen') or '').strip()
    if kind == 'pl' and not screen:
        return jsonify({'error': 'screen required for kind=pl'}), 400
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
                "INSERT INTO user_views (username, name, config, sort_order, kind, screen_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (username, name, json.dumps(cfg), next_ord, kind, screen or None)
            )
            new_id = cur.lastrowid
        db.commit()
        return jsonify({'id': new_id, 'name': name, 'config': cfg, 'sort_order': next_ord})
    finally:
        db.close()
```

(`PUT`/`DELETE` 엔드포인트는 소유권을 `id`+`username`으로만 확인하므로 변경 불필요.)

- [ ] **Step 5: 테스트 통과 확인 (+ 기존 회귀 확인)**

Run: `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -v`
Expected: 전부 PASS. (파일 저장 시 라이브 리로더가 자동 재시작되지만, `_ensure_schema` 세션 픽스처가 직접 `init_db()`를 호출하므로 타이밍과 무관하게 통과해야 함)

- [ ] **Step 6: 커밋**

```bash
git add app_v2.py tests/test_pl_views_api.py
git commit -m "feat: add kind/screen_id to user_views for PL saved views"
```

---

## Task 2: 프론트 — 편집 모드 진입점 + 뷰 CRUD 셸

**Files:**
- Modify: `templates/dashboard_v2.html:2818` 부근 (`state` 객체)
- Modify: `templates/dashboard_v2.html:4897-4944` 부근 (`renderOrgPl()` 카드 헤더·본문)
- Modify: `templates/dashboard_v2.html:1510` 부근 (CSS, `pl-edit-*` 신규 — 이후 Task 3/4/5가 쓰는 클래스도 여기서 한 번에 추가)

**Interfaces:**
- Consumes: 없음 (Task 1의 `/api/views?kind=pl&screen=org` API만 사용)
- Produces: `state.plEdit.org`(bool), `state.plViews.org`(array), `state.plActiveView.org`(id|null), `state.plViewConfig.org`(object|null), `plBlankConfig()`, `plUpdateConfig(screenId, mutator)`, `renderPlEditPanel(screenId)`(문자열 반환), `wirePlEditPanel(screenId)`(빈 함수, Task 3/4/5가 내용 추가) — 이후 Task들이 그대로 사용.

- [ ] **Step 1: `state`에 PL 뷰 상태 추가**

`templates/dashboard_v2.html:2819` (`cplData: null,` 다음 줄)에 삽입:

```js
  cplData: null,   // /api/pl 실데이터 캐시: { months:[...], byNode:{name:{SK:{...},UM:{...}}} }
  plEdit: { org: false },
  plViews: { org: [] },
  plViewsLoaded: { org: false },
  plActiveView: { org: null },
  plViewConfig: { org: null },
```

- [ ] **Step 2: CSS 추가**

`templates/dashboard_v2.html:1510` (`table.pl-table{margin-bottom:4px}` 다음 줄)에 삽입:

```css
.pl-body-split{display:flex;align-items:flex-start}
.pl-body-split>.pl-table-wrap{flex:1;min-width:0}
.pl-edit-toggle-btn{background:none;border:1px solid var(--border,#3a3a5c);border-radius:6px;width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-tertiary);margin-left:6px}
.pl-edit-toggle-btn:hover{border-color:var(--border-strong);color:var(--text)}
.pl-edit-toggle-btn.active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.pl-edit-panel{width:280px;flex-shrink:0;border-left:1px solid var(--border);padding:14px;background:var(--surface-2);font-size:12px}
.pl-edit-panel-hd{display:flex;align-items:center;gap:6px;margin-bottom:10px}
.pl-edit-view-label{font-size:10px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase}
.pl-edit-view-select{flex:1;font-size:12px;padding:4px 6px;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text)}
.pl-edit-panel-actions{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px}
.pl-edit-panel-actions button{font-size:10.5px;padding:3px 8px;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text-secondary);cursor:pointer}
.pl-edit-panel-actions button:hover{border-color:var(--accent);color:var(--accent)}
.pl-edit-section-title{font-size:10.5px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;margin:12px 0 6px}
.pl-edit-row-list,.pl-edit-sub-list,.pl-edit-section-list,.pl-edit-custom-list{list-style:none;margin:0;padding:0}
.pl-edit-row-block,.pl-edit-section-row{display:flex;align-items:center;gap:6px;padding:5px 4px;border-radius:5px;cursor:grab;background:var(--surface)}
.pl-edit-row-block+.pl-edit-row-block,.pl-edit-section-row+.pl-edit-section-row{margin-top:3px}
.pl-edit-sub-list{margin-left:18px;margin-top:2px}
.pl-edit-sub-row{display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:5px;cursor:grab;font-size:11px;color:var(--text-secondary)}
.pl-edit-drag-handle{color:var(--text-tertiary);font-size:11px;cursor:grab;flex-shrink:0}
.pl-edit-row-locked-label{font-weight:700}
.pl-edit-custom-row{display:flex;align-items:center;gap:6px;padding:4px;font-size:11px}
.pl-edit-custom-row code{flex:1;background:var(--surface);padding:1px 5px;border-radius:4px;color:var(--text-tertiary);font-size:10.5px}
.pl-edit-custom-row button{border:none;background:none;color:var(--negative);cursor:pointer;font-size:13px}
.pl-edit-custom-form{margin-top:6px;display:flex;flex-direction:column;gap:5px}
.pl-edit-custom-form input{font-size:11.5px;padding:4px 6px;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text)}
.pl-edit-token-hints{display:flex;flex-wrap:wrap;gap:3px}
.pl-edit-token-chip{font-size:10px;padding:1px 6px;border-radius:10px;background:var(--surface);border:1px solid var(--border);color:var(--text-tertiary);cursor:pointer}
.pl-edit-token-chip:hover{border-color:var(--accent);color:var(--accent)}
.pl-edit-custom-error{font-size:10.5px;color:var(--negative);min-height:14px}
.pl-edit-custom-form>button{font-size:11px;padding:5px;border:1px solid var(--accent);border-radius:5px;background:var(--accent-soft);color:var(--accent);cursor:pointer}
```

- [ ] **Step 3: 뷰 CRUD 프론트 함수 + 패널 셸 추가**

`templates/dashboard_v2.html:4821` (`renderOrgPl` 함수 정의 바로 위)에 삽입:

```js
function plBlankConfig(){
  return { rows:{blockOrder:[],subOrder:{},hidden:[],custom:[]}, sections:{order:[],hidden:[],deptOverrides:{}} };
}

function plUpdateConfig(screenId, mutator){
  if (!state.plViewConfig[screenId]) state.plViewConfig[screenId] = plBlankConfig();
  mutator(state.plViewConfig[screenId]);
  renderOrgPl();
}

async function loadPlViews(screenId){
  try {
    const r = await fetch('/api/views?kind=pl&screen=' + screenId, {credentials:'same-origin'}).then(function(res){return res.json();});
    state.plViews[screenId] = r.views || [];
  } catch(e){ console.error('[plViews] load error', e); state.plViews[screenId] = []; }
}

async function togglePlEdit(screenId){
  state.plEdit[screenId] = !state.plEdit[screenId];
  if (state.plEdit[screenId] && !state.plViewsLoaded[screenId]) {
    state.plViewsLoaded[screenId] = true;
    await loadPlViews(screenId);
  }
  renderOrgPl();
}

function plSwitchView(screenId, viewId){
  state.plActiveView[screenId] = viewId;
  const v = viewId == null ? null : (state.plViews[screenId] || []).filter(function(x){ return x.id === viewId; })[0];
  state.plViewConfig[screenId] = v ? v.config : null;
  renderOrgPl();
}

async function plSaveAsNewView(screenId){
  const name = prompt('새 뷰 이름을 입력하세요');
  if (!name) return;
  const cfg = state.plViewConfig[screenId] || plBlankConfig();
  const created = await fetch('/api/views', {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin',
    body: JSON.stringify({kind:'pl', screen:screenId, name:name, config:cfg})
  }).then(function(r){ return r.json(); });
  state.plViews[screenId].push(created);
  state.plActiveView[screenId] = created.id;
  state.plViewConfig[screenId] = created.config;
  renderOrgPl();
}

async function plRenameView(screenId){
  const id = state.plActiveView[screenId];
  if (id == null) return;
  const view = (state.plViews[screenId] || []).filter(function(v){ return v.id === id; })[0];
  const name = prompt('새 이름', view ? view.name : '');
  if (!name) return;
  await fetch('/api/views/' + id, {
    method:'PUT', headers:{'Content-Type':'application/json'}, credentials:'same-origin',
    body: JSON.stringify({name:name})
  });
  if (view) view.name = name;
  renderOrgPl();
}

async function plDeleteView(screenId){
  const id = state.plActiveView[screenId];
  if (id == null) return;
  if (!confirm('이 뷰를 삭제할까요?')) return;
  await fetch('/api/views/' + id, {method:'DELETE', credentials:'same-origin'});
  state.plViews[screenId] = (state.plViews[screenId] || []).filter(function(v){ return v.id !== id; });
  state.plActiveView[screenId] = null;
  state.plViewConfig[screenId] = null;
  renderOrgPl();
}

function renderPlEditPanel(screenId){
  const views = state.plViews[screenId] || [];
  const activeId = state.plActiveView[screenId];
  let h = '<div class="pl-edit-panel">';
  h += '<div class="pl-edit-panel-hd">'
     + '<span class="pl-edit-view-label">뷰</span>'
     + '<select class="pl-edit-view-select" data-pl-view-select="' + screenId + '">'
     + '<option value=""' + (activeId == null ? ' selected' : '') + '>기본</option>'
     + views.map(function(v){ return '<option value="' + v.id + '"' + (activeId === v.id ? ' selected' : '') + '>' + escPlAttr(v.name) + '</option>'; }).join('')
     + '</select>'
     + '</div>';
  h += '<div class="pl-edit-panel-actions">'
     + '<button data-pl-view-save-as="' + screenId + '">+ 새 뷰로 저장</button>'
     + (activeId != null ? '<button data-pl-view-rename="' + screenId + '">이름변경</button><button data-pl-view-delete="' + screenId + '">삭제</button>' : '')
     + '</div>';
  h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '"></div>';
  h += '</div>';
  return h;
}

function wirePlEditPanel(screenId){
  const panel = document.querySelector('.pl-edit-panel');
  if (!panel) return;
  const sel = panel.querySelector('[data-pl-view-select="' + screenId + '"]');
  if (sel) sel.addEventListener('change', function(){ plSwitchView(screenId, sel.value ? parseInt(sel.value, 10) : null); });
  const saveAsBtn = panel.querySelector('[data-pl-view-save-as="' + screenId + '"]');
  if (saveAsBtn) saveAsBtn.addEventListener('click', function(){ plSaveAsNewView(screenId); });
  const renameBtn = panel.querySelector('[data-pl-view-rename="' + screenId + '"]');
  if (renameBtn) renameBtn.addEventListener('click', function(){ plRenameView(screenId); });
  const deleteBtn = panel.querySelector('[data-pl-view-delete="' + screenId + '"]');
  if (deleteBtn) deleteBtn.addEventListener('click', function(){ plDeleteView(screenId); });
  // Task 3/4/5가 여기에 각자의 wire*Handlers(screenId) 호출을 추가한다
}
```

- [ ] **Step 4: `renderOrgPl()` 카드 헤더에 편집 버튼 + 본문 분할 반영**

`templates/dashboard_v2.html:4909-4910`:

```js
    +'<div class="waterfall-card-unit">단위: 백만원</div></div></div>'
    +'<div class="card-body card-body-flush"><div class="pl-table-wrap">';
```

를 다음으로 교체:

```js
    +'<div class="waterfall-card-unit">단위: 백만원</div>'
    +'<button class="pl-edit-toggle-btn'+(state.plEdit.org?' active':'')+'" data-pl-edit-toggle="org" title="편집"><i data-lucide="sliders-horizontal"></i></button>'
    +'</div></div>'
    +'<div class="card-body card-body-flush"><div class="pl-body-split"><div class="pl-table-wrap">';
```

`templates/dashboard_v2.html:4944` (`html+='</div></div></div>';` — 섹션 루프 바로 뒤, `wrap.innerHTML=html` 이전)을 다음으로 교체:

```js
  html += '</div>'; // .pl-table-wrap 닫기
  if (state.plEdit.org) html += renderPlEditPanel('org');
  html += '</div></div></div>'; // .pl-body-split, .card-body, .card 닫기
```

그리고 함수 맨 앞부분(`templates/dashboard_v2.html:4825` 부근, `if(!state.cplData){...}` 다음 줄)에 뷰 최초 로드 트리거 추가:

```js
  if(!state.cplData){if(!_cplDataLoading)loadCplData();return;}
  if(!state.plViewsLoaded.org){state.plViewsLoaded.org=true;loadPlViews('org').then(renderOrgPl);return;}
```

마지막으로 함수 끝부분, 기존 `wrap.querySelectorAll('[data-cpl-period]')...` 블록 뒤(`if(window.lucide)window.lucide.createIcons();` 바로 앞)에 추가:

```js
  wrap.querySelectorAll('[data-pl-edit-toggle]').forEach(function(btn){
    btn.addEventListener('click', function(){ togglePlEdit(btn.dataset.plEditToggle); });
  });
  if (state.plEdit.org) wirePlEditPanel('org');
```

- [ ] **Step 5: 수동 검증 (browse)**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B js "!!document.querySelector('.pl-edit-panel')"
$B dialog-accept "테스트뷰"
$B js "document.querySelector('[data-pl-view-save-as=org]').click()"
sleep 1
$B js "document.querySelector('[data-pl-view-select=org]').selectedOptions[0].textContent"
$B console --errors
```

Expected: `!!document.querySelector('.pl-edit-panel')` → `true`, 드롭다운 선택 텍스트 → `테스트뷰`, 콘솔 에러 없음. (한 Bash 호출 안에서 순차 실행 — 세션 daemon이 별도 호출 간 재시작되는 이슈 회피)

- [ ] **Step 6: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: PL view editor entry point + saved-view CRUD (org pilot)"
```

---

## Task 3: 프론트 — 행 표시/숨김 + 순서 편집

**Files:**
- Modify: `templates/dashboard_v2.html` (Task 2가 만든 `renderOrgPl`/`renderPlEditPanel`/`wirePlEditPanel` 영역, `CPL_ROW_DEFS` 바로 아래)

**Interfaces:**
- Consumes: Task 2의 `plUpdateConfig`, `state.plViewConfig`, `renderPlEditPanel`, `wirePlEditPanel`
- Produces: `PL_ROW_BLOCKS`, `PL_SUB_GROUP_KEYS`, `plEffectiveRowDefs(screenId)`, `plEvalFormula(formula, M, months)`(Task 4가 실구현으로 교체할 스텁), `renderPlRowEditor(screenId)`, `wirePlRowDragHandlers(screenId)` — Task 4/5/6이 그대로 사용.

- [ ] **Step 1: 블록 모델 + 파생 행 목록 함수 추가**

`templates/dashboard_v2.html:4769` (`const CPL_ROW_DEFS = [...]` 배열이 끝나는 `];` 바로 다음 줄)에 삽입:

```js
const PL_ROW_BLOCKS = [
  { anchor:'sales',   ids:['sales'] },
  { anchor:'gross',   ids:['cogs','gross'] },
  { anchor:'sgaD',    ids:['sgaD','sgaD.adv','sgaD.log','sgaD.fee','sgaD.hr','sgaD.etc'] },
  { anchor:'direct',  ids:['direct'] },
  { anchor:'sgaO',    ids:['sgaO','sgaO.adv','sgaO.log','sgaO.fee','sgaO.hr','sgaO.etc'] },
  { anchor:'contrib', ids:['contrib'] },
  { anchor:'sgaC',    ids:['sgaC','sgaC.adv','sgaC.log','sgaC.fee','sgaC.hr','sgaC.etc'] },
  { anchor:'op',      ids:['op'] },
];
const PL_SUB_GROUP_KEYS = ['adv','log','fee','hr','etc'];

// Task 4에서 실제 수식 파서로 교체됨. 그때까지 custom 행은 항상 빈 배열이라 호출되지 않는다.
function plEvalFormula(formula, M, months){ return months.map(function(){ return 0; }); }

function plEffectiveRowDefs(screenId){
  const cfg = state.plViewConfig[screenId];
  if (!cfg) return CPL_ROW_DEFS;
  const rowById = {}; CPL_ROW_DEFS.forEach(function(r){ rowById[r.id] = r; });
  const hidden = new Set((cfg.rows && cfg.rows.hidden) || []);
  const blockOrder = (cfg.rows && cfg.rows.blockOrder) || [];
  const subOrder = (cfg.rows && cfg.rows.subOrder) || {};
  const custom = (cfg.rows && cfg.rows.custom) || [];

  const orderedAnchors = blockOrder.filter(function(a){ return PL_ROW_BLOCKS.some(function(b){ return b.anchor === a; }); });
  const remainingAnchors = PL_ROW_BLOCKS.map(function(b){ return b.anchor; }).filter(function(a){ return orderedAnchors.indexOf(a) < 0; });
  const finalAnchors = orderedAnchors.concat(remainingAnchors);

  let result = [];
  finalAnchors.forEach(function(anchor){
    const block = PL_ROW_BLOCKS.filter(function(b){ return b.anchor === anchor; })[0];
    if (anchor === 'gross') {
      result.push(rowById.cogs);
      result.push(rowById.gross);
    } else if (block.ids.length === 1) {
      result.push(rowById[anchor]);
    } else {
      result.push(rowById[anchor]);
      const order = (subOrder[anchor] && subOrder[anchor].length === 5) ? subOrder[anchor] : PL_SUB_GROUP_KEYS;
      order.forEach(function(key){
        const subId = anchor + '.' + key;
        if (!hidden.has(subId)) result.push(rowById[subId]);
      });
    }
    custom.filter(function(c){ return c.afterId === anchor; }).forEach(function(c){
      result.push({ id:c.id, label:c.label, custom:true, formula:c.formula, sub:false, pct:false });
    });
  });
  return result;
}
```

- [ ] **Step 2: `renderTable`이 `plEffectiveRowDefs`/커스텀 행을 반영하도록 수정**

`templates/dashboard_v2.html:4859-4864`:

```js
  function renderTable(M, depts, brand){
    const deptsAttr=escPlAttr((depts||[]).join(','));
    const brandKey=brand||'all';
    const allMStr=months.join(',');
    const pv=function(id,prd){return prd.monthIndices.reduce(function(a,i){return a+((cplRowValue(M,id)||[])[i]||0);},0);};
    const tv=function(id){return(cplRowValue(M,id)||[]).reduce(function(a,v){return a+v;},0);};
```

를 다음으로 교체:

```js
  function renderTable(M, depts, brand){
    const deptsAttr=escPlAttr((depts||[]).join(','));
    const brandKey=brand||'all';
    const allMStr=months.join(',');
    const rowSeries=function(x){
      const row = (typeof x==='string') ? {id:x} : x;
      if (row.custom) return plEvalFormula(row.formula, M, months);
      return cplRowValue(M, row.id) || [];
    };
    const pv=function(x,prd){const s=rowSeries(x);return prd.monthIndices.reduce(function(a,i){return a+(s[i]||0);},0);};
    const tv=function(x){return rowSeries(x).reduce(function(a,v){return a+v;},0);};
```

`templates/dashboard_v2.html:4870-4893`(`CPL_ROW_DEFS.forEach(function(row){`부터 `return t+'</tbody></table>';` 바로 위 `});`까지) 전체를 다음으로 교체 — `CPL_ROW_DEFS`→`plEffectiveRowDefs('org')`, `tv(row.id)`→`tv(row)`, `pv(row.id,...)`→`pv(row,...)`로 바뀐 부분 외엔 원본과 동일 (`tv('sales')`/`pv('sales',prd)`처럼 문자열 인자를 쓰는 %-행 블록은 `rowSeries`가 문자열도 처리하므로 그대로 둠):

```js
    plEffectiveRowDefs('org').forEach(function(row){
      const mk=row.member?PFX+':'+row.member:null;
      if(mk&&!plExpanded.has(mk))return;
      const tk=row.toggle?PFX+':'+row.toggle:null;
      const cls=['pl-row',row.bold?'pl-bold':'',row.sub?'pl-sub':'',row.hl?'pl-hl-'+row.hl:'',row.toggle?'pl-group':''].filter(Boolean).join(' ');
      const chev=tk?'<i data-lucide="'+(plExpanded.has(tk)?'chevron-down':'chevron-right')+'" class="pl-chev"></i>':'';
      const totV=tv(row);
      t+='<tr class="'+cls+'"'+(tk?' data-cpl-toggle="'+tk+'"':'')+'>'+
        '<td>'+chev+row.label+'</td>'+
        '<td data-plitem="'+escPlAttr(row.id)+'" data-pldim="Department" data-pldimval="__depts__" data-pldepts="'+deptsAttr+'" data-plmonths="'+allMStr+'" data-plsec="'+brandKey+'">'+fmtMm(totV)+'<div class="pl-mom pl-mom-na">&nbsp;</div></td>';
      periods.forEach(function(prd,pi){
        const pV=pv(row,prd),prV=pi>0?pv(row,periods[pi-1]):undefined;
        const mStr=prd.monthIndices.map(function(i){return months[i];}).join(',');
        t+='<td class="pl-col-total" data-plitem="'+escPlAttr(row.id)+'" data-pldim="Department" data-pldimval="__depts__" data-pldepts="'+deptsAttr+'" data-plmonths="'+mStr+'" data-plsec="'+brandKey+'">'+fmtMm(pV)+momCell(pV,prV)+'</td>';
      });
      t+='</tr>';
      if(row.pct&&(!row.pctMember||plExpanded.has(PFX+':'+row.pctMember))){
        const tS=tv('sales');
        t+='<tr class="pl-pct'+(row.sub?' pl-sub':'')+(row.hl?' pl-pct-hl-'+row.hl:'')+'"><td>%</td>'+
          '<td>'+fmtPct(totV,tS)+'</td>';
        periods.forEach(function(prd){t+='<td class="pl-col-total">'+fmtPct(pv(row,prd),pv('sales',prd))+'</td>';});
        t+='</tr>';
      }
    });
    return t+'</tbody></table>';
```

**주의:** `row.pct`는 커스텀 계산식 행에서 항상 `false`(Task 3 §1의 `plEffectiveRowDefs`가 커스텀 행을 `{..., pct:false}`로 생성)이므로 %-행은 기존 22개 행에만 렌더링되고 커스텀 행에는 안 붙는다 — 의도된 동작.

- [ ] **Step 3: 행 편집기 UI 추가**

Task 2에서 만든 `wirePlEditPanel` 함수 바로 위에 삽입:

```js
function renderPlRowEditor(screenId){
  const cfg = state.plViewConfig[screenId];
  const hidden = new Set((cfg && cfg.rows && cfg.rows.hidden) || []);
  const blockOrder = (cfg && cfg.rows && cfg.rows.blockOrder && cfg.rows.blockOrder.length) ? cfg.rows.blockOrder : PL_ROW_BLOCKS.map(function(b){ return b.anchor; });
  let h = '<div class="pl-edit-section-title">행(계정 항목)</div><ul class="pl-edit-row-list" data-pl-row-list="' + screenId + '">';
  blockOrder.forEach(function(anchor){
    const block = PL_ROW_BLOCKS.filter(function(b){ return b.anchor === anchor; })[0];
    if (!block) return;
    const anchorRow = CPL_ROW_DEFS.filter(function(r){ return r.id === anchor; })[0];
    h += '<li class="pl-edit-row-block" draggable="true" data-pl-row-block="' + anchor + '">'
       + '<span class="pl-edit-drag-handle">⣿</span>'
       + '<span class="pl-edit-row-locked-label">' + anchorRow.label + '</span>';
    if (block.ids.length > 1) {
      const subOrder = (cfg && cfg.rows.subOrder && cfg.rows.subOrder[anchor] && cfg.rows.subOrder[anchor].length === 5) ? cfg.rows.subOrder[anchor] : PL_SUB_GROUP_KEYS;
      h += '<ul class="pl-edit-sub-list" data-pl-sub-list="' + anchor + '">';
      subOrder.forEach(function(key){
        const subId = anchor + '.' + key;
        const subRow = CPL_ROW_DEFS.filter(function(r){ return r.id === subId; })[0];
        h += '<li class="pl-edit-sub-row" draggable="true" data-pl-sub-row="' + subId + '" data-pl-sub-parent="' + anchor + '">'
           + '<span class="pl-edit-drag-handle">⣿</span>'
           + '<label><input type="checkbox" data-pl-row-hide="' + subId + '"' + (hidden.has(subId) ? '' : ' checked') + '>' + subRow.label + '</label></li>';
      });
      h += '</ul>';
    }
    h += '</li>';
  });
  h += '</ul>';
  return h;
}

function wirePlRowDragHandlers(screenId){
  const list = document.querySelector('[data-pl-row-list="' + screenId + '"]');
  if (!list) return;
  let dragBlock = null;
  list.querySelectorAll('[data-pl-row-block]').forEach(function(li){
    li.addEventListener('dragstart', function(e){ dragBlock = li.dataset.plRowBlock; e.dataTransfer.effectAllowed = 'move'; });
    li.addEventListener('dragover', function(e){
      e.preventDefault();
      if (e.target.closest('[data-pl-sub-row]')) return;
      const target = e.target.closest('[data-pl-row-block]');
      if (!target || target.dataset.plRowBlock === dragBlock) return;
      const rect = target.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      list.insertBefore(document.querySelector('[data-pl-row-block="' + dragBlock + '"]'), before ? target : target.nextSibling);
    });
    li.addEventListener('dragend', function(){
      const newOrder = Array.prototype.map.call(list.querySelectorAll('[data-pl-row-block]'), function(el){ return el.dataset.plRowBlock; });
      plUpdateConfig(screenId, function(cfg){ cfg.rows.blockOrder = newOrder; });
    });
  });
  list.querySelectorAll('[data-pl-sub-row]').forEach(function(li){
    let dragSub = null;
    li.addEventListener('dragstart', function(e){ dragSub = li.dataset.plSubRow; e.stopPropagation(); });
    li.addEventListener('dragover', function(e){
      e.preventDefault(); e.stopPropagation();
      const target = e.target.closest('[data-pl-sub-row]');
      if (!target || target.dataset.plSubParent !== li.dataset.plSubParent || target.dataset.plSubRow === dragSub) return;
      const subList = target.closest('[data-pl-sub-list]');
      const rect = target.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      subList.insertBefore(document.querySelector('[data-pl-sub-row="' + dragSub + '"]'), before ? target : target.nextSibling);
    });
    li.addEventListener('dragend', function(e){
      e.stopPropagation();
      const parent = li.dataset.plSubParent;
      const subList = document.querySelector('[data-pl-sub-list="' + parent + '"]');
      const newOrder = Array.prototype.map.call(subList.querySelectorAll('[data-pl-sub-row]'), function(el){ return el.dataset.plSubRow.split('.')[1]; });
      plUpdateConfig(screenId, function(cfg){ cfg.rows.subOrder[parent] = newOrder; });
    });
  });
  list.querySelectorAll('[data-pl-row-hide]').forEach(function(cb){
    cb.addEventListener('change', function(){
      const id = cb.dataset.plRowHide;
      plUpdateConfig(screenId, function(cfg){
        const set = new Set(cfg.rows.hidden);
        if (cb.checked) set.delete(id); else set.add(id);
        cfg.rows.hidden = Array.from(set);
      });
    });
  });
}
```

- [ ] **Step 4: 패널에 행 편집기 연결**

`renderPlEditPanel` 안의 `h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '"></div>';` 줄을:

```js
  h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '">'
     + renderPlRowEditor(screenId)
     + '</div>';
```

로 교체. `wirePlEditPanel` 안의 마지막 주석(`// Task 3/4/5가...`) 줄을:

```js
  wirePlRowDragHandlers(screenId);
```

로 교체(주석 유지하려면 이 줄 위에 남겨도 됨).

- [ ] **Step 5: 수동 검증 (browse)**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B js "document.querySelector('[data-pl-row-hide=\"sgaD.fee\"]').click()"
sleep 1
$B js "document.getElementById('categoryPlSection').innerText.includes('수수료')"
$B console --errors
```

Expected: 마지막 `js` 호출 결과가 `false`(숨겨진 "수수료" 세부계정이 표에서 사라짐), 콘솔 에러 없음.

- [ ] **Step 6: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: PL row show/hide + block reorder editing (org pilot)"
```

---

## Task 4: 프론트 — 커스텀 계산식 행

**Files:**
- Modify: `templates/dashboard_v2.html` (Task 3의 `plEvalFormula` 스텁 교체, `renderPlEditPanel`/`wirePlEditPanel` 확장)

**Interfaces:**
- Consumes: Task 3의 `PL_ROW_BLOCKS`(afterId 검증용), `plUpdateConfig`, `renderPlEditPanel`, `wirePlEditPanel`
- Produces: `PL_FORMULA_TOKENS`, `plParseFormula(src)`, `plValidateFormula(formula)`, `plEvalFormula(formula, M, months)`(Task 3 스텁 교체), `renderPlCustomRowEditor(screenId)`, `wirePlCustomRowHandlers(screenId, panelEl)`

- [ ] **Step 1: 수식 파서 작성 (Task 3의 스텁 교체)**

Task 3에서 추가한 다음 스텁:

```js
// Task 4에서 실제 수식 파서로 교체됨. 그때까지 custom 행은 항상 빈 배열이라 호출되지 않는다.
function plEvalFormula(formula, M, months){ return months.map(function(){ return 0; }); }
```

을 통째로 다음으로 교체:

```js
const PL_FORMULA_TOKENS = [
  'sales','cogs','gross','op','direct','contrib',
  'sgaD','sgaD.adv','sgaD.log','sgaD.fee','sgaD.hr','sgaD.etc',
  'sgaO','sgaO.adv','sgaO.log','sgaO.fee','sgaO.hr','sgaO.etc',
  'sgaC','sgaC.adv','sgaC.log','sgaC.fee','sgaC.hr','sgaC.etc',
];
const PL_FORMULA_TOKEN_SET = new Set(PL_FORMULA_TOKENS);
const PL_FORMULA_RE = /\s*(sgaD\.adv|sgaD\.log|sgaD\.fee|sgaD\.hr|sgaD\.etc|sgaO\.adv|sgaO\.log|sgaO\.fee|sgaO\.hr|sgaO\.etc|sgaC\.adv|sgaC\.log|sgaC\.fee|sgaC\.hr|sgaC\.etc|sales|cogs|gross|op|direct|contrib|sgaD|sgaO|sgaC|\d+\.\d+|\d+|\+|-|\*|\/|\(|\))\s*/y;

function plTokenizeFormula(src){
  const tokens = [];
  let i = 0;
  while (i < src.length) {
    PL_FORMULA_RE.lastIndex = i;
    const m = PL_FORMULA_RE.exec(src);
    if (!m || m.index !== i) throw new Error('알 수 없는 문자: "' + src.slice(i, i + 1) + '"');
    tokens.push(m[1]);
    i = PL_FORMULA_RE.lastIndex;
  }
  return tokens;
}

function plParseFormula(src){
  const tokens = plTokenizeFormula(src);
  let pos = 0;
  function peek(){ return tokens[pos]; }
  function next(){ return tokens[pos++]; }
  function parseAtom(){
    const t = next();
    if (t === undefined) throw new Error('수식이 완성되지 않았습니다');
    if (t === '(') {
      const node = parseExpr();
      if (next() !== ')') throw new Error('닫는 괄호 ")"가 필요합니다');
      return node;
    }
    if (PL_FORMULA_TOKEN_SET.has(t)) return { type:'metric', id:t };
    if (/^\d+(\.\d+)?$/.test(t)) return { type:'const', value:parseFloat(t) };
    throw new Error('허용되지 않은 토큰: "' + t + '" (허용: ' + PL_FORMULA_TOKENS.join(', ') + ', 숫자, + - * / ( ))');
  }
  function parseTerm(){
    let node = parseAtom();
    while (peek() === '*' || peek() === '/') {
      const op = next();
      node = { type:'bin', op:op, left:node, right:parseAtom() };
    }
    return node;
  }
  function parseExpr(){
    let node = parseTerm();
    while (peek() === '+' || peek() === '-') {
      const op = next();
      node = { type:'bin', op:op, left:node, right:parseTerm() };
    }
    return node;
  }
  const ast = parseExpr();
  if (pos !== tokens.length) throw new Error('수식 끝에 예상치 못한 문자가 있습니다: "' + tokens[pos] + '"');
  return ast;
}

function plEvalAst(ast, valueAt){
  if (ast.type === 'const') return ast.value;
  if (ast.type === 'metric') return valueAt(ast.id);
  const l = plEvalAst(ast.left, valueAt), r = plEvalAst(ast.right, valueAt);
  if (ast.op === '+') return l + r;
  if (ast.op === '-') return l - r;
  if (ast.op === '*') return l * r;
  if (ast.op === '/') return r === 0 ? 0 : l / r;
  throw new Error('알 수 없는 연산자: ' + ast.op);
}

function plValidateFormula(formula){
  plParseFormula(formula); // 문법 에러면 여기서 throw
}

function plEvalFormula(formula, M, months){
  let ast;
  try { ast = plParseFormula(formula); } catch(e){ return months.map(function(){ return 0; }); }
  return months.map(function(_, i){
    return plEvalAst(ast, function(id){ return (cplRowValue(M, id) || [])[i] || 0; });
  });
}
```

- [ ] **Step 2: 커스텀 행 추가 UI**

Task 3에서 추가한 `renderPlRowEditor`/`wirePlRowDragHandlers` 바로 아래에 삽입:

```js
function renderPlCustomRowEditor(screenId){
  const cfg = state.plViewConfig[screenId];
  const custom = (cfg && cfg.rows && cfg.rows.custom) || [];
  let h = '<div class="pl-edit-section-title">계산식 행</div><ul class="pl-edit-custom-list">';
  custom.forEach(function(c){
    h += '<li class="pl-edit-custom-row"><span>' + escPlAttr(c.label) + '</span><code>' + escPlAttr(c.formula) + '</code>'
       + '<button data-pl-custom-delete="' + c.id + '" data-pl-screen="' + screenId + '">×</button></li>';
  });
  h += '</ul>'
     + '<div class="pl-edit-custom-form">'
     + '<input type="text" placeholder="행 이름 (예: 매출총이익률)" data-pl-custom-name-input>'
     + '<input type="text" placeholder="수식 (예: gross / sales * 100)" data-pl-custom-formula-input>'
     + '<div class="pl-edit-token-hints">' + PL_FORMULA_TOKENS.map(function(t){ return '<span class="pl-edit-token-chip" data-pl-token-insert="' + t + '">' + t + '</span>'; }).join('') + '</div>'
     + '<div class="pl-edit-custom-error" data-pl-custom-error></div>'
     + '<button data-pl-custom-add="' + screenId + '">+ 계산식 행 추가 (영업이익 뒤에 삽입)</button>'
     + '</div>';
  return h;
}

function wirePlCustomRowHandlers(screenId, panelEl){
  if (!panelEl) return;
  panelEl.querySelectorAll('[data-pl-token-insert]').forEach(function(chip){
    chip.addEventListener('click', function(){
      const input = panelEl.querySelector('[data-pl-custom-formula-input]');
      input.value += (input.value && !/[\s+\-*/(]$/.test(input.value) ? ' ' : '') + chip.dataset.plTokenInsert;
      input.focus();
    });
  });
  const addBtn = panelEl.querySelector('[data-pl-custom-add="' + screenId + '"]');
  if (addBtn) addBtn.addEventListener('click', function(){
    const nameInput = panelEl.querySelector('[data-pl-custom-name-input]');
    const formulaInput = panelEl.querySelector('[data-pl-custom-formula-input]');
    const errBox = panelEl.querySelector('[data-pl-custom-error]');
    const name = nameInput.value.trim(), formula = formulaInput.value.trim();
    errBox.textContent = '';
    if (!name) { errBox.textContent = '행 이름을 입력하세요'; return; }
    try { plValidateFormula(formula); } catch(e){ errBox.textContent = e.message; return; }
    plUpdateConfig(screenId, function(cfg){
      cfg.rows.custom.push({ id:'custom_' + Date.now(), label:name, formula:formula, afterId:'op' });
    });
  });
  panelEl.querySelectorAll('[data-pl-custom-delete]').forEach(function(btn){
    btn.addEventListener('click', function(){
      const id = btn.dataset.plCustomDelete, screen = btn.dataset.plScreen;
      plUpdateConfig(screen, function(cfg){ cfg.rows.custom = cfg.rows.custom.filter(function(c){ return c.id !== id; }); });
    });
  });
}
```

- [ ] **Step 3: 패널에 연결**

`renderPlEditPanel`의 본문 조립 줄:

```js
  h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '">'
     + renderPlRowEditor(screenId)
     + '</div>';
```

를:

```js
  h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '">'
     + renderPlRowEditor(screenId)
     + renderPlCustomRowEditor(screenId)
     + '</div>';
```

로 교체. `wirePlEditPanel`에서 `wirePlRowDragHandlers(screenId);` 다음 줄에 추가:

```js
  wirePlCustomRowHandlers(screenId, panel);
```

- [ ] **Step 4: 수동 검증 (browse)**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B fill '[data-pl-custom-name-input]' '매출총이익률'
$B fill '[data-pl-custom-formula-input]' 'gross / sales * 100'
$B js "document.querySelector('[data-pl-custom-add=org]').click()"
sleep 1
$B js "document.getElementById('categoryPlSection').innerText.includes('매출총이익률')"
$B console --errors
```

Expected: 마지막 `js` 호출 결과 `true`, 콘솔 에러 없음. 잘못된 수식(`sales / headcount`)으로 같은 흐름을 반복하면 `data-pl-custom-error` 박스에 "허용되지 않은 토큰: \"headcount\"..." 메시지가 뜨고 행이 추가되지 않는지도 확인.

- [ ] **Step 5: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: PL custom formula rows with whitelisted expression parser"
```

---

## Task 5: 프론트 — 섹션(전체/SK/유통) 표시·순서 편집

**Files:**
- Modify: `templates/dashboard_v2.html` (`renderOrgPl()`의 섹션 렌더 루프, `renderPlEditPanel`/`wirePlEditPanel` 확장)

**Interfaces:**
- Consumes: Task 2의 `plUpdateConfig`, `renderPlEditPanel`, `wirePlEditPanel`
- Produces: `PL_ORG_SECTION_IDS`, `PL_ORG_SECTION_LABEL`, `plEffectiveSections(screenId)`, `renderPlSectionEditor(screenId)`, `wirePlSectionDragHandlers(screenId)`

- [ ] **Step 1: 섹션 파생 함수 추가**

Task 3의 `plEffectiveRowDefs` 함수 바로 아래에 삽입:

```js
const PL_ORG_SECTION_IDS = ['all','SK','UM'];
let PL_ORG_SECTION_LABEL = null; // 최초 사용 시 지연 초기화 (_BRAND_LABEL 정의 이후 실행되도록)
function plOrgSectionLabel(id){
  if (!PL_ORG_SECTION_LABEL) PL_ORG_SECTION_LABEL = { all:'전체', SK:_BRAND_LABEL.SK, UM:_BRAND_LABEL.UM };
  return PL_ORG_SECTION_LABEL[id];
}

function plEffectiveSections(screenId){
  const cfg = state.plViewConfig[screenId];
  if (!cfg) return PL_ORG_SECTION_IDS.slice();
  const hidden = new Set((cfg.sections && cfg.sections.hidden) || []);
  const order = (cfg.sections && cfg.sections.order && cfg.sections.order.length) ? cfg.sections.order : PL_ORG_SECTION_IDS;
  const ordered = order.filter(function(id){ return PL_ORG_SECTION_IDS.indexOf(id) >= 0; });
  const remaining = PL_ORG_SECTION_IDS.filter(function(id){ return ordered.indexOf(id) < 0; });
  return ordered.concat(remaining).filter(function(id){ return !hidden.has(id); });
}
```

(`_BRAND_LABEL`은 `templates/dashboard_v2.html:4707`에 이미 정의된 `{ 'SK':'SK 브랜드', 'UM':'유통본부' }` — 지연 초기화라 정의 순서 무관.)

- [ ] **Step 2: `renderOrgPl()`의 섹션 루프를 `plEffectiveSections` 반영하도록 교체**

`templates/dashboard_v2.html:4912-4942` 전체(주석 `// 전체 합산 테이블...`부터 `_BRAND_ORDER.forEach(...)` 블록이 끝나는 `});`까지)를 다음으로 교체:

```js
  const allDepts=Object.keys(byNode);
  const activeSections = plEffectiveSections('org');

  activeSections.forEach(function(sec){
    if (sec === 'all') {
      html+='<div class="pl-section-title" style="display:flex;align-items:center"><span>전체</span>'+plDlBtn('all',months.join(','),allDepts.join(','))+'</div>';
      html+=renderTable(secMetrics(allDepts,'all'),allDepts,'all');
      return;
    }
    const brand = sec;
    const brandDivs=_BRAND_DIV[brand]||[];
    const brandDepts=[];
    brandDivs.forEach(function(div){(_DIV_DEPT_MAP[div]||[]).forEach(function(d){if(byNode[d])brandDepts.push(d);});});
    if(!brandDepts.length)return;
    const bExp=orgBrandExp.has(brand);
    html+='<div class="pl-section-title" style="cursor:pointer;font-size:14px;display:flex;align-items:center" data-org-brand="'+brand+'">'
      +'<span><i data-lucide="'+(bExp?'chevron-down':'chevron-right')+'" class="pl-chev"></i>'+_BRAND_LABEL[brand]+'</span>'
      +(bExp?plDlBtn(brand,months.join(','),brandDepts.join(',')):'')+'</div>';
    if(!bExp)return;
    html+=renderTable(secMetrics(brandDepts,brand),brandDepts,brand);
    brandDivs.forEach(function(div){
      const divDepts=(_DIV_DEPT_MAP[div]||[]).filter(function(d){return !!byNode[d];});
      if(!divDepts.length)return;
      const dExp=orgDivExp.has(div);
      html+='<div class="pl-section-title" style="cursor:pointer;margin-left:20px;display:flex;align-items:center" data-org-div="'+div+'">'
        +'<span><i data-lucide="'+(dExp?'chevron-down':'chevron-right')+'" class="pl-chev"></i>'+div+'</span>'
        +(dExp?plDlBtn(brand,months.join(','),divDepts.join(',')):'')+'</div>';
      if(!dExp)return;
      html+=renderTable(secMetrics(divDepts,brand),divDepts,brand);
      divDepts.forEach(function(dept){
        html+='<div class="pl-section-title" style="margin-left:40px;font-size:11px;opacity:.8;display:flex;align-items:center"><span>▸ '+dept+'</span>'+plDlBtn(brand,months.join(','),dept)+'</div>';
        html+=renderTable(secMetrics([dept],brand),[dept],brand);
      });
    });
  });
```

- [ ] **Step 3: 섹션 편집기 UI**

Task 4의 `renderPlCustomRowEditor`/`wirePlCustomRowHandlers` 바로 아래에 삽입:

```js
function renderPlSectionEditor(screenId){
  const cfg = state.plViewConfig[screenId];
  const hidden = new Set((cfg && cfg.sections && cfg.sections.hidden) || []);
  const order = (cfg && cfg.sections && cfg.sections.order && cfg.sections.order.length) ? cfg.sections.order : PL_ORG_SECTION_IDS.slice();
  let h = '<div class="pl-edit-section-title">섹션(구분)</div><ul class="pl-edit-section-list" data-pl-section-list="' + screenId + '">';
  order.forEach(function(id){
    h += '<li class="pl-edit-section-row" draggable="true" data-pl-section-row="' + id + '">'
       + '<span class="pl-edit-drag-handle">⣿</span>'
       + '<label><input type="checkbox" data-pl-section-hide="' + id + '"' + (hidden.has(id) ? '' : ' checked') + '>' + plOrgSectionLabel(id) + '</label></li>';
  });
  h += '</ul>';
  return h;
}

function wirePlSectionDragHandlers(screenId){
  const list = document.querySelector('[data-pl-section-list="' + screenId + '"]');
  if (!list) return;
  let dragId = null;
  list.querySelectorAll('[data-pl-section-row]').forEach(function(li){
    li.addEventListener('dragstart', function(){ dragId = li.dataset.plSectionRow; });
    li.addEventListener('dragover', function(e){
      e.preventDefault();
      const target = e.target.closest('[data-pl-section-row]');
      if (!target || target.dataset.plSectionRow === dragId) return;
      const rect = target.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      list.insertBefore(document.querySelector('[data-pl-section-row="' + dragId + '"]'), before ? target : target.nextSibling);
    });
    li.addEventListener('dragend', function(){
      const newOrder = Array.prototype.map.call(list.querySelectorAll('[data-pl-section-row]'), function(el){ return el.dataset.plSectionRow; });
      plUpdateConfig(screenId, function(cfg){ cfg.sections.order = newOrder; });
    });
  });
  list.querySelectorAll('[data-pl-section-hide]').forEach(function(cb){
    cb.addEventListener('change', function(){
      const id = cb.dataset.plSectionHide;
      plUpdateConfig(screenId, function(cfg){
        const set = new Set(cfg.sections.hidden);
        if (cb.checked) set.delete(id); else set.add(id);
        cfg.sections.hidden = Array.from(set);
      });
    });
  });
}
```

- [ ] **Step 4: 패널에 연결**

`renderPlEditPanel`의 본문 조립 줄을:

```js
  h += '<div class="pl-edit-panel-body" data-pl-edit-body="' + screenId + '">'
     + renderPlSectionEditor(screenId)
     + renderPlRowEditor(screenId)
     + renderPlCustomRowEditor(screenId)
     + '</div>';
```

로 교체(섹션 편집기를 맨 위로). `wirePlEditPanel`에서 `wirePlCustomRowHandlers(screenId, panel);` 다음 줄에 추가:

```js
  wirePlSectionDragHandlers(screenId);
```

- [ ] **Step 5: 수동 검증 (browse)**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B js "document.querySelector('[data-pl-section-hide=UM]').click()"
sleep 1
$B js "document.getElementById('categoryPlSection').innerText.includes('유통본부')"
$B console --errors
```

Expected: 마지막 `js` 호출 결과 `false`(유통본부 섹션 숨김), 콘솔 에러 없음.

- [ ] **Step 6: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: PL section show/hide + reorder editing (org pilot)"
```

---

## Task 6: 통합 검증 + 회귀 테스트

**Files:** 없음(검증 전용)

**Interfaces:** 없음

- [ ] **Step 1: 백엔드 전체 회귀**

Run: `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q`
Expected: 전부 PASS.

- [ ] **Step 2: "기본" 뷰가 파일럿 이전과 동일한지 확인**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.getElementById('categoryPlSection').innerText.slice(0,200)"
```

Expected: `전체` / `SK 브랜드` / `유통본부` 3개 섹션 헤더가 편집 이전과 동일한 순서로 나타남(편집 안 한 로그인 세션 기준 — 아직 어떤 뷰도 선택 안 한 "기본" 상태).

- [ ] **Step 3: 엔드투엔드 편집 → 저장 → 새로고침 → 재현 시나리오**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B js "document.querySelector('[data-pl-row-hide=\"sgaD.fee\"]').click()"
$B js "document.querySelector('[data-pl-section-hide=UM]').click()"
sleep 1
$B dialog-accept "회귀테스트뷰"
$B js "document.querySelector('[data-pl-view-save-as=org]').click()"
sleep 1
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B js "switchCategory('org')"
sleep 3
$B js "document.querySelector('[data-pl-edit-toggle=org]').click()"
sleep 1
$B js "document.querySelector('[data-pl-view-select=org]').value = Array.from(document.querySelector('[data-pl-view-select=org]').options).find(o=>o.textContent==='회귀테스트뷰').value; document.querySelector('[data-pl-view-select=org]').dispatchEvent(new Event('change'))"
sleep 1
$B js "JSON.stringify({hasUM: document.getElementById('categoryPlSection').innerText.includes('유통본부'), hasFee: document.getElementById('categoryPlSection').innerText.includes('수수료')})"
```

Expected: `{"hasUM":false,"hasFee":false}` — 새로고침 후에도 저장한 커스텀 상태가 그대로 재현됨.

- [ ] **Step 4: "기본"으로 되돌리면 원상복구되는지 + 뷰 삭제**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B js "document.querySelector('[data-pl-view-select=org]').value=''; document.querySelector('[data-pl-view-select=org]').dispatchEvent(new Event('change'))"
sleep 1
$B js "document.getElementById('categoryPlSection').innerText.includes('유통본부')"
$B js "document.querySelector('[data-pl-view-select=org]').value = Array.from(document.querySelector('[data-pl-view-select=org]').options).find(o=>o.textContent==='회귀테스트뷰').value; document.querySelector('[data-pl-view-select=org]').dispatchEvent(new Event('change'))"
sleep 1
$B dialog-accept ""
$B js "document.querySelector('[data-pl-view-delete=org]').click()"
sleep 1
$B js "!Array.from(document.querySelector('[data-pl-view-select=org]').options).some(o=>o.textContent==='회귀테스트뷰')"
$B console --errors
```

Expected: 첫 `js` 호출 → `true`("기본" 선택 시 유통본부 섹션 다시 보임), 마지막 `js` 호출 → `true`(삭제 후 드롭다운에서 사라짐), 콘솔 에러 없음.

- [ ] **Step 5: 다른 사용자에게 영향 없음 확인 (API 레벨)**

Run: `python -m pytest tests/test_pl_views_api.py::test_pl_views_list_empty_for_new_screen -v`
Expected: PASS — 이 테스트가 쓰는 `testuser_pl_views` 계정은 이번 단계에서 만든 어떤 jeffrey 소유 뷰도 보이지 않음을 이미 검증(사용자별 격리).

- [ ] **Step 6: 스펙 문서 상태 갱신 + 최종 커밋**

`docs/superpowers/specs/2026-07-10-pl-view-editor-design.md`의 `**Status:** Approved (pilot scope)`를 `**Status:** Implemented (pilot — org screen)`로 수정.

```bash
git add docs/superpowers/specs/2026-07-10-pl-view-editor-design.md
git commit -m "docs: mark PL view editor org pilot as implemented"
```
