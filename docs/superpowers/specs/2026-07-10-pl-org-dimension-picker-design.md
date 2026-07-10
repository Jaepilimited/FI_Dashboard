# 조직별 P&L — 구분 기준 차원 교체 기능 — Design Spec

**Date:** 2026-07-10
**Status:** Approved
**Supersedes:** `2026-07-10-pl-view-editor-design.md` §2 "섹션 편집 범위 (조직별 파일럿 한정)" 행 — 그 결정은 "조직별은 구분 기준 차원 교체를 파일럿 범위 밖으로 미룬다"였음. 본 스펙은 그 유예를 해소하고, 조직별 화면에도 차원 교체를 추가한다.

---

## 1. Overview

이미 구현된 조직별(org) P&L 편집기(행 표시/숨김·순서, 커스텀 계산식 행, 섹션 표시/순서)에 새 기능을 더한다: 사이드 패널에 **"구분 기준" 드롭존**을 추가해, 지금 고정된 `Department`(전체/SK/유통 3단 계층) 대신 국가·상품라인·판매유형 등 다른 차원으로 섹션 구성을 바꿀 수 있게 한다.

**목적**(사용자 확인): 조직별로 보다가 특정 부서/섹션에 문제가 보이면, 같은 숫자를 국가별·상품별 등 다른 기준으로 쪼개서 원인을 진단할 수 있어야 한다.

---

## 2. Key Design Decisions

| 결정 | 선택 | 이유 |
|------|------|------|
| 레이아웃 | **지금과 완전히 동일** — 값마다 세로로 쌓인 전체 22행 P&L 테이블(굵은 행 클릭 → 세부 계정, 접기/펼치기) | 사용자가 명시적으로 확정. 기존 `renderTable` 함수를 그대로 재사용 — 신규 렌더링 로직 없음 |
| 구분 기준 후보 | `/api/pl`이 이미 지원하는 8개 차원 전부: `Department`(부서, 기본값), `Line`(라인), `Category`(카테고리), `Country`(국가), `Continent2`(대륙), `Customer`(거래처), `Sales_Type`(판매유형), `Group`(그룹) | 백엔드가 이미 전부 지원하므로 신규 쿼리 불필요. 사용자가 "8개 전부"를 명시적으로 선택 |
| Department가 아닐 때 섹션 구성 | **매출 기준 상위 10개 + "기타"** 자동 집계, 개별 값 표시/숨김·순서변경은 없음 | 기존 상품별/지역별 화면의 top10+기타 관례(`2026-07-06-region-product-top10-others-design.md`)와 통일. 값이 많을 때(국가 20개+) 성능·가독성 보호 |
| Department일 때 | 기존 동작 100% 그대로 — Brand→본부→부서 3단 계층, 이미 구현된 섹션 표시/순서 편집 그대로 사용 | `state.plViewConfig.org`가 `null`이거나 `sections.dim`이 없거나 `'Department'`이면 기존 `renderOrgPl` 코드 경로 완전 무변경 (기본 렌더링 불변 보장 유지) |
| 브랜드 × 차원 동시 교차 | **없음** — 구분 기준은 한 번에 하나만 적용(브랜드 분할과 새 차원 분할을 동시에 하지 않음) | 2차원 피벗은 범위 밖. Department가 아닐 때는 브랜드 필터 없이 전사 기준으로 그 차원을 쪼갬 |
| 추가 드릴다운 | **없음** — 차원을 바꾼 상태에서 그 안을 또 다른 차원으로 재드릴은 지원 안 함 | 1단계 교체만. 여러 단계 피벗은 범위 밖 |
| 행 편집(순서/숨김/계산식) | 구분 기준과 무관하게 그대로 동작 | 행은 P&L 계정 구조 자체이므로 어떤 차원으로 섹션을 나누든 동일 |

---

## 3. Config Schema 확장

기존 `2026-07-10-pl-view-editor-design.md` §3-2의 `sections` 객체에 필드 추가:

```json
{
  "sections": {
    "dim": "Country",
    "order": ["all", "SK", "UM"],
    "hidden": [],
    "deptOverrides": {}
  }
}
```

- `sections.dim`: 8개 차원 컬럼명 중 하나(`Department`|`Line`|`Category`|`Country`|`Continent2`|`Customer`|`Sales_Type`|`Group`). 생략 또는 `'Department'`이면 기존 동작.
- `dim !== 'Department'`일 때는 `sections.order`/`sections.hidden`/`deptOverrides`가 **무시됨**(top10+기타는 자동 계산이라 사용자가 개별 선택할 대상이 없음) — UI에서도 이 상태일 땐 기존 섹션 체크리스트 대신 안내 문구만 표시.

---

## 4. Frontend Architecture

### 4-1. 유효 차원 계산

```
plEffectiveSectionDim(screenId) → state.plViewConfig[screenId]?.sections?.dim || 'Department'
```

### 4-2. 데이터 로드 분기 (`loadCplData`/`_cplDimCol`)

- `_cplDimCol()`의 `cat==='org'` 분기: 지금은 무조건 `'Department'` 반환 → `plEffectiveSectionDim('org')` 반환하도록 변경.
- `loadCplData()`의 org 분기:
  - `dim==='Department'`: 기존 그대로 — `brand=SK`/`brand=UM`/무필터 3개 병렬 fetch.
  - `dim!=='Department'`: **무필터 1개 fetch만** (`/api/pl?dim=<선택차원>`, 브랜드 파라미터 없음) — 전사 기준으로 그 차원 값별 집계.
- `sections.dim`이 바뀌면(드롭존에 새 칩을 놓으면) `state.cplData=null` 리셋 후 `loadCplData()` 재호출 — 기존에 카테고리 전환 시 `applyAll()`이 하는 것과 동일한 패턴.

### 4-3. 렌더링 분기 (`renderOrgPl`)

- `dim==='Department'`: 기존 코드 100% 무변경.
- `dim!=='Department'`: 새 렌더 경로(`renderOrgPlByDim`) —
  1. `byNode`(값 이름 → all 필드들)의 각 값에 대해 매출 합계 계산, 내림차순 정렬.
  2. "전체" 블록(항상 첫 번째, 전사 총합 — 기존과 동일 의미) → 상위 10개 값 블록 → "기타" 블록(11번째부터 합산).
  3. 각 블록은 기존 `renderTable(M, ...)`을 그대로 호출(행 편집·계산식 행 반영 동일하게 적용) — 본부/부서 하위 드릴 단계만 없음(평평한 1단계).

### 4-4. 사이드 패널 UI

섹션 편집기 상단에 추가:

```
구분 기준
┌─────────────────────────┐
│  [ Department ▾ 로 표시 ]  │  ← 드롭존, 현재 선택값 표시
└─────────────────────────┘
필드: [부서] [라인] [카테고리] [국가] [대륙] [거래처] [판매유형] [그룹]  ← 드래그 가능한 칩
```

- 칩을 드롭존에 드래그하면 `cfg.sections.dim = <필드명>` 저장 → 재렌더(재fetch 트리거).
- `dim!=='Department'`일 때는 기존 "섹션(전체/SK/유통)" 체크리스트 대신 문구 표시: `"매출 기준 상위 10개 + 기타 자동 표시"`.
- Department로 되돌리면(드롭존에 "Department" 칩을 다시 놓으면) 기존 섹션 체크리스트가 다시 나타남.

### 4-5. CSS

기존 `pl-edit-*` 네임스페이스 재사용. 신규: `pl-edit-dim-dropzone`, `pl-edit-dim-chip` (기존 `pl-edit-token-chip` 스타일과 유사하게).

---

## 5. Non-Goals (이번 범위 제외)

- 브랜드 × 차원 동시 교차(2차원 피벗)
- 차원 교체 후 추가 드릴다운(다단계 피벗)
- `dim!=='Department'`일 때 개별 값 표시/숨김·순서변경(top10+기타는 자동)
- 조직별 외 4개 화면(이미 §9에서 예정된 확장 — 그쪽은 애초에 평평한 `CPL_SEC_DEFS` 구조라 차원 교체가 더 자연스러움, 별도 작업)

---

## 6. Files to Change (예상)

| 파일 | 변경 내용 |
|------|-----------|
| `templates/dashboard_v2.html` | `_cplDimCol()`/`loadCplData()` org 분기 수정, `plEffectiveSectionDim`/`renderOrgPlByDim` 신규, 구분 기준 드롭존 UI + 드래그 핸들러, `renderOrgPl()` 진입부에서 dim에 따라 기존 경로/신규 경로 분기 |

백엔드(`app_v2.py`) 변경 없음 — `/api/pl`이 이미 8개 차원 전부 지원.
