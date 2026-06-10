# 분석 빌더 탭 (Tableau-style) — Design Spec

**Date:** 2026-06-10  
**Status:** Approved

---

## 1. Overview

원시데이터 탭 아래에 "분석 빌더" 탭을 추가한다. Tableau의 Sheet 편집 UX를 재현하며, 드래그앤드롭으로 피벗/차트를 구성하고 유저별 다중 시트를 서버 DB에 저장한다.

---

## 2. Tab Registration

`dashboard.html`의 `CATEGORY_DEFS`에 아래 항목 추가:

```js
{ id:'tableau', label:'분석 빌더', icon:'layout-dashboard', path:[] }
```

---

## 3. Layout (3-Panel)

```
┌──────────────────────────────────────────────────────────────┐
│  [차트타입 12종 아이콘]  [Chart|Pivot 토글]  [시트탭 +-]  [저장]  │  ← 상단 툴바
├────────────────┬─────────────────────────────────────────────┤
│ DIMENSIONS     │  ROWS:    드롭존 (필드칩)                     │
│ (동적 목록)     │  COLUMNS: 드롭존 (필드칩)                     │
│                │  COLOR:   드롭존 (필드칩, 단일)                │
│ MEASURES       │  SIZE:    드롭존 (버블/산점도 전용)             │
│ (동적 목록)     │  FILTERS: 드롭존 + 값 선택 팝오버              │
│                ├─────────────────────────────────────────────┤
│                │  [ECharts 캔버스 or 피벗 테이블]               │
└────────────────┴─────────────────────────────────────────────┘
```

- **좌측 패널(220px):** 필드 목록. DIMENSIONS / MEASURES 섹션 구분. 각 필드는 드래그 가능한 칩.
- **우측 상단(선반 영역):** ROWS, COLUMNS, COLOR, SIZE, FILTERS 드롭존.
- **우측 하단(시각화 영역):** ECharts 캔버스(Chart 모드) 또는 피벗 테이블(Pivot 모드).
- **상단 툴바:** 차트 타입 선택, 모드 토글, 시트 탭, 저장 버튼.

---

## 4. Dynamic Field Discovery

### 4-1. API

```
GET /api/tableau/fields
```

- BQ `client.get_table(config.BQ_TABLE)`로 스키마 조회
- 컬럼 타입 기반 자동 분류:
  - `STRING, DATE, DATETIME, TIMESTAMP` → DIMENSION
  - `INT64, FLOAT64, NUMERIC, BIGNUMERIC` → MEASURE
- 결과는 `_query_cache`에 TTL 3600초로 캐시
- 응답:

```json
{
  "dimensions": ["Year_Month", "Group", "Department", "Country", "..."],
  "measures":   ["Sales_Amount", "Cost_of_Sales", "Gross_Profit", "..."]
}
```

### 4-2. 컬럼 추가 반영

- 탭 진입 시마다 `/api/tableau/fields` 호출 → 캐시 내 자동 반영
- 관리자는 기존 `/api/clear-cache` 또는 `/api/cache/clear`로 즉시 갱신 가능

### 4-3. Graceful Degradation

저장된 View Config에 존재하지 않는 필드가 포함되어 있으면 해당 필드만 조용히 제거하고 나머지 config는 그대로 로드.

---

## 5. Backend — DB Schema

`init_db()`에 추가:

```sql
CREATE TABLE IF NOT EXISTS user_views (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  username    VARCHAR(100) NOT NULL,
  name        VARCHAR(100) NOT NULL DEFAULT '시트 1',
  config      JSON NOT NULL,
  sort_order  INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_username (username)
)
```

---

## 6. Backend — API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/views` | login_required | 현재 유저의 시트 목록 (sort_order ASC) |
| POST | `/api/views` | login_required | 새 시트 생성, `{name, config}` |
| PUT | `/api/views/<id>` | login_required | 시트 수정 `{name?, config?}`, 본인 소유 확인 |
| DELETE | `/api/views/<id>` | login_required | 시트 삭제, 본인 소유 확인 |
| POST | `/api/tableau/query` | login_required | config → BQ 쿼리 실행 → 결과 반환 |
| GET | `/api/tableau/fields` | login_required | 동적 필드 목록 |

### 6-1. View Config JSON Schema

```json
{
  "chartType": "bar",
  "mode": "chart",
  "rows": ["Year_Month"],
  "columns": ["Group"],
  "measures": ["Sales_Amount", "Gross_Profit"],
  "color": "Sales_Type",
  "size": null,
  "filters": {
    "Sales_Type": ["B2B"],
    "Year_Month": ["2024-01", "2024-02"]
  },
  "sort": "desc",
  "limit": 500
}
```

### 6-2. Query Builder Logic (`/api/tableau/query`)

1. config의 rows + columns → `GROUP BY` 절 생성
2. measures → `SUM(...)` 집계 (허용된 컬럼명 화이트리스트로 SQL injection 방지)
3. filters → `WHERE ... IN UNNEST(...)` (기존 `build_bq_filters` 패턴 재사용)
4. sort + limit 적용
5. 결과 JSON 반환 (`{columns: [...], rows: [[...], ...]}`)

**보안:** measures, rows, columns 필드명은 `/api/tableau/fields`가 반환한 화이트리스트와 대조 후 BQ 쿼리 조립. 직접 문자열 삽입 없음.

---

## 7. Frontend — Drag and Drop

- HTML5 Drag API 사용 (외부 라이브러리 추가 없음)
- 필드칩 `draggable="true"` + `dragstart` 이벤트
- 드롭존: `dragover` / `drop` 이벤트 핸들러
- 칩 내 `×` 버튼으로 선반에서 제거
- 선반 내 칩 순서 변경: `dragover` 시 삽입 위치 미리보기

---

## 8. Chart Types (13종, Apache ECharts CDN)

| # | 이름 | ECharts 타입 | ROWS 필드 | MEASURES |
|---|------|-------------|----------|----------|
| 1 | 막대(Bar) | `bar` | 1개 | 1+ |
| 2 | 누적막대(Stacked Bar) | `bar` + stack | 1+COLOR | 1 |
| 3 | 선(Line) | `line` | 1개 | 1+ |
| 4 | 영역(Area) | `line` + areaStyle | 1+COLOR | 1 |
| 5 | 누적영역(Stacked Area) | `line` + stack + area | 1+COLOR | 1 |
| 6 | 원형(Pie) | `pie` | 1개(카테고리) | 1 |
| 7 | 도넛(Donut) | `pie` + radius | 1개 | 1 |
| 8 | 폭포수(Waterfall) | `bar` 커스텀 | 1개 | 1 |
| 9 | 산점도(Scatter) | `scatter` | 1개 | 2(x,y) |
| 10 | 버블(Bubble) | `scatter` + symbolSize | 1개 | 3(x,y,size) |
| 11 | 히트맵(Heatmap) | `heatmap` | 2개(x,y) | 1 |
| 12 | 트리맵(Treemap) | `treemap` | 1+COLOR | 1 |
| 13 | 콤보(Bar+Line) | `bar`+`line` 혼합 | 1개 | 2+ |

---

## 9. Pivot Table Mode

- ROWS 선반 필드 → 행 그룹핑 키
- COLUMNS 선반 필드 → 열 그룹핑 키
- MEASURES → 교차 셀 값 (SUM)
- 소계 행/열 자동 추가
- 셀 값 기반 배경색 히트맵 옵션 (토글)

---

## 10. Sheet Management

- 상단 탭바에 시트 탭 렌더링 (Tableau Sheet Tab UX)
- `+` 버튼: 새 시트 생성, 기본명 "시트 N"
- 탭 더블클릭: 인라인 이름 편집 (blur/Enter → PUT 저장)
- 탭 우클릭 컨텍스트 메뉴: 이름 변경 / 삭제
- **자동저장:** 필드 배치·차트 타입 변경 후 3초 디바운스 → PUT `/api/views/<id>`
- 첫 방문 시 기본 시트 1개 자동 생성

---

## 11. Theming

기존 `--accent`, `--surface`, `--border`, `--text` CSS 변수 그대로 사용. 다크/라이트 테마 자동 대응. ECharts 테마도 현재 테마 감지 후 적용.

---

## 12. Files to Change

| 파일 | 변경 내용 |
|------|----------|
| `app_v2.py` | `init_db()` 테이블 추가, 6개 API 엔드포인트 추가 |
| `templates/dashboard.html` | `CATEGORY_DEFS` 탭 추가, 분석 빌더 UI 전체, ECharts CDN 추가 |
