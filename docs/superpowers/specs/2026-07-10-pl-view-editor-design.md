# 손익계산서 편집 기능 (PL View Editor) — Design Spec

**Date:** 2026-07-10
**Status:** Implemented (pilot — org screen)

---

## 1. Overview

현재 5개 화면(요약/조직별/지역별/상품별/판매유형별)의 손익계산서 표는 전부 고정된 구조(`CPL_ROW_DEFS` 22개 행, 하드코딩된 섹션 구성)로 렌더링된다. 이를 화면별로:

- 행(계정 항목) 표시/숨김·순서 변경, 커스텀 계산식 행 추가
- 섹션(브랜드/차원 구분) 구성 편집
- 이름 붙인 여러 개의 "저장된 뷰"로 개인별 서버 저장 (다른 사용자는 항상 "기본"을 봄)

가 가능하게 만든다. **파일럿 범위: 조직별(org) 화면 1개**에서 전체 기능을 완성·검증한 뒤 나머지 4개 화면으로 확장한다 (본 스펙은 파일럿만 다루고, 확장은 §9에 후속 작업으로 기록).

기존 "커스텀 분석탭"(`docs/superpowers/specs/2026-06-10-tableau-builder-design.md`)과는 별개의 **전용 편집기**로 새로 만든다. 이유: P&L은 소계·%행·계층 구조(판관비 하위 5개 세부계정)가 고정 수식으로 얽혀 있어, 범용 피벗 선반에 자유 매핑하면 숫자가 깨질 위험이 있다 (§2 결정 참조).

---

## 2. Key Design Decisions

| 결정 | 선택 | 이유 |
|------|------|------|
| 편집 UI 구현 방식 | 전용 편집기 신규 제작 | P&L 도메인(소계·계층) 안전성 우선. 커스텀 분석탭의 `tbl-shelf` 드래그앤드롭 *시각 언어*(칩, 드롭존 하이라이트)는 재사용하되 컴포넌트는 별도 |
| 행 재배치 범위 | 최상위 굵은 행끼리만 자유 재배치. 판관비 하위 세부계정(광고선전비/물류비/수수료/인건비/기타)은 자기 그룹 내에서만 재배치 | 소계값은 백엔드 사전계산이라 순서 무관하지만, `toggle`/`member` 그룹 구조가 깨지면 렌더링 자체가 깨짐 |
| 커스텀 계산식 행 | 기존 22개 지표(`sales`,`cogs`,`gross`,`sgaD`,`sgaD.adv`,...,`op`)만 토큰으로 허용하는 사칙연산(`+ - * / ( )`, 숫자 리터럴) | 헤드카운트 등 미보유 데이터 참조 방지. 클라이언트에서 매 기간 배열 재계산이면 충분 (신규 백엔드 쿼리 불필요) |
| 수식 평가 방법 | 화이트리스트 토크나이저 + 재귀하강 파서 (직접 구현, `eval`/`Function` 금지) | 사용자 입력 문자열을 그대로 실행하면 XSS/코드 인젝션 위험 |
| 섹션 편집 범위 (조직별 파일럿 한정) | "전체/SK/유통" 3개 섹션의 표시·순서·부서 소속(SK↔유통↔제외)만 편집. 구분 기준 차원 자체를 Department→다른 차원(예: Sales_Type)으로 교체하는 것은 **파일럿 범위 밖** | 조직별은 Brand→본부→부서 3단 계층(`_BRAND_DIV`/`_DIV_DEPT_MAP`)이 Department에 강하게 결합되어 있어, 임의 차원 교체는 계층 구조 자체를 재설계해야 함. 반면 상품별/지역별/판매유형별은 이미 단일 차원 기반 평평한 섹션 리스트(`CPL_SEC_DEFS`)라 차원 교체가 훨씬 자연스러움 → **차원 교체 기능은 §9 확장 단계에서 상품별/지역별/판매유형별에 먼저 적용** |
| 뷰 저장 위치 | 기존 `user_views` 테이블에 `kind`/`screen_id` 컬럼 추가해 재사용 (신규 테이블 없음) | 커스텀 분석탭이 이미 동일 패턴(개인별 다중 이름-저장 뷰, 서버 DB)을 갖고 있어 테이블/CRUD API 중복 생성이 불필요 |
| "기본" 뷰의 실체 | DB row 아님. `view=null` 선택 시 현재 하드코딩 렌더링 그대로 | 다른 사용자가 항상 보는 화면과 100% 동일해야 하므로, 기본값은 코드 경로로 유지하고 커스텀 config는 그 위에 얹는 방식 |

---

## 3. Data Model

### 3-1. `user_views` 테이블 확장

```sql
ALTER TABLE user_views ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'tableau';
ALTER TABLE user_views ADD COLUMN IF NOT EXISTS screen_id VARCHAR(20) DEFAULT NULL;
```

- 기존 커스텀 분석탭 시트: `kind='tableau'`, `screen_id=NULL` (기본값이라 마이그레이션 불필요, 기존 행 그대로 동작)
- PL 뷰: `kind='pl'`, `screen_id='org'` (파일럿), 확장 시 `'product'|'region'|'sales'|'overview'`

### 3-2. PL View Config JSON (kind='pl')

```json
{
  "rows": {
    "blockOrder": ["sales", "gross", "sgaD", "direct", "sgaO", "contrib", "sgaC", "op"],
    "subOrder": { "sgaD": ["adv", "log", "fee", "hr", "etc"], "sgaO": ["adv", "log", "fee", "hr", "etc"], "sgaC": ["adv", "log", "fee", "hr", "etc"] },
    "hidden": ["sgaD.fee"],
    "custom": [
      { "id": "custom_1", "label": "매출총이익률", "formula": "gross / sales * 100", "afterId": "gross" }
    ]
  },
  "sections": {
    "order": ["all", "SK", "UM"],
    "hidden": [],
    "deptOverrides": {}
  }
}
```

**행 순서 모델 (블록 단위) — 셀프리뷰로 정밀화:** `CPL_ROW_DEFS`를 그대로 훑으면 `cogs`(매출원가, `member:'gross'`)가 자신의 그룹 앵커인 `gross`(매출총이익, `toggle:'gross'`)보다 배열상 **앞**에 위치한다 — `sgaD`류(앵커가 세부계정보다 먼저 나옴)와 반대 패턴이라, "서브 행은 항상 부모 뒤"라는 단순 규칙이 깨진다. 따라서 최상위 재배치 단위를 8개 **고정 블록**으로 명시한다:

| 블록 앵커 | 포함 행 (원래 순서 고정) | 재배치 가능 범위 |
|-----------|--------------------------|-------------------|
| `sales`   | `sales` | 블록 전체가 다른 블록과 자유 순서 교환 |
| `gross`   | `cogs`, `gross` (이 순서 고정) | 블록 전체 이동만 가능. `cogs`/`gross` 내부 순서·숨김 불가 |
| `sgaD`    | `sgaD`, `sgaD.adv/.log/.fee/.hr/.etc` | 블록 이동 가능 + 세부계정 5개는 서로 순서 변경·숨김 가능 |
| `direct`  | `direct` | 블록 전체 이동만 |
| `sgaO`    | `sgaO` + 세부계정 5개 | `sgaD`와 동일 |
| `contrib` | `contrib` | 블록 전체 이동만 |
| `sgaC`    | `sgaC` + 세부계정 5개 | `sgaD`와 동일 |
| `op`      | `op` | 블록 전체 이동만 |

- `rows.blockOrder`: 8개 앵커 id의 순열. 생략되면 원래 순서.
- `rows.subOrder`: `sgaD`/`sgaO`/`sgaC` 블록 안 세부계정 5개(`adv`/`log`/`fee`/`hr`/`etc`)의 순서만 재배치. `cogs`는 `subOrder` 대상이 아님(고정).
- `rows.hidden`: 숨길 행 id 목록. **블록 앵커 8개(`sales`,`gross`,`sgaD`,`direct`,`sgaO`,`contrib`,`sgaC`,`op`)와 `cogs`는 숨김 불가** — UI에서 체크박스 비활성화. 이유: 앵커는 `toggle`로 세부계정 펼침을 제어하는 구조적 필수 행이고, `cogs`는 그 자체가 유일한 고정 멤버라 그룹 구조상 항상 렌더링되어야 함. 세부계정 15개(`sgaD.adv` 등)만 자유롭게 숨김 가능.
- `rows.custom`: 계산식 행. `formula`는 §4 파서로 검증. `afterId`는 8개 블록 앵커 id 중 하나 — 해당 블록 맨 끝에 삽입.
- `sections.order`/`hidden`: `'all'|'SK'|'UM'` 값의 표시 순서·숨김만 제어 (§2 결정에 따라 파일럿은 차원 자체는 고정)
- `sections.deptOverrides`: 파일럿 확장 옵션 — 특정 부서를 SK↔UM 사이 재배정하거나 제외. `{ "부서명": "SK"|"UM"|"exclude" }`. **1차 구현에서는 빈 객체 허용만 하고 UI는 생략 가능** (Nice-to-have, 아래 §8 우선순위 참조)

---

## 4. Formula Parser (커스텀 계산식 행)

- 허용 토큰: 22개 metric id (`sales`,`cogs`,`gross`,`op`,`direct`,`contrib`,`sgaD`,`sgaD.adv`,`sgaD.log`,`sgaD.fee`,`sgaD.hr`,`sgaD.etc`,`sgaO`,`sgaO.*`,`sgaC`,`sgaC.*`), 정수/소수 리터럴, `+ - * / ( )`, 공백
- 구현: 정규식 토크나이저 → 재귀하강 파서 (곱셈/나눗셈 우선순위 → 덧셈/뺄셈) → AST → 평가 함수. `eval`/`new Function` 사용 금지.
- 평가 시점: `cplRowValue(M, id)`가 반환하는 월별 배열과 동일한 형태로, 커스텀 행도 기간별 배열을 리턴 (각 인덱스마다 AST 평가 — division by zero는 `0` 처리 후 `PL_EMPTY` 표시)
- 저장 검증: 서버는 `formula` 문자열을 그대로 JSON에 저장만 하고 실행하지 않음 (실행은 항상 클라이언트). 저장 시점에 프론트에서 파싱 실패하면 저장 자체를 막음 (에러 토스트).
- 미지원 토큰(예: 존재하지 않는 metric id, 함수 호출 등) → 파싱 에러로 저장 차단, 에러 메시지에 허용 토큰 목록 표시.

---

## 5. Frontend Architecture

### 5-1. 진입점

`renderOrgPl()`의 카드 헤더(`.card-hd`)에 편집 토글 아이콘 버튼 추가 (`data-lucide="pencil"` 또는 `sliders-horizontal`). 클릭 시 `state.plEdit.org = true`, 카드 우측에 `renderPlEditPanel('org')`가 렌더한 패널이 열림 (기존 카드 레이아웃을 `display:flex`로 좌우 분할, 패널 폭 280px 고정, `card-body-flush` 안에 나란히 배치).

패널 상단에 뷰 선택 드롭다운:
```
뷰: [ 기본            ▾ ]
    ├ 기본
    ├ 내 월말 보고용
    └ 분기 임원보고용
    ────────────────
    + 현재 상태를 새 뷰로 저장
```

### 5-2. State

```js
state.plEdit = { org: false, product: false, region: false, sales: false, overview: false };  // 편집 모드 on/off
state.plViews = { org: [], product: [], ... };   // 서버에서 로드한 저장된 뷰 목록 (kind=pl, screen=<id>)
state.plActiveView = { org: null, ... };          // 현재 선택된 view id (null = 기본)
state.plViewConfig = { org: null, ... };          // 선택된 view의 config (null = 기본 하드코딩 렌더링)
```

- 화면(org 등) 최초 진입 시 `loadPlViews('org')` → `GET /api/views?kind=pl&screen=org`
- `renderOrgPl()`는 `state.plViewConfig.org`가 있으면 §3-2 config를 반영해 `CPL_ROW_DEFS`/섹션 리스트를 머지한 파생 목록으로 렌더, 없으면 지금과 완전히 동일한 코드 경로

### 5-3. 행 편집 패널 UI

- 체크리스트 (드래그 핸들 `⠿` + 체크박스 + 라벨), 최상위 행은 굵게, 서브 행은 들여쓰기
- 드래그: 최상위 행끼리는 리스트 전체에서 자유 이동, 서브 행은 자신의 부모 그룹 범위 밖으로 드롭 시 스냅백 (시각적으로 그룹 경계에 구분선 표시)
- 하단 `+ 계산식 행 추가` 버튼 → 인라인 폼(이름 입력 + 수식 입력 + `sales`, `gross` 등 클릭 삽입 가능한 토큰 칩 목록 + 실시간 파싱 에러 표시)

### 5-4. 섹션 편집 패널 UI

- 체크리스트: `전체`, `SK 브랜드`, `유통본부` — 체크(표시) + 드래그(순서)
- (Nice-to-have, 1차 구현 선택사항) 부서 재배정: 부서 목록에서 드래그로 SK↔유통 사이 이동 또는 "제외" 존으로 이동

### 5-5. CSS 네임스페이스

`tbl-*` (커스텀 분석탭)와 충돌 방지 위해 `pl-edit-*` 프리픽스 신규 정의 (`pl-edit-panel`, `pl-edit-row-chip`, `pl-edit-dropzone` 등). 드래그오버 하이라이트·칩 스타일은 기존 `tbl-shelf`류 CSS 값을 참고해 시각적 일관성만 맞춤 (색상 변수 재사용, 클래스는 독립).

---

## 6. Backend API 변경

### 6-1. 기존 엔드포인트 확장

| Method | Path | 변경 내용 |
|--------|------|-----------|
| GET | `/api/views` | 쿼리파라미터 `kind`(기본 `tableau`), `screen`(kind=pl일 때 필수) 추가. `WHERE username=%s AND kind=%s [AND screen_id=%s]` |
| POST | `/api/views` | body에 `kind`(기본 `tableau`), `screen` 추가 필드. `kind='pl'`이면 `screen` 필수(400 검증) |
| PUT | `/api/views/<id>` | 변경 없음 (소유권 검사 username+id로 이미 충분, kind 무관) |
| DELETE | `/api/views/<id>` | 변경 없음 |

- 기존 커스텀 분석탭 프론트 호출부(`GET/POST /api/views`)는 `kind` 파라미터를 안 보내므로 자동으로 `kind='tableau'` 기본값 적용 → **하위 호환 보장, 프론트 기존 코드 수정 불필요**

### 6-2. `init_db()` 변경

§3-1의 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 2줄 추가 (기존 `password_hash` 컬럼 추가와 동일 패턴, `app_v2.py:202-203` 참조).

---

## 7. Non-Goals (파일럿 범위 제외)

- 조직별 화면에서 구분 기준 차원 자체 교체 (§2 결정)
- 편집 내용의 타 사용자 공유/협업 (개인별 저장만, §설계 확정)
- 열(기간 단위: 월별/분기별/반기별) 편집 — 이미 기존 UI로 전환 가능하므로 신규 개발 대상 아님
- 커스텀 계산식 행에서 미보유 데이터(헤드카운트 등) 참조

---

## 8. 구현 우선순위 (파일럿 내부)

1. 백엔드: `user_views` 컬럼 확장 + `/api/views` kind/screen 파라미터
2. 프론트: 뷰 CRUD (로드/저장/이름변경/삭제) + "기본" 폴백 렌더링 — 커스텀 config 없이도 기존과 동일하게 보이는지 먼저 검증
3. 프론트: 행 표시/숨김 + 순서 변경 (그룹 제약 포함) 반영 렌더링
4. 프론트: 계산식 행 파서 + 추가/삭제 UI
5. 프론트: 섹션 표시/순서 편집 (전체/SK/유통)
6. (선택) 부서 재배정(`deptOverrides`) — 시간 허용 시

---

## 9. 확장 단계 (파일럿 검증 후, 별도 작업으로 진행)

- 지역별/상품별/판매유형별/요약 4개 화면에 동일 엔진 적용 (`screen_id` 값만 다르게)
- 상품별/지역별/판매유형별은 `CPL_SEC_DEFS` 기반 평평한 구조라, 이 단계에서 **구분 기준 차원 자체를 드래그로 교체**하는 기능을 여기서 먼저 완성 (§2 결정에 따른 후순위 배치)
- 조직별에도 차원 교체가 필요하다고 판단되면, 확장 단계 검증 후 별도 스펙으로 재설계

---

## 10. Files to Change (파일럿)

| 파일 | 변경 내용 |
|------|-----------|
| `app_v2.py` | `init_db()` ALTER TABLE 2줄, `/api/views` GET/POST에 kind/screen 파라미터 처리 |
| `templates/dashboard_v2.html` | 편집 토글 버튼, `renderPlEditPanel()`, 뷰 CRUD 프론트 함수, 행/섹션 편집 UI, 수식 파서, `renderOrgPl()`이 `state.plViewConfig.org` 반영하도록 수정, 신규 CSS(`pl-edit-*`) |
