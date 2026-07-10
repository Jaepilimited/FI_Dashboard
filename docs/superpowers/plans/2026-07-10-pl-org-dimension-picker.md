# 조직별 P&L 구분 기준 차원 교체 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 조직별(org) P&L 편집기의 사이드 패널에 "구분 기준" 드롭존을 추가해, 지금 고정된 `Department`(전체/SK/유통 3단 계층) 대신 국가·상품라인 등 `/api/pl`이 지원하는 8개 차원 중 아무거나로 섹션 구성을 바꿀 수 있게 한다.

**Architecture:** 기존 `loadCplData()`(3-fetch: SK/UM/전체)를 org+non-Department 조합일 때만 1-fetch(브랜드 필터 없음)로 분기시키고, `renderOrgPl()`의 섹션 렌더 루프를 `plEffectiveSectionDim('org')==='Department'`일 때 기존 코드 그대로, 아닐 때는 매출 상위 10개+기타를 기존 `secMetrics`/`renderTable`(둘 다 이미 dimension-agnostic)로 그대로 재사용해 렌더. 백엔드(`app_v2.py`) 변경 없음.

**Tech Stack:** `templates/dashboard_v2.html`의 인라인 ES5 JS (프레임워크 없음). 검증은 gstack `browse` 스킬로 라이브 서버(`http://127.0.0.1:5000`) 대상 수동 검증 — 이 프로젝트에 JS 유닛테스트 러너 없음.

## Global Constraints

- 레이아웃은 기존 조직별 P&L 테이블과 완전히 동일 — 신규 렌더링 로직 없이 기존 `renderTable`/`secMetrics` 재사용.
- `state.plViewConfig.org`가 `null`이거나 `sections.dim`이 없거나 `'Department'`이면 **기존 렌더링 경로 100% 무변경** (기본 화면 회귀 위험 최고 지점 — 이전 플랜에서도 매 태스크 이 불변성을 증명했음, 이번에도 동일).
- 구분 기준 후보 8개, 정확히 이 컬럼명: `Department`,`Line`,`Category`,`Country`,`Continent2`,`Customer`,`Sales_Type`,`Group`.
- `dim!=='Department'`일 때: 브랜드 필터 없이 전사 기준, 매출 합계 내림차순 상위 10개 + "기타" 자동 집계. 개별 표시/숨김·순서변경 없음. 브랜드×차원 동시 교차 없음. 추가 드릴다운 없음.
- 백엔드(`app_v2.py`) 변경 없음 — `/api/pl`이 이미 8개 차원 전부 지원.
- 커밋마다 `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q` 통과 확인(회귀 없음 증명용 — 이번 플랜은 백엔드를 안 건드리므로 통과는 당연하지만, "안 건드렸다"를 증명하는 게 목적).
- 라이브 운영 서버(Flask 디버그 리로더 자동 재시작), master 직접 작업(사용자 승인, worktree 없음). 프론트 검증은 `browse` 명령을 반드시 한 Bash 호출 안에서 순차 실행(daemon이 별도 호출 간 세션을 잃는 이슈 있음). 로그인: `jeffrey`/`skin1004!`.

---

## File Structure

| 파일 | 책임 |
|------|------|
| `templates/dashboard_v2.html` | `plEffectiveSectionDim`, `_cplDimCol`/`loadCplData` 분기, `renderOrgPl()` 섹션 렌더 분기, 구분 기준 드롭존 UI + 드래그 핸들러, `pl-edit-dim-*` CSS |

백엔드(`app_v2.py`) 변경 없음.

---

## Task 1: 데이터 레이어 — `plEffectiveSectionDim` + `_cplDimCol`/`loadCplData` 분기

**Files:**
- Modify: `templates/dashboard_v2.html:4595-4603` (`_cplDimCol`)
- Modify: `templates/dashboard_v2.html:4629-4700` (`loadCplData`)
- Modify: `templates/dashboard_v2.html:4944` 부근 (`plEffectiveSections` 옆에 `plEffectiveSectionDim` 추가)

**Interfaces:**
- Produces: `plEffectiveSectionDim(screenId)` → `'Department'|'Line'|'Category'|'Country'|'Continent2'|'Customer'|'Sales_Type'|'Group'`. `_cplDimCol()`가 org일 때 이 함수를 참조하도록 변경. `loadCplData()`가 org+non-Department일 때 1-fetch로 분기(그 외 모든 경우 기존과 완전히 동일한 3-fetch, byte-for-byte 동일 결과).
- Consumes: 없음 (기존 `state.plViewConfig`, `_cplAppendDrillFilters` 그대로 사용)

- [ ] **Step 1: `plEffectiveSectionDim` 추가**

`templates/dashboard_v2.html:4943` (`function plEffectiveSections(screenId){` 바로 위)에 삽입:

```js
function plEffectiveSectionDim(screenId){
  const cfg = state.plViewConfig[screenId];
  return (cfg && cfg.sections && cfg.sections.dim) || 'Department';
}
```

- [ ] **Step 2: `_cplDimCol()`의 org 분기 교체**

`templates/dashboard_v2.html:4598`:

```js
  if (cat === 'org')     return 'Department';
```

를:

```js
  if (cat === 'org')     return plEffectiveSectionDim('org');
```

로 교체. (`function` 선언은 호이스팅되므로 `plEffectiveSectionDim`이 파일상 `_cplDimCol`보다 뒤에 있어도 문제없음 — 이 코드베이스가 이미 여러 곳에서 의존하는 패턴.)

- [ ] **Step 3: `loadCplData()`를 org+non-Department 1-fetch 분기로 리팩터**

`templates/dashboard_v2.html:4629-4700` 전체(`async function loadCplData(){`부터 함수가 끝나는 `}`까지)를 다음으로 교체:

```js
async function loadCplData(){
  if (_cplDataLoading) return;
  _cplDataLoading = true;
  state.cplData = null;
  // "불러오는 중" 표시
  const wrap = document.getElementById('categoryPlSection');
  if (wrap) wrap.innerHTML = '<div style="padding:20px;color:var(--text-tertiary)">불러오는 중…</div>';
  try {
    const dimCol = _cplDimCol();
    const PL_FIELDS = ['sales','cogs','gross','op',
      'sgaD','sgaD_adv','sgaD_log','sgaD_fee','sgaD_hr','sgaD_etc',
      'sgaO','sgaO_adv','sgaO_log','sgaO_fee','sgaO_hr','sgaO_etc',
      'sgaC','sgaC_adv','sgaC_log','sgaC_fee','sgaC_hr','sgaC_etc'];
    const byNode = {};
    let months;
    function mergeNode(brand, apiData){
      const apiMonths = apiData.months || [];
      const idxMap = {};
      apiMonths.forEach(function(m, i){ idxMap[m] = i; });
      const zeros = function(){ return months.map(function(){ return 0; }); };
      (apiData.nodes || []).forEach(function(nd){
        const name = nd.name;
        if (!byNode[name]) byNode[name] = {};
        if (!byNode[name][brand]) byNode[name][brand] = {};
        const target = byNode[name][brand];
        PL_FIELDS.forEach(function(f){
          if (!target[f]) target[f] = zeros();
          const src = nd[f] || [];
          months.forEach(function(m, ti){
            const si = idxMap[m];
            if (si != null && src[si] != null) target[f][ti] += src[si];
          });
        });
        target.direct = target.gross.map(function(v, i){ return v - target.sgaD[i]; });
        target.contrib = target.direct.map(function(v, i){ return v - target.sgaO[i]; });
      });
    }
    const orgByOtherDim = (state.category === 'org') && (dimCol !== 'Department');
    if (orgByOtherDim) {
      // 조직별 화면에서 구분 기준이 Department가 아닐 때: 브랜드 필터 없이 1개 쿼리만
      const pAll = new URLSearchParams();
      pAll.append('dim', dimCol);
      _cplAppendDrillFilters(pAll);
      const dAll = await fetch('/api/pl?' + pAll.toString(), { credentials: 'same-origin' }).then(function(r){ return r.json(); });
      months = (dAll.months || []).slice().sort();
      mergeNode('all', dAll);
    } else {
      // 기존 동작: SK/UM/전체 3개 쿼리 (org+Department, region, product, sales 전부 이 경로)
      const pSK = new URLSearchParams();
      pSK.append('dim', dimCol);
      pSK.append('brand', 'SK');
      _cplAppendDrillFilters(pSK);
      const pUM = new URLSearchParams();
      pUM.append('dim', dimCol);
      pUM.append('brand', 'UM');
      _cplAppendDrillFilters(pUM);
      const pAll = new URLSearchParams();
      pAll.append('dim', dimCol);
      _cplAppendDrillFilters(pAll);
      const [dSK, dUM, dAll] = await Promise.all([
        fetch('/api/pl?' + pSK.toString(), { credentials: 'same-origin' }).then(function(r){ return r.json(); }),
        fetch('/api/pl?' + pUM.toString(), { credentials: 'same-origin' }).then(function(r){ return r.json(); }),
        fetch('/api/pl?' + pAll.toString(), { credentials: 'same-origin' }).then(function(r){ return r.json(); }),
      ]);
      const monthsSet = new Set();
      (dSK.months || []).forEach(function(m){ monthsSet.add(m); });
      (dUM.months || []).forEach(function(m){ monthsSet.add(m); });
      (dAll.months || []).forEach(function(m){ monthsSet.add(m); });
      months = Array.from(monthsSet).sort();
      mergeNode('SK', dSK);
      mergeNode('UM', dUM);
      mergeNode('all', dAll);
    }
    state.cplData = { months: months, byNode: byNode };
  } catch(e){
    console.error('[CPL] loadCplData error', e);
    state.cplData = { months: activeMonths(), byNode: {} };
  } finally {
    _cplDataLoading = false;
  }
  renderCategoryPl();
}
```

**주의:** `months`는 이제 `let`으로 함수 최상단에서 선언되고 두 분기 중 하나에서 채워진 뒤 `mergeNode` 호출 시점에 이미 값이 있어야 한다 — 두 분기 모두 `mergeNode(...)` 호출 전에 `months = ...`를 먼저 실행하므로 안전.

- [ ] **Step 4: 수동 검증 (browse) — region/product/sales/org+Department 회귀 없음 + org+Country 1-fetch 확인**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B goto http://127.0.0.1:5000/dashboard
$B wait --networkidle
$B fill 'input[name="username"]' 'jeffrey'
$B fill 'input[name="password"]' 'skin1004!'
$B click 'button[type="submit"]'
$B wait --networkidle
$B js "switchCategory('product')"
sleep 3
$B js "Object.keys(state.cplData.byNode).slice(0,3)"
$B js "switchCategory('org')"
sleep 3
$B js "JSON.stringify({dim:_cplDimCol(), keys:Object.keys(state.cplData.byNode).slice(0,3)})"
$B js "state.plViewConfig.org = {rows:{blockOrder:[],subOrder:{},hidden:[],custom:[]}, sections:{dim:'Country',order:[],hidden:[],deptOverrides:{}}}; state.cplData=null; renderOrgPl(); 'triggered'"
sleep 3
$B js "JSON.stringify({dim:_cplDimCol(), keys:Object.keys(state.cplData.byNode).slice(0,5)})"
$B console --errors
```

Expected: product 화면 `byNode` 키가 라인명(예: `Centella` 등, 기존과 동일). org+기본(Department) `dim` → `"Department"`, 키는 부서명. `state.plViewConfig.org.sections.dim='Country'` 설정 후 재렌더한 결과 `dim` → `"Country"`, `byNode` 키가 국가명(예: `한국`,`베트남` 등)으로 바뀜. 콘솔 에러 없음.

- [ ] **Step 5: 회귀 테스트**

Run: `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q`
Expected: 14/14 PASS (백엔드 무변경이므로 기존과 동일 — 안 건드렸다는 증거로 기록).

- [ ] **Step 6: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: load org P&L by arbitrary dimension when sections.dim is set"
```

---

## Task 2: 렌더 분기 — `renderOrgPl()` 매출 상위 10개+기타 블록

**Files:**
- Modify: `templates/dashboard_v2.html:5401-5435` (`renderOrgPl()`의 섹션 렌더 루프)

**Interfaces:**
- Consumes: Task 1의 `plEffectiveSectionDim`, `state.cplData.byNode`(이제 dim에 따라 부서명 또는 다른 차원 값명으로 키가 있음)
- Produces: 없음 (렌더 로직만 추가, 신규 함수 export 없음 — `renderOrgPl()` 내부 로직)

- [ ] **Step 1: 섹션 렌더 루프를 dim 분기로 교체**

`templates/dashboard_v2.html:5401-5435`(`const allDepts=Object.keys(byNode);`부터 `activeSections.forEach(...)` 블록이 끝나는 `});`까지)를 다음으로 교체:

```js
  const allDepts=Object.keys(byNode);
  const sectionDim = plEffectiveSectionDim('org');

  if (sectionDim !== 'Department') {
    // 구분 기준이 Department가 아닐 때: 매출 상위 10개 + 기타 (브랜드 교차 없음)
    const salesOf = function(name){
      const src = (byNode[name] && byNode[name].all && byNode[name].all.sales) || [];
      return src.reduce(function(a,v){ return a+(v||0); }, 0);
    };
    const sortedNames = allDepts.slice().sort(function(a,b){ return salesOf(b) - salesOf(a); });
    const topNames = sortedNames.slice(0, 10);
    const restNames = sortedNames.slice(10);

    html+='<div class="pl-section-title" style="display:flex;align-items:center"><span>전체</span>'+plDlBtn('all',months.join(','),allDepts.join(','))+'</div>';
    html+=renderTable(secMetrics(allDepts,'all'),allDepts,'all');

    topNames.forEach(function(name){
      html+='<div class="pl-section-title" style="display:flex;align-items:center"><span>'+name+'</span>'+plDlBtn('all',months.join(','),name)+'</div>';
      html+=renderTable(secMetrics([name],'all'),[name],'all');
    });

    if (restNames.length){
      html+='<div class="pl-section-title" style="display:flex;align-items:center"><span>기타</span>'+plDlBtn('all',months.join(','),restNames.join(','))+'</div>';
      html+=renderTable(secMetrics(restNames,'all'),restNames,'all');
    }
  } else {
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
  }
```

**주의:** `sectionDim==='Department'`(else 블록) 안의 코드는 원본 `activeSections.forEach(...)` 블록과 **글자 하나까지 동일** — 이게 "기본 렌더링 무변경" 증명의 핵심이다. 복사할 때 임의로 손대지 말 것.

- [ ] **Step 2: 수동 검증 (browse)**

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
$B js "document.getElementById('categoryPlSection').innerText.slice(0,80)"
$B js "state.plViewConfig.org = {rows:{blockOrder:[],subOrder:{},hidden:[],custom:[]}, sections:{dim:'Country',order:[],hidden:[],deptOverrides:{}}}; state.cplData=null; renderOrgPl(); 'triggered'"
sleep 3
$B js "document.getElementById('categoryPlSection').innerText.split('\n').filter(function(l){return l.trim() && !l.includes('구분') && !l.includes('합계')}).slice(0,15).join(' | ')"
$B js "document.getElementById('categoryPlSection').innerText.includes('기타')"
$B console --errors
```

Expected: 첫 `innerText.slice(0,80)` 확인에서 "전체"가 보임(기존과 동일 — `state.plViewConfig.org`가 아직 null이므로 Department 경로). `dim='Country'`로 바꾼 뒤에는 섹션 제목들이 국가명으로 바뀌고 "기타" 섹션이 포함됨(국가 10개 초과 시). 콘솔 에러 없음.

- [ ] **Step 3: 회귀 테스트**

Run: `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q`
Expected: 14/14 PASS.

- [ ] **Step 4: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: render org P&L by top-10+기타 when sections.dim is not Department"
```

---

## Task 3: UI — 구분 기준 드롭존 + 필드 칩

**Files:**
- Modify: `templates/dashboard_v2.html:5189-5203` (`renderPlSectionEditor`)
- Modify: `templates/dashboard_v2.html` (`wirePlEditPanel` — 드롭존 와이어링 추가)
- Modify: `templates/dashboard_v2.html:1510` 부근 (CSS, `pl-edit-dim-*` 신규)

**Interfaces:**
- Consumes: Task 1의 `plEffectiveSectionDim`, Task 2의 렌더 분기, 기존 `plUpdateConfig`
- Produces: `PL_ORG_DIM_FIELDS`(배열), `wirePlDimDropzone(screenId)`

- [ ] **Step 1: 차원 필드 목록 상수 추가**

`templates/dashboard_v2.html:4936` (`const PL_ORG_SECTION_IDS = ['all','SK','UM'];` 바로 위)에 삽입:

```js
const PL_ORG_DIM_FIELDS = [
  { col:'Department',  label:'부서' },
  { col:'Line',         label:'라인' },
  { col:'Category',     label:'카테고리' },
  { col:'Country',      label:'국가' },
  { col:'Continent2',   label:'대륙' },
  { col:'Customer',     label:'거래처' },
  { col:'Sales_Type',   label:'판매유형' },
  { col:'Group',        label:'그룹' },
];
function plDimFieldLabel(col){
  const f = PL_ORG_DIM_FIELDS.filter(function(x){ return x.col === col; })[0];
  return f ? f.label : col;
}
```

- [ ] **Step 2: `renderPlSectionEditor`에 드롭존 + 조건부 섹션 체크리스트 추가**

`templates/dashboard_v2.html:5189-5203` 전체를 다음으로 교체:

```js
function renderPlSectionEditor(screenId){
  const dim = plEffectiveSectionDim(screenId);
  let h = '<div class="pl-edit-section-title">구분 기준</div>';
  h += '<div class="pl-edit-dim-dropzone" data-pl-dim-dropzone="' + screenId + '">' + escPlAttr(plDimFieldLabel(dim)) + '로 표시</div>';
  h += '<div class="pl-edit-dim-fields">' + PL_ORG_DIM_FIELDS.map(function(f){
    return '<span class="pl-edit-dim-chip" draggable="true" data-pl-dim-chip="' + f.col + '">' + f.label + '</span>';
  }).join('') + '</div>';

  h += '<div class="pl-edit-section-title">섹션(구분)</div>';
  if (dim !== 'Department') {
    h += '<div class="pl-edit-dim-note">매출 기준 상위 10개 + 기타 자동 표시</div>';
    return h;
  }

  const cfg = state.plViewConfig[screenId];
  const hidden = new Set((cfg && cfg.sections && cfg.sections.hidden) || []);
  const rawOrder = (cfg && cfg.sections && cfg.sections.order && cfg.sections.order.length) ? cfg.sections.order : PL_ORG_SECTION_IDS.slice();
  const orderedValid = rawOrder.filter(function(id){ return PL_ORG_SECTION_IDS.indexOf(id) >= 0; });
  const order = orderedValid.concat(PL_ORG_SECTION_IDS.filter(function(id){ return orderedValid.indexOf(id) < 0; }));
  h += '<ul class="pl-edit-section-list" data-pl-section-list="' + screenId + '">';
  order.forEach(function(id){
    h += '<li class="pl-edit-section-row" draggable="true" data-pl-section-row="' + id + '">'
       + '<span class="pl-edit-drag-handle">⣿</span>'
       + '<label><input type="checkbox" data-pl-section-hide="' + id + '"' + (hidden.has(id) ? '' : ' checked') + '>' + plOrgSectionLabel(id) + '</label></li>';
  });
  h += '</ul>';
  return h;
}
```

- [ ] **Step 3: 드롭존 드래그 핸들러 추가**

Task 2에서 만든 `wirePlSectionDragHandlers` 함수 바로 아래에 삽입:

```js
function wirePlDimDropzone(screenId){
  const zone = document.querySelector('[data-pl-dim-dropzone="' + screenId + '"]');
  if (!zone) return;
  document.querySelectorAll('[data-pl-dim-chip]').forEach(function(chip){
    chip.addEventListener('dragstart', function(e){ e.dataTransfer.setData('text/plain', chip.dataset.plDimChip); });
  });
  zone.addEventListener('dragover', function(e){ e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', function(){ zone.classList.remove('drag-over'); });
  zone.addEventListener('drop', function(e){
    e.preventDefault();
    zone.classList.remove('drag-over');
    const col = e.dataTransfer.getData('text/plain');
    if (!col) return;
    state.cplData = null;
    plUpdateConfig(screenId, function(cfg){ cfg.sections.dim = col; });
  });
}
```

- [ ] **Step 4: `wirePlEditPanel`에 연결**

`wirePlEditPanel` 함수 안의 `wirePlSectionDragHandlers(screenId);` 다음 줄에 추가:

```js
  wirePlDimDropzone(screenId);
```

- [ ] **Step 5: CSS 추가**

`templates/dashboard_v2.html:1540` 부근(기존 `pl-edit-*` CSS 블록 끝) — `.pl-edit-custom-form>button{...}` 다음 줄에 삽입:

```css
.pl-edit-dim-fields{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:8px}
.pl-edit-dim-chip{font-size:10px;padding:1px 6px;border-radius:10px;background:var(--surface);border:1px solid var(--border);color:var(--text-tertiary);cursor:grab}
.pl-edit-dim-chip:hover{border-color:var(--accent);color:var(--accent)}
.pl-edit-dim-dropzone{font-size:12px;padding:6px 8px;border:1px dashed var(--border-strong);border-radius:6px;text-align:center;color:var(--text-secondary);margin-bottom:6px;transition:border-color .12s,background .12s}
.pl-edit-dim-dropzone.drag-over{border-color:var(--accent);background:var(--accent-soft)}
.pl-edit-dim-note{font-size:11px;color:var(--text-tertiary);padding:4px 0}
```

- [ ] **Step 6: 수동 검증 (browse) — 실제 드래그앤드롭 이벤트로 종단 검증**

이전 플랜(Task 3)에서 체크박스 클릭만으로는 드래그 핸들러의 실제 동작을 증명하지 못한다는 교훈이 있었다 — 반드시 진짜 `DragEvent`를 dispatch해서 검증할 것.

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
$B js "document.querySelectorAll('[data-pl-dim-chip]').length"
$B js "
  var chip = document.querySelector('[data-pl-dim-chip=Country]');
  var zone = document.querySelector('[data-pl-dim-dropzone=org]');
  var dt = new DataTransfer();
  chip.dispatchEvent(new DragEvent('dragstart', {dataTransfer:dt, bubbles:true}));
  dt.setData('text/plain','Country');
  zone.dispatchEvent(new DragEvent('dragover', {dataTransfer:dt, bubbles:true, cancelable:true}));
  zone.dispatchEvent(new DragEvent('drop', {dataTransfer:dt, bubbles:true, cancelable:true}));
  'dispatched';
"
sleep 3
$B js "JSON.stringify({dim: state.plViewConfig.org.sections.dim, dropzoneText: document.querySelector('[data-pl-dim-dropzone=org]').textContent})"
$B js "document.getElementById('categoryPlSection').innerText.includes('기타')"
$B console --errors
```

Expected: 필드 칩 개수 → `8`. 드래그앤드롭 dispatch 후 `state.plViewConfig.org.sections.dim` → `"Country"`, 드롭존 텍스트에 `"국가로 표시"` 포함. 테이블에 "기타" 섹션 등장(국가 10개 초과 시). 콘솔 에러 없음.

- [ ] **Step 7: "Department로 되돌리기" 검증 + 기본 화면 무변경 재확인**

```bash
B=/c/Users/DB_PC/.claude/skills/gstack/browse/dist/browse
$B js "
  var chip = document.querySelector('[data-pl-dim-chip=Department]');
  var zone = document.querySelector('[data-pl-dim-dropzone=org]');
  var dt = new DataTransfer();
  chip.dispatchEvent(new DragEvent('dragstart', {dataTransfer:dt, bubbles:true}));
  dt.setData('text/plain','Department');
  zone.dispatchEvent(new DragEvent('drop', {dataTransfer:dt, bubbles:true, cancelable:true}));
  'dispatched';
"
sleep 3
$B js "JSON.stringify({dim: state.plViewConfig.org.sections.dim, hasSectionList: !!document.querySelector('[data-pl-section-list=org]')})"
$B console --errors
```

Expected: `dim` → `"Department"`, `hasSectionList` → `true`(기존 전체/SK/유통 체크리스트가 다시 나타남).

- [ ] **Step 8: 회귀 테스트**

Run: `python -m pytest tests/test_tableau_api.py tests/test_pl_views_api.py -q`
Expected: 14/14 PASS.

- [ ] **Step 9: 커밋**

```bash
git add templates/dashboard_v2.html
git commit -m "feat: add 구분 기준 dropzone UI for org P&L dimension picker"
```
