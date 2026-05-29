# FI Dashboard — 설치 및 실행 가이드

## 사전 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 |
| MariaDB / MySQL | 실행 중이어야 함 |
| GCP 서비스 계정 키 | `.json` 파일 보유 |

---

## 1. 레포 클론 & 이동

```bash
git clone https://github.com/Jaepilimited/FI_Dashboard.git
cd FI_Dashboard
```

---

## 2. 가상환경 생성 & 패키지 설치

```bash
# Mac / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

---

## 3. config.py 설정 (최초 1회)

```bash
cp config.example.py config.py
```

`config.py` 를 열어 아래 항목을 채웁니다.

```python
# ── Active Directory (사내 LDAP 로그인) ──────────────────────────
AD_HOST        = '172.16.1.13'          # AD 서버 IP
AD_PORT        = 636                    # LDAPS 포트
AD_DOMAIN      = 'cravercorp'
AD_BIND_USER   = r'cravercorp\joincraver'
AD_BIND_PASS   = '...'                  # AD bind 비밀번호
AD_SEARCH_BASE = 'OU=Users,OU=Craver_Accounts,DC=ad,DC=cravercorp,DC=com'

# ── MariaDB (세션·유저 DB) ────────────────────────────────────────
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_NAME = 'skin1004_ai'
DB_USER = 'skin1004'
DB_PASS = '...'                         # DB 비밀번호

# ── BigQuery ──────────────────────────────────────────────────────
BQ_KEY_PATH = r'/path/to/service-account.json'   # GCP 키 파일 절대경로
BQ_PROJECT  = 'skin1004-319714'
BQ_TABLE    = 'skin1004-319714.Sales_Integration.FI_Final'

# ── Flask ─────────────────────────────────────────────────────────
SECRET_KEY = '랜덤한-비밀-문자열'       # 32자 이상 권장
```

> ⚠️ `config.py` 는 `.gitignore` 에 포함되어 있어 커밋되지 않습니다.

---

## 4. DB 초기화 (최초 1회)

```bash
python setup_db.py        # 테이블 생성
python create_admin.py    # 관리자 계정 생성
```

---

## 5. 대시보드 템플릿 최신화 (업데이트 시)

배포된 최신 `dashboard_v2.html` 파일을 받아 교체합니다.

```bash
cp ~/Downloads/dashboard_v2.html templates/dashboard_v2.html
```

---

## 6. 실행

```bash
python app_v2.py
```

브라우저에서 `http://127.0.0.1:5001` 접속

> 포트 변경이 필요하면 `app_v2.py` 마지막 줄의 `port=5001` 수정

---

## 파일 구조

```
FI_Dashboard/
├── app_v2.py            # Flask 앱 (메인)
├── config.py            # ⚠️ 실제 접속 정보 (커밋 금지)
├── config.example.py    # 설정 템플릿
├── requirements.txt
├── setup_db.py
├── create_admin.py
├── templates/
│   ├── dashboard_v2.html
│   ├── login.html
│   └── signup.html
└── static/
```

---

## 주요 API 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /dashboard` | 메인 대시보드 |
| `GET /api/prefetch` | KPI·트렌드·브레이크다운 일괄 조회 |
| `GET /api/export-csv` | CSV 청크 다운로드 |
| `POST /api/cache/clear` | BigQuery 캐시 초기화 (관리자) |
