# FI Dashboard 설계 문서

**날짜:** 2026-05-21  
**상태:** 승인됨

---

## 개요

BigQuery의 매출/수익 데이터를 시각화하는 사내 대시보드. Flask 백엔드 + 단일 HTML 프론트엔드 구조. AD LDAPS 인증 + MariaDB 화이트리스트로 접근 제어.

---

## 파일 구조

```
FI Dashboard/
├── app.py                  # Flask 메인 (라우팅, 인증, API)
├── config.py               # AD/BigQuery/MariaDB 설정값
├── requirements.txt        # 패키지 목록
└── templates/
    ├── login.html          # 로그인 페이지
    ├── dashboard.html      # 메인 대시보드
    └── admin.html          # 사용자 관리 (관리자 전용)
```

---

## 인증 아키텍처

### 로그인 흐름
1. 사용자가 AD 계정(아이디/비밀번호) 입력
2. Flask → AD 서버(172.16.1.13) LDAPS 바인드 시도
3. 성공 시 MariaDB `dashboard_users` 테이블 화이트리스트 확인
4. 통과 시 Flask 세션 생성 → 대시보드 진입

### AD 서버 설정
- **IP:** 172.16.1.13
- **프로토콜:** LDAPS
- **바인드 계정:** cravercorp\joincraver
- **Search Base:** OU=Users,OU=Craver_Accounts,DC=ad,DC=cravercorp,DC=com

### MariaDB 화이트리스트 테이블
```sql
CREATE TABLE dashboard_users (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  username     VARCHAR(100) NOT NULL UNIQUE,
  display_name VARCHAR(200),
  role         ENUM('admin','viewer') DEFAULT 'viewer',
  is_active    BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
- **Host:** 127.0.0.1:3306
- **Database:** skin1004_ai
- **User:** skin1004

---

## 데이터 소스

**BigQuery 테이블:** `skin1004-319714.Sales_Integration.FI_Dashboard`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| Department | STRING | 부서 |
| Customer | STRING | 거래처 |
| Product_Name | STRING | 품명 |
| Product_Code | STRING | 품번 |
| Specification | STRING | 규격 |
| Sales_Quantity | INTEGER | 매출수량 |
| Sales_Amount | INTEGER | 매출액 |
| Cost_of_Sales | INTEGER | 매출원가 |
| Gross_Profit | INTEGER | 매출총이익 |
| SG_and_A_Expenses | INTEGER | 판관비 |
| Operating_Income | INTEGER | 영업이익 |
| Year_Month | STRING | 연월 (2026-01~04) |

---

## 대시보드 구성

### 필터 바 (항상 표시)
- 월(Year_Month) 멀티셀렉트
- 부서(Department) 드롭다운
- 거래처(Customer) 검색 드롭다운
- 품명(Product_Name) 텍스트 검색
- 적용 버튼 → AJAX로 모든 섹션 동시 갱신

### 섹션 1 — KPI 카드 (6개)
매출액 / 매출원가 / 매출총이익 / 매출총이익률 / 판관비 / 영업이익  
각 카드: 합계 값 + 전월 대비 증감률

### 섹션 2 — 월별 추이
라인 차트: 매출액 / 매출총이익 / 영업이익 3개 시리즈

### 섹션 3 — 4탭 분석
| 탭 | 차트 | 테이블 |
|---|---|---|
| 개요 | 부서별 Bar + 거래처 TOP10 도넛 | - |
| 부서별 | Stacked Bar | 부서별 상세 |
| 거래처별 | Horizontal Bar | 랭킹 |
| 품목별 | Bar Chart | 랭킹 |

### 사용자 관리 (/admin, admin 전용)
- 화이트리스트 사용자 목록
- 추가 / 삭제 / 역할 변경

---

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| POST | /login | LDAP 인증 + 화이트리스트 확인 |
| GET | /logout | 세션 종료 |
| GET | /api/filters | 부서·거래처 선택지 목록 |
| GET | /api/kpi | KPI 카드 데이터 |
| GET | /api/monthly-trend | 월별 추이 |
| GET | /api/department | 부서별 집계 |
| GET | /api/customer | 거래처별 랭킹 |
| GET | /api/product | 품목별 랭킹 |
| GET/POST | /admin/users | 사용자 관리 (admin만) |

---

## 기술 스택

- **백엔드:** Python Flask, ldap3, google-cloud-bigquery, PyMySQL, Flask-Session
- **프론트엔드:** Chart.js 4.4.7, Inter/Noto Sans KR 폰트, CSS Custom Properties
- **인증:** LDAPS (ldap3) + MariaDB 화이트리스트
- **데이터:** BigQuery REST API (서비스 계정 JSON 키)
