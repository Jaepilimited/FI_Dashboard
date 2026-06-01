# FI Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flask 기반 FI 수익성 대시보드 — AD LDAPS 인증 + MariaDB 화이트리스트, BigQuery 실시간 데이터, Chart.js 시각화

**Architecture:** Flask 백엔드가 LDAP 인증·BigQuery 쿼리·MariaDB 사용자 관리를 처리하고, Jinja2 템플릿(login/dashboard/admin.html)이 AJAX로 API를 호출해 차트를 갱신한다.

**Tech Stack:** Python Flask 3, ldap3, pymysql, google-cloud-bigquery, Chart.js 4.4.7, Inter/Noto Sans KR

---

## 파일 맵

| 경로 | 역할 |
|---|---|
| `app.py` | Flask 앱 전체 (라우트, 인증, API, 어드민) |
| `config.py` | AD/BQ/MariaDB 설정 상수 |
| `requirements.txt` | 패키지 목록 |
| `templates/login.html` | 로그인 페이지 |
| `templates/dashboard.html` | 메인 대시보드 |
| `templates/admin.html` | 사용자 관리 (admin 전용) |

---

## Task 1: 의존성 및 설정 파일

**Files:**
- Create: `requirements.txt`
- Create: `config.py`

- [ ] **Step 1: requirements.txt 작성**

```
flask>=3.0.0
ldap3>=2.9.1
pymysql>=1.1.0
google-cloud-bigquery>=3.17.0
google-auth>=2.28.0
pandas>=2.2.0
pyarrow>=15.0.0
```

- [ ] **Step 2: config.py 작성**

```python
# AD (Active Directory)
AD_HOST = '172.16.1.13'
AD_PORT = 636
AD_DOMAIN = 'cravercorp'
AD_BIND_USER = r'cravercorp\joincraver'
AD_BIND_PASS = 'Craverworknet!'
AD_SEARCH_BASE = 'OU=Users,OU=Craver_Accounts,DC=ad,DC=cravercorp,DC=com'

# MariaDB
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_NAME = 'skin1004_ai'
DB_USER = 'skin1004'
DB_PASS = 'skin1004!'

# BigQuery
BQ_KEY_PATH = r'C:/json_key/skin1004-319714-60527c477460.json'
BQ_PROJECT = 'skin1004-319714'
BQ_TABLE = 'skin1004-319714.Sales_Integration.FI_Dashboard'

# Flask
SECRET_KEY = 'fi-dashboard-secret-key-2026'
```

- [ ] **Step 3: 패키지 설치**

```
pip install -r requirements.txt
```

Expected: 오류 없이 완료

---

## Task 2: MariaDB 화이트리스트 테이블 생성

**Files:**
- 없음 (DB 직접 실행)

- [ ] **Step 1: MariaDB 접속 후 테이블 생성**

```sql
USE skin1004_ai;

CREATE TABLE IF NOT EXISTS dashboard_users (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  username     VARCHAR(100) NOT NULL UNIQUE COMMENT 'AD sAMAccountName (소문자)',
  display_name VARCHAR(200) DEFAULT '',
  role         ENUM('admin','viewer') DEFAULT 'viewer',
  is_active    TINYINT(1) DEFAULT 1,
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 최초 관리자 등록 (username은 실제 AD 아이디로 교체)
INSERT INTO dashboard_users (username, display_name, role)
VALUES ('admin_user', '관리자', 'admin');
```

- [ ] **Step 2: 등록 확인**

```sql
SELECT * FROM dashboard_users;
```

Expected: 방금 삽입한 행 1건 조회

---

## Task 3: app.py — 뼈대 + 인증 함수

**Files:**
- Create: `app.py`

- [ ] **Step 1: app.py 기본 구조 작성**

```python
import ssl
import functools
import pymysql
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from ldap3 import Server, Connection, NTLM, Tls, ALL
from google.cloud import bigquery
from google.oauth2 import service_account
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


# ─── MariaDB helper ────────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASS,
        database=config.DB_NAME, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# ─── BigQuery helper ───────────────────────────────────────────────
def get_bq_client():
    creds = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    return bigquery.Client(project=config.BQ_PROJECT, credentials=creds)


# ─── LDAP 인증 ─────────────────────────────────────────────────────
def authenticate_ldap(username, password):
    """AD LDAPS로 사용자 자격증명 검증. 성공=True, 실패=False"""
    tls = Tls(validate=ssl.CERT_NONE)
    server = Server(config.AD_HOST, port=config.AD_PORT, use_ssl=True, tls=tls)
    try:
        conn = Connection(
            server,
            user=f'{config.AD_DOMAIN}\\{username}',
            password=password,
            authentication=NTLM,
            auto_bind=True
        )
        conn.unbind()
        return True
    except Exception:
        return False


# ─── 화이트리스트 확인 ─────────────────────────────────────────────
def check_whitelist(username):
    """MariaDB 화이트리스트에서 활성 사용자 조회. 없으면 None"""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT username, display_name, role FROM dashboard_users "
                "WHERE username=%s AND is_active=1",
                (username.lower(),)
            )
            return cur.fetchone()
    finally:
        db.close()


# ─── 로그인 필수 데코레이터 ────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if session['user'].get('role') != 'admin':
            return jsonify({'error': '권한이 없습니다'}), 403
        return f(*args, **kwargs)
    return wrapper
```

- [ ] **Step 2: 문법 오류 확인**

```
python -c "import app"
```

Expected: 오류 없음 (ImportError 없이 종료)

---

## Task 4: app.py — 로그인·로그아웃·메인 라우트

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 로그인/로그아웃/대시보드 라우트 추가 (app.py 끝에 이어붙이기)**

```python
# ─── 로그인 ────────────────────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = '아이디와 비밀번호를 입력하세요.'
        elif not authenticate_ldap(username, password):
            error = '아이디 또는 비밀번호가 올바르지 않습니다.'
        else:
            user = check_whitelist(username)
            if not user:
                error = '접근 권한이 없습니다. 관리자에게 문의하세요.'
            else:
                session['user'] = {
                    'username': user['username'],
                    'display_name': user['display_name'] or username,
                    'role': user['role']
                }
                return redirect(url_for('dashboard'))

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=session['user'])
```

- [ ] **Step 2: Flask 실행 테스트**

```
python app.py
```

브라우저에서 `http://127.0.0.1:5000` → `/login` 리다이렉트 확인

---

## Task 5: app.py — BigQuery 필터 헬퍼 + /api/filters, /api/kpi

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 필터 WHERE절 빌더 함수 추가**

```python
# ─── BigQuery 필터 빌더 ────────────────────────────────────────────
def build_bq_filters(args):
    """request.args에서 BigQuery WHERE절과 파라미터 반환"""
    conditions = []
    params = []

    months = args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    department = args.get('department', '').strip()
    if department:
        conditions.append('Department = @department')
        params.append(bigquery.ScalarQueryParameter('department', 'STRING', department))

    customer = args.get('customer', '').strip()
    if customer:
        conditions.append('Customer = @customer')
        params.append(bigquery.ScalarQueryParameter('customer', 'STRING', customer))

    product = args.get('product', '').strip()
    if product:
        conditions.append('LOWER(Product_Name) LIKE LOWER(@product)')
        params.append(bigquery.ScalarQueryParameter('product', 'STRING', f'%{product}%'))

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    return where, params


def run_query(sql, params=None):
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    rows = client.query(sql, job_config=job_config).result()
    return [dict(row) for row in rows]
```

- [ ] **Step 2: /api/filters 엔드포인트 추가**

```python
@app.route('/api/filters')
@login_required
def api_filters():
    """부서·거래처 선택지 목록"""
    sql = f"""
        SELECT DISTINCT Department FROM `{config.BQ_TABLE}`
        WHERE Department IS NOT NULL ORDER BY Department
    """
    depts = [r['Department'] for r in run_query(sql)]

    sql2 = f"""
        SELECT DISTINCT Customer FROM `{config.BQ_TABLE}`
        WHERE Customer IS NOT NULL ORDER BY Customer
    """
    customers = [r['Customer'] for r in run_query(sql2)]

    sql3 = f"""
        SELECT DISTINCT Year_Month FROM `{config.BQ_TABLE}`
        ORDER BY Year_Month
    """
    months = [r['Year_Month'] for r in run_query(sql3)]

    return jsonify({'departments': depts, 'customers': customers, 'months': months})
```

- [ ] **Step 3: /api/kpi 엔드포인트 추가**

```python
@app.route('/api/kpi')
@login_required
def api_kpi():
    """KPI 카드 데이터 (합계 + 전체 대비 이익률)"""
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            SUM(Sales_Amount)       AS sales_amount,
            SUM(Cost_of_Sales)      AS cost_of_sales,
            SUM(Gross_Profit)       AS gross_profit,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SUM(SG_and_A_Expenses)  AS sga_expenses,
            SUM(Operating_Income)   AS operating_income,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin,
            SUM(Sales_Quantity)     AS sales_quantity
        FROM `{config.BQ_TABLE}`
        {where}
    """
    rows = run_query(sql, params)
    row = rows[0] if rows else {}
    # None → 0 처리
    result = {k: (float(v) if v is not None else 0) for k, v in row.items()}
    return jsonify(result)
```

---

## Task 6: app.py — /api/monthly-trend, /api/department, /api/customer, /api/product

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 월별 추이 엔드포인트**

```python
@app.route('/api/monthly-trend')
@login_required
def api_monthly_trend():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Year_Month,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SUM(Cost_of_Sales)     AS cost_of_sales
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Year_Month
        ORDER BY Year_Month
    """
    rows = run_query(sql, params)
    return jsonify(rows)
```

- [ ] **Step 2: 부서별 집계 엔드포인트**

```python
@app.route('/api/department')
@login_required
def api_department():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Department,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Department
        ORDER BY sales_amount DESC
    """
    rows = run_query(sql, params)
    return jsonify(rows)
```

- [ ] **Step 3: 거래처별 랭킹 엔드포인트**

```python
@app.route('/api/customer')
@login_required
def api_customer():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Customer,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Customer
        ORDER BY sales_amount DESC
        LIMIT 30
    """
    rows = run_query(sql, params)
    return jsonify(rows)
```

- [ ] **Step 4: 품목별 랭킹 엔드포인트**

```python
@app.route('/api/product')
@login_required
def api_product():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Product_Name,
            Product_Code,
            SUM(Sales_Quantity)    AS sales_quantity,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Product_Name, Product_Code
        ORDER BY sales_amount DESC
        LIMIT 30
    """
    rows = run_query(sql, params)
    return jsonify(rows)
```

- [ ] **Step 5: 앱 진입점 추가 (app.py 최하단)**

```python
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
```

---

## Task 7: app.py — /admin 라우트

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 어드민 라우트 추가**

```python
@app.route('/admin')
@admin_required
def admin():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM dashboard_users ORDER BY created_at DESC")
            users = cur.fetchall()
    finally:
        db.close()
    return render_template('admin.html', user=session['user'], users=users)


@app.route('/admin/users/add', methods=['POST'])
@admin_required
def admin_add_user():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    display_name = data.get('display_name', '').strip()
    role = data.get('role', 'viewer')
    if not username:
        return jsonify({'error': 'username 필수'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO dashboard_users (username, display_name, role) VALUES (%s,%s,%s)",
                (username, display_name, role)
            )
        db.commit()
        return jsonify({'ok': True})
    except pymysql.err.IntegrityError:
        return jsonify({'error': '이미 등록된 사용자'}), 409
    finally:
        db.close()


@app.route('/admin/users/<int:uid>/delete', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM dashboard_users WHERE id=%s", (uid,))
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()


@app.route('/admin/users/<int:uid>/role', methods=['POST'])
@admin_required
def admin_change_role(uid):
    data = request.get_json()
    role = data.get('role')
    if role not in ('admin', 'viewer'):
        return jsonify({'error': '잘못된 role'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE dashboard_users SET role=%s WHERE id=%s", (role, uid))
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()


@app.route('/admin/users/<int:uid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE dashboard_users SET is_active = NOT is_active WHERE id=%s", (uid,)
            )
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
```

---

## Task 8: templates/login.html

**Files:**
- Create: `templates/login.html`

- [ ] **Step 1: login.html 작성**

```html
<!DOCTYPE html>
<html lang="ko" class="theme-dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FI Dashboard — 로그인</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    html.theme-dark{--bg:#0A0A0A;--surface:#141414;--surface-hover:#1C1C1C;--border:rgba(255,255,255,0.06);--text:#EDEDED;--text-secondary:#888;--accent:#3b82f6;--accent-secondary:#8b5cf6;--positive:#10b981;--negative:#f43f5e;--warning:#f59e0b}
    html.theme-light{--bg:#FAFAF9;--surface:#FFFFFF;--surface-hover:#F5F5F4;--border:rgba(0,0,0,0.08);--text:#0f172a;--text-secondary:#64748b;--accent:#2563eb;--accent-secondary:#7c3aed;--positive:#059669;--negative:#e11d48;--warning:#d97706}

    body{
      font-family:'Noto Sans KR','Inter',sans-serif;
      background:var(--bg); color:var(--text);
      min-height:100vh; display:flex; align-items:center; justify-content:center;
      transition:background .3s,color .3s;
      -webkit-font-smoothing:antialiased;
      position:relative; overflow:hidden;
    }

    /* 배경 그라디언트 구체 */
    .bg-orb{position:fixed;border-radius:50%;filter:blur(80px);opacity:.15;pointer-events:none}
    .bg-orb-1{width:600px;height:600px;background:var(--accent);top:-200px;left:-200px}
    .bg-orb-2{width:400px;height:400px;background:var(--accent-secondary);bottom:-100px;right:-100px}

    /* 로그인 카드 */
    .login-card{
      position:relative;z-index:1;
      width:100%;max-width:420px;margin:24px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:20px;padding:48px 40px;
      box-shadow:0 32px 64px rgba(0,0,0,.24);
      animation:fadeInUp .6s ease-out both;
    }

    @keyframes fadeInUp{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:translateY(0)}}

    /* 로고 */
    .logo-area{text-align:center;margin-bottom:36px}
    .logo-icon{
      width:64px;height:64px;border-radius:16px;
      background:linear-gradient(135deg,var(--accent),var(--accent-secondary));
      display:inline-flex;align-items:center;justify-content:center;
      margin-bottom:16px;
    }
    .logo-icon svg{width:32px;height:32px;stroke:white;fill:none;stroke-width:2;stroke-linecap:round}
    h1{font-size:1.5rem;font-weight:700;letter-spacing:-.03em;margin-bottom:4px}
    .logo-sub{color:var(--text-secondary);font-size:.875rem}

    /* 폼 */
    .form-group{margin-bottom:20px}
    label{display:block;font-size:.8125rem;font-weight:500;color:var(--text-secondary);margin-bottom:8px;letter-spacing:.01em}
    .input-wrap{position:relative}
    .input-wrap svg{
      position:absolute;left:14px;top:50%;transform:translateY(-50%);
      width:18px;height:18px;stroke:var(--text-secondary);fill:none;stroke-width:2;stroke-linecap:round;
      pointer-events:none;
    }
    input[type="text"],input[type="password"]{
      width:100%;padding:12px 16px 12px 42px;
      background:var(--bg);border:1px solid var(--border);border-radius:10px;
      color:var(--text);font-size:.9375rem;font-family:inherit;
      transition:border-color .2s,box-shadow .2s;outline:none;
    }
    input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(59,130,246,.15)}

    /* 에러 */
    .error-msg{
      background:rgba(244,63,94,.1);border:1px solid rgba(244,63,94,.25);
      color:var(--negative);border-radius:8px;padding:10px 14px;
      font-size:.875rem;margin-bottom:20px;display:flex;align-items:center;gap:8px;
    }
    .error-msg svg{width:16px;height:16px;stroke:var(--negative);fill:none;stroke-width:2;flex-shrink:0}

    /* 버튼 */
    .btn-login{
      width:100%;padding:14px;border:none;border-radius:10px;
      background:linear-gradient(135deg,var(--accent),var(--accent-secondary));
      color:white;font-size:1rem;font-weight:600;font-family:inherit;
      cursor:pointer;transition:opacity .2s,transform .1s;letter-spacing:-.01em;
    }
    .btn-login:hover{opacity:.9}
    .btn-login:active{transform:scale(.98)}
    .btn-login:disabled{opacity:.6;cursor:not-allowed}

    /* 테마 토글 */
    .theme-btn{
      position:fixed;top:16px;right:16px;
      width:40px;height:40px;border-radius:10px;
      background:var(--surface);border:1px solid var(--border);
      color:var(--text-secondary);cursor:pointer;
      display:flex;align-items:center;justify-content:center;font-size:18px;
      transition:background .2s;
    }
    .theme-btn:hover{background:var(--surface-hover)}

    /* 하단 */
    .login-footer{text-align:center;margin-top:24px;color:var(--text-secondary);font-size:.8125rem}

    @media(max-width:375px){
      .login-card{padding:32px 24px;margin:16px}
      body{overflow-x:hidden}
    }
    @media print{.bg-orb,.theme-btn{display:none}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
  </style>
</head>
<body>
  <div class="bg-orb bg-orb-1"></div>
  <div class="bg-orb bg-orb-2"></div>

  <button class="theme-btn" onclick="cycleTheme()" aria-label="테마 전환">
    <span id="themeIcon">🌙</span>
  </button>

  <main id="main-content">
    <div class="login-card" role="main">
      <div class="logo-area">
        <div class="logo-icon">
          <svg viewBox="0 0 24 24">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
        </div>
        <h1>FI Dashboard</h1>
        <p class="logo-sub">수익성 분석 대시보드</p>
      </div>

      {% if error %}
      <div class="error-msg" role="alert">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        {{ error }}
      </div>
      {% endif %}

      <form method="POST" action="/login" id="loginForm">
        <div class="form-group">
          <label for="username">아이디 (AD 계정)</label>
          <div class="input-wrap">
            <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            <input type="text" id="username" name="username" placeholder="사용자 아이디" autocomplete="username" required>
          </div>
        </div>
        <div class="form-group">
          <label for="password">비밀번호</label>
          <div class="input-wrap">
            <svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <input type="password" id="password" name="password" placeholder="••••••••" autocomplete="current-password" required>
          </div>
        </div>
        <button type="submit" class="btn-login" id="submitBtn">로그인</button>
      </form>

      <p class="login-footer">접근 권한이 없다면 관리자에게 문의하세요</p>
    </div>
  </main>

  <script>
    var savedTheme = localStorage.getItem('viz-theme');
    var currentTheme = savedTheme || (window.matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
    function applyTheme(t){
      document.documentElement.className='theme-'+t;
      document.getElementById('themeIcon').textContent = t==='dark' ? '🌙' : '☀️';
      localStorage.setItem('viz-theme',t); currentTheme=t;
    }
    function cycleTheme(){ applyTheme(currentTheme==='dark'?'light':'dark'); }
    applyTheme(currentTheme);

    document.getElementById('loginForm').addEventListener('submit', function(){
      var btn = document.getElementById('submitBtn');
      btn.disabled=true; btn.textContent='인증 중...';
    });
  </script>
</body>
</html>
```

---

## Task 9: templates/dashboard.html — 구조 + 필터 + KPI

**Files:**
- Create: `templates/dashboard.html`

- [ ] **Step 1: dashboard.html 헤드·CSS·상단 네비 + 필터바 작성**

```html
<!DOCTYPE html>
<html lang="ko" class="theme-dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FI Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
  <script>if(typeof Chart!=='undefined')Chart.defaults.animation=false;</script>
  <script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{interpolate-size:allow-keywords}
    html.theme-dark{--bg:#0A0A0A;--surface:#141414;--surface-hover:#1C1C1C;--border:rgba(255,255,255,0.05);--text:#EDEDED;--text-secondary:#888;--accent:#3b82f6;--accent-secondary:#8b5cf6;--positive:#10b981;--negative:#f43f5e;--warning:#f59e0b;--nav-bg:rgba(10,10,10,.85)}
    html.theme-light{--bg:#F4F6FA;--surface:#FFFFFF;--surface-hover:#F5F5F4;--border:rgba(0,0,0,0.07);--text:#0f172a;--text-secondary:#64748b;--accent:#2563eb;--accent-secondary:#7c3aed;--positive:#059669;--negative:#e11d48;--warning:#d97706;--nav-bg:rgba(255,255,255,.85)}

    body{font-family:'Noto Sans KR','Inter',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;-webkit-font-smoothing:antialiased;transition:background .3s,color .3s;min-height:100vh}
    h1{font-size:2.5rem;font-weight:700;letter-spacing:-.03em}
    h2{font-size:2rem;font-weight:600;letter-spacing:-.03em}
    h3{font-size:1.5rem;font-weight:500;letter-spacing:-.02em}

    /* ── NAV ── */
    .topnav{
      position:sticky;top:0;z-index:100;
      background:var(--nav-bg);backdrop-filter:blur(16px);
      border-bottom:1px solid var(--border);
      padding:0 32px;height:60px;
      display:flex;align-items:center;justify-content:space-between;
    }
    .nav-brand{display:flex;align-items:center;gap:10px}
    .nav-logo{
      width:32px;height:32px;border-radius:8px;
      background:linear-gradient(135deg,var(--accent),var(--accent-secondary));
      display:flex;align-items:center;justify-content:center;
    }
    .nav-logo svg{width:16px;height:16px;stroke:white;fill:none;stroke-width:2.5;stroke-linecap:round}
    .nav-title{font-size:.9375rem;font-weight:700;letter-spacing:-.02em}
    .nav-right{display:flex;align-items:center;gap:12px}
    .nav-user{font-size:.8125rem;color:var(--text-secondary)}
    .nav-badge{
      padding:3px 10px;border-radius:20px;font-size:.75rem;font-weight:600;
      background:rgba(59,130,246,.15);color:var(--accent);
    }
    .nav-badge.admin{background:rgba(139,92,246,.15);color:var(--accent-secondary)}
    .nav-btn{
      padding:6px 14px;border-radius:8px;border:1px solid var(--border);
      background:transparent;color:var(--text-secondary);font-size:.8125rem;
      cursor:pointer;font-family:inherit;transition:background .2s;
    }
    .nav-btn:hover{background:var(--surface-hover)}

    /* ── FILTER BAR ── */
    .filter-bar{
      background:var(--surface);border-bottom:1px solid var(--border);
      padding:16px 32px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;
    }
    .filter-group{display:flex;flex-direction:column;gap:6px;min-width:160px}
    .filter-label{font-size:.75rem;font-weight:500;color:var(--text-secondary);letter-spacing:.03em;text-transform:uppercase}
    .filter-select,.filter-input{
      padding:8px 12px;border-radius:8px;border:1px solid var(--border);
      background:var(--bg);color:var(--text);font-size:.875rem;font-family:inherit;
      outline:none;transition:border-color .2s;
    }
    .filter-select:focus,.filter-input:focus{border-color:var(--accent)}
    .filter-months{display:flex;flex-wrap:wrap;gap:6px}
    .month-chip{
      padding:5px 12px;border-radius:20px;border:1px solid var(--border);
      background:transparent;color:var(--text-secondary);font-size:.8125rem;
      cursor:pointer;font-family:inherit;transition:all .2s;
    }
    .month-chip.active{background:var(--accent);border-color:var(--accent);color:white;font-weight:600}
    .btn-apply{
      padding:9px 24px;border-radius:8px;border:none;
      background:var(--accent);color:white;font-size:.875rem;font-weight:600;
      cursor:pointer;font-family:inherit;transition:opacity .2s;white-space:nowrap;
      align-self:flex-end;
    }
    .btn-apply:hover{opacity:.85}
    .btn-reset{
      padding:9px 16px;border-radius:8px;border:1px solid var(--border);
      background:transparent;color:var(--text-secondary);font-size:.875rem;
      cursor:pointer;font-family:inherit;transition:background .2s;white-space:nowrap;
      align-self:flex-end;
    }
    .btn-reset:hover{background:var(--surface-hover)}

    /* ── MAIN CONTAINER ── */
    .container{max-width:1600px;margin:0 auto;padding:32px}

    /* ── KPI CARDS ── */
    .kpi-grid{
      display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;
      margin-bottom:48px;
    }
    .kpi-card{
      background:var(--surface);border:1px solid var(--border);border-radius:12px;
      padding:24px;transition:box-shadow .2s;cursor:default;position:relative;overflow:hidden;
    }
    .kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--accent);opacity:.6}
    .kpi-card.positive::before{background:var(--positive)}
    .kpi-card.negative-kpi::before{background:var(--negative)}
    .kpi-card.warning::before{background:var(--warning)}
    .kpi-card:hover{box-shadow:0 0 0 1px var(--border),0 8px 24px rgba(0,0,0,.1)}
    .kpi-label{font-size:.8125rem;font-weight:500;color:var(--text-secondary);margin-bottom:12px;display:flex;align-items:center;gap:6px}
    .kpi-label svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
    .kpi-value{font-size:1.75rem;font-weight:700;letter-spacing:-.03em;color:var(--text);line-height:1}
    .kpi-sub{font-size:.8125rem;color:var(--text-secondary);margin-top:8px}
    .kpi-delta{
      display:inline-flex;align-items:center;gap:3px;font-size:.8125rem;font-weight:600;
      padding:2px 8px;border-radius:20px;margin-top:8px;
    }
    .kpi-delta.up{background:rgba(16,185,129,.15);color:var(--positive)}
    .kpi-delta.down{background:rgba(244,63,94,.15);color:var(--negative)}

    /* ── SECTION HEADERS ── */
    .section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
    .section-title{font-size:1.125rem;font-weight:700;letter-spacing:-.02em}
    .section-sub{font-size:.8125rem;color:var(--text-secondary);margin-top:2px}

    /* ── CHART CARDS ── */
    .chart-card{
      background:var(--surface);border:1px solid var(--border);border-radius:12px;
      padding:28px;margin-bottom:48px;
    }
    .chart-container{height:360px;position:relative}

    /* ── TABS ── */
    .tab-bar{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:32px}
    .tab-btn{
      padding:10px 20px;border:none;background:transparent;
      color:var(--text-secondary);font-size:.875rem;font-weight:500;
      cursor:pointer;font-family:inherit;border-bottom:2px solid transparent;
      margin-bottom:-1px;transition:color .2s,border-color .2s;
    }
    .tab-btn.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
    .tab-btn:hover:not(.active){color:var(--text)}
    .tab-panel{display:none}
    .tab-panel.active{display:block}

    /* ── GRID 2-COL ── */
    .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:32px}

    /* ── TABLE ── */
    .table-wrap{overflow-x:auto;border-radius:10px;border:1px solid var(--border)}
    table{width:100%;border-collapse:collapse;font-size:.875rem}
    thead th{
      padding:12px 16px;text-align:left;font-size:.75rem;font-weight:600;
      color:var(--text-secondary);background:var(--bg);border-bottom:1px solid var(--border);
      white-space:nowrap;letter-spacing:.03em;text-transform:uppercase;
    }
    tbody tr{border-bottom:1px solid var(--border);transition:background .15s}
    tbody tr:last-child{border-bottom:none}
    tbody tr:hover{background:var(--surface-hover)}
    tbody td{padding:11px 16px;color:var(--text)}
    .rank-badge{
      display:inline-flex;align-items:center;justify-content:center;
      width:22px;height:22px;border-radius:6px;font-size:.75rem;font-weight:700;
      background:var(--bg);color:var(--text-secondary);
    }
    .rank-badge.top3{background:var(--accent);color:white}
    .bar-cell{display:flex;align-items:center;gap:8px}
    .mini-bar{height:6px;border-radius:3px;background:var(--accent);opacity:.7;min-width:2px;transition:width .4s ease}
    .positive-text{color:var(--positive)}
    .negative-text{color:var(--negative)}

    /* ── VIZ MENU ── */
    .viz-menu{position:fixed;top:16px;right:16px;z-index:9999}
    .viz-menu-toggle{width:44px;height:44px;border-radius:12px;background:var(--surface);border:1px solid var(--border);color:var(--text);cursor:pointer;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(12px);transition:all .2s}
    .viz-menu-toggle:hover{background:var(--surface-hover)}
    .viz-menu-dropdown{position:absolute;top:52px;right:0;min-width:200px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:8px;opacity:0;visibility:hidden;transform:translateY(-8px);transition:all .2s;backdrop-filter:blur(16px)}
    .viz-menu-dropdown.open{opacity:1;visibility:visible;transform:translateY(0)}
    .viz-menu-dropdown button{width:100%;padding:10px 14px;border:none;border-radius:8px;background:transparent;color:var(--text);font-size:14px;font-family:inherit;cursor:pointer;text-align:left;display:flex;align-items:center;gap:10px;transition:background .15s}
    .viz-menu-dropdown button:hover{background:var(--surface-hover)}

    /* ── ANIMATIONS ── */
    @keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    .animate{animation:fadeInUp .5s ease-out both}
    .delay-1{animation-delay:.05s}.delay-2{animation-delay:.1s}.delay-3{animation-delay:.15s}
    .delay-4{animation-delay:.2s}.delay-5{animation-delay:.25s}.delay-6{animation-delay:.3s}
    .reveal{opacity:0;transform:translateY(20px);transition:opacity .6s ease,transform .6s ease}
    .reveal.visible{opacity:1;transform:translateY(0)}

    /* ── LOADING SPINNER ── */
    .loading{display:flex;align-items:center;justify-content:center;height:200px;color:var(--text-secondary);font-size:.875rem;gap:10px}
    .spinner{width:20px;height:20px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
    @keyframes spin{to{transform:rotate(360deg)}}

    /* ── RESPONSIVE ── */
    @media(max-width:1024px){.grid-2{grid-template-columns:1fr}}
    @media(max-width:768px){
      .container{padding:16px}
      .kpi-grid{grid-template-columns:repeat(2,1fr)}
      .filter-bar{padding:12px 16px}
      .topnav{padding:0 16px}
      .tab-btn{padding:8px 12px;font-size:.8125rem}
    }
    @media(max-width:375px){
      body{overflow-x:hidden}
      .kpi-grid{grid-template-columns:1fr}
      .kpi-value{font-size:1.5rem}
    }
    @media print{
      .viz-menu,.filter-bar,.topnav{display:none}
      .chart-card{break-inside:avoid}
      *{print-color-adjust:exact;-webkit-print-color-adjust:exact}
    }
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
  </style>
</head>
<body>

<!-- TOP NAV -->
<nav class="topnav" role="banner">
  <div class="nav-brand">
    <div class="nav-logo">
      <svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
    </div>
    <span class="nav-title">FI Dashboard</span>
  </div>
  <div class="nav-right">
    <span class="nav-user">{{ user.display_name }}</span>
    <span class="nav-badge {% if user.role == 'admin' %}admin{% endif %}">{{ user.role }}</span>
    {% if user.role == 'admin' %}
    <a href="/admin"><button class="nav-btn">사용자 관리</button></a>
    {% endif %}
    <a href="/logout"><button class="nav-btn">로그아웃</button></a>
  </div>
</nav>

<!-- FILTER BAR -->
<section class="filter-bar" aria-label="데이터 필터">
  <div class="filter-group">
    <span class="filter-label">월 선택</span>
    <div class="filter-months" id="monthChips"></div>
  </div>
  <div class="filter-group">
    <span class="filter-label">부서</span>
    <select class="filter-select" id="filterDept">
      <option value="">전체 부서</option>
    </select>
  </div>
  <div class="filter-group">
    <span class="filter-label">거래처</span>
    <select class="filter-select" id="filterCustomer">
      <option value="">전체 거래처</option>
    </select>
  </div>
  <div class="filter-group">
    <span class="filter-label">품명 검색</span>
    <input type="text" class="filter-input" id="filterProduct" placeholder="품명 입력...">
  </div>
  <button class="btn-apply" onclick="applyFilters()">적용</button>
  <button class="btn-reset" onclick="resetFilters()">초기화</button>
</section>

<a href="#main-content" style="position:absolute;left:-9999px">Skip to content</a>

<main id="main-content">
<div class="container">

  <!-- KPI CARDS -->
  <section aria-label="핵심 지표" style="margin-bottom:48px">
    <div class="section-header animate">
      <div>
        <div class="section-title">핵심 지표</div>
        <div class="section-sub">필터 적용 기간 합계</div>
      </div>
    </div>
    <div class="kpi-grid" id="kpiGrid">
      <div class="loading"><div class="spinner"></div>불러오는 중...</div>
    </div>
  </section>

  <!-- MONTHLY TREND -->
  <section aria-label="월별 추이" data-reveal>
    <div class="chart-card">
      <div class="section-header">
        <div>
          <div class="section-title">월별 추이</div>
          <div class="section-sub">매출액 · 매출총이익 · 영업이익</div>
        </div>
      </div>
      <div class="chart-container" role="img" aria-label="월별 매출 추이 라인 차트">
        <canvas id="trendChart"></canvas>
      </div>
    </div>
  </section>

  <!-- TABS -->
  <section aria-label="상세 분석" data-reveal>
    <div class="tab-bar" role="tablist">
      <button class="tab-btn active" role="tab" onclick="switchTab('overview')">개요</button>
      <button class="tab-btn" role="tab" onclick="switchTab('dept')">부서별</button>
      <button class="tab-btn" role="tab" onclick="switchTab('customer')">거래처별</button>
      <button class="tab-btn" role="tab" onclick="switchTab('product')">품목별</button>
    </div>

    <!-- 개요 탭 -->
    <div id="tab-overview" class="tab-panel active">
      <div class="grid-2">
        <div class="chart-card" style="margin-bottom:0">
          <div class="section-header"><div class="section-title">부서별 매출</div></div>
          <div class="chart-container" role="img" aria-label="부서별 매출액 바 차트">
            <canvas id="deptBarChart"></canvas>
          </div>
        </div>
        <div class="chart-card" style="margin-bottom:0">
          <div class="section-header"><div class="section-title">거래처 TOP 10 매출 비중</div></div>
          <div class="chart-container" role="img" aria-label="거래처 TOP10 도넛 차트">
            <canvas id="customerDonutChart"></canvas>
          </div>
        </div>
      </div>
    </div>

    <!-- 부서별 탭 -->
    <div id="tab-dept" class="tab-panel">
      <div class="chart-card">
        <div class="section-header"><div class="section-title">부서별 손익 구조</div></div>
        <div class="chart-container" role="img" aria-label="부서별 매출/이익 스택 바 차트">
          <canvas id="deptStackChart"></canvas>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th><th>부서</th><th>매출액</th><th>매출원가</th>
              <th>매출총이익</th><th>총이익률</th><th>판관비</th><th>영업이익</th><th>영업이익률</th>
            </tr>
          </thead>
          <tbody id="deptTableBody"><tr><td colspan="9" class="loading">불러오는 중...</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- 거래처별 탭 -->
    <div id="tab-customer" class="tab-panel">
      <div class="chart-card">
        <div class="section-header"><div class="section-title">거래처별 매출 TOP 20</div></div>
        <div class="chart-container" style="height:480px" role="img" aria-label="거래처별 수평 바 차트">
          <canvas id="customerBarChart"></canvas>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>거래처</th><th>매출액</th><th>매출총이익</th><th>총이익률</th><th>영업이익</th><th>영업이익률</th></tr>
          </thead>
          <tbody id="customerTableBody"><tr><td colspan="7" class="loading">불러오는 중...</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- 품목별 탭 -->
    <div id="tab-product" class="tab-panel">
      <div class="chart-card">
        <div class="section-header"><div class="section-title">품목별 매출 TOP 20</div></div>
        <div class="chart-container" style="height:480px" role="img" aria-label="품목별 수평 바 차트">
          <canvas id="productBarChart"></canvas>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>품명</th><th>품번</th><th>매출수량</th><th>매출액</th><th>매출총이익</th><th>총이익률</th></tr>
          </thead>
          <tbody id="productTableBody"><tr><td colspan="7" class="loading">불러오는 중...</td></tr></tbody>
        </table>
      </div>
    </div>
  </section>

</div>
</main>

<!-- VIZ MENU -->
<div class="viz-menu">
  <button class="viz-menu-toggle" onclick="toggleMenu()" aria-label="메뉴">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <line x1="3" y1="5" x2="17" y2="5"/><line x1="3" y1="10" x2="17" y2="10"/><line x1="3" y1="15" x2="17" y2="15"/>
    </svg>
  </button>
  <div class="viz-menu-dropdown" id="vizMenuDropdown">
    <button onclick="cycleTheme()"><span id="themeIcon">🌙</span><span id="themeLabel">Dark</span></button>
    <button onclick="downloadImage()"><span>📥</span><span>PNG 다운로드</span></button>
    <button onclick="window.print()"><span>🖨️</span><span>인쇄 / PDF</span></button>
  </div>
</div>

<script>
// ── 전역 상태 ──────────────────────────────────────────────────────
var selectedMonths = [];
var chartsBuilt = false;
var trendChart, deptBarChart, customerDonutChart, deptStackChart, customerBarChart, productBarChart;
var lastKpiData = {};
var lastDeptData = [];
var lastCustomerData = [];
var lastProductData = [];

// ── 테마 ───────────────────────────────────────────────────────────
var savedTheme = localStorage.getItem('viz-theme');
var currentTheme = savedTheme || (window.matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
function applyTheme(t){
  document.documentElement.className='theme-'+t;
  var icon=document.getElementById('themeIcon'), label=document.getElementById('themeLabel');
  if(icon) icon.textContent=t==='dark'?'🌙':'☀️';
  if(label) label.textContent=t==='dark'?'Dark':'Light';
  localStorage.setItem('viz-theme',t); currentTheme=t;
  if(chartsBuilt) onThemeChange();
}
function cycleTheme(){ applyTheme(currentTheme==='dark'?'light':'dark'); }
applyTheme(currentTheme);

// ── 메뉴 ───────────────────────────────────────────────────────────
function toggleMenu(){
  var d=document.getElementById('vizMenuDropdown');
  if(d) d.classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.viz-menu')){
    var d=document.getElementById('vizMenuDropdown');
    if(d) d.classList.remove('open');
  }
});

// ── 유틸 ───────────────────────────────────────────────────────────
function fmt(n){ return Math.round(n).toLocaleString('ko-KR'); }
function fmtM(n){ // 백만원 단위
  if(Math.abs(n)>=1e8) return (n/1e8).toFixed(1)+'억';
  if(Math.abs(n)>=1e6) return (n/1e6).toFixed(1)+'백만';
  return Math.round(n).toLocaleString();
}
function fmtPct(n){ return (n||0).toFixed(1)+'%'; }
function getColors(){
  var s=getComputedStyle(document.documentElement);
  return {
    text: s.getPropertyValue('--text').trim(),
    textSec: s.getPropertyValue('--text-secondary').trim(),
    border: s.getPropertyValue('--border').trim(),
    surface: s.getPropertyValue('--surface').trim(),
    accent: s.getPropertyValue('--accent').trim(),
    accentSec: s.getPropertyValue('--accent-secondary').trim(),
    positive: s.getPropertyValue('--positive').trim(),
    negative: s.getPropertyValue('--negative').trim(),
    warning: s.getPropertyValue('--warning').trim(),
    isDark: document.documentElement.classList.contains('theme-dark')
  };
}
function resetCanvas(id){
  var old=document.getElementById(id);
  if(!old) return null;
  var p=old.parentNode, c=document.createElement('canvas');
  c.id=id; p.replaceChild(c,old); return c;
}

// ── 필터 빌드 ──────────────────────────────────────────────────────
function buildParams(){
  var p=new URLSearchParams();
  selectedMonths.forEach(function(m){ p.append('months',m); });
  var dept=document.getElementById('filterDept').value;
  var cust=document.getElementById('filterCustomer').value;
  var prod=document.getElementById('filterProduct').value;
  if(dept) p.set('department',dept);
  if(cust) p.set('customer',cust);
  if(prod) p.set('product',prod);
  return p.toString();
}

function applyFilters(){ loadAll(); }

function resetFilters(){
  selectedMonths=[];
  document.querySelectorAll('.month-chip').forEach(function(c){ c.classList.remove('active'); });
  document.getElementById('filterDept').value='';
  document.getElementById('filterCustomer').value='';
  document.getElementById('filterProduct').value='';
  loadAll();
}

// ── 필터 옵션 로드 ─────────────────────────────────────────────────
function loadFilters(){
  fetch('/api/filters').then(function(r){ return r.json(); }).then(function(data){
    // 월 칩
    var wrap=document.getElementById('monthChips');
    wrap.innerHTML='';
    data.months.forEach(function(m){
      var btn=document.createElement('button');
      btn.className='month-chip'; btn.textContent=m; btn.dataset.month=m;
      btn.onclick=function(){
        var idx=selectedMonths.indexOf(m);
        if(idx>-1){ selectedMonths.splice(idx,1); btn.classList.remove('active'); }
        else { selectedMonths.push(m); btn.classList.add('active'); }
      };
      wrap.appendChild(btn);
    });
    // 부서
    var deptSel=document.getElementById('filterDept');
    data.departments.forEach(function(d){
      var o=document.createElement('option'); o.value=d; o.textContent=d; deptSel.appendChild(o);
    });
    // 거래처
    var custSel=document.getElementById('filterCustomer');
    data.customers.forEach(function(c){
      var o=document.createElement('option'); o.value=c; o.textContent=c; custSel.appendChild(o);
    });
  });
}

// ── KPI 로드 ───────────────────────────────────────────────────────
function loadKPI(){
  var p=buildParams();
  fetch('/api/kpi?'+p).then(function(r){ return r.json(); }).then(function(d){
    lastKpiData=d;
    renderKPI(d);
  });
}

function renderKPI(d){
  var grid=document.getElementById('kpiGrid');
  var cards=[
    {label:'매출액',      value:d.sales_amount,        sub:'원',       cls:'',          icon:'trending-up'},
    {label:'매출원가',    value:d.cost_of_sales,        sub:'원',       cls:'warning',   icon:'package'},
    {label:'매출총이익',  value:d.gross_profit,         sub:'원',       cls:'positive',  icon:'bar-chart-2'},
    {label:'총이익률',    value:d.gross_margin,         sub:'%',        cls:'positive',  icon:'percent', isPct:true},
    {label:'판관비',      value:d.sga_expenses,         sub:'원',       cls:'negative-kpi', icon:'minus-circle'},
    {label:'영업이익',    value:d.operating_income,     sub:'원',
     cls: d.operating_income>=0 ? 'positive':'negative-kpi', icon:'activity'},
    {label:'영업이익률',  value:d.operating_margin,     sub:'%',
     cls: d.operating_margin>=0 ? 'positive':'negative-kpi', icon:'percent', isPct:true},
    {label:'매출수량',    value:d.sales_quantity,       sub:'개',       cls:'',          icon:'shopping-cart'},
  ];
  grid.innerHTML='';
  cards.forEach(function(c,i){
    var div=document.createElement('div');
    div.className='kpi-card '+c.cls+' animate delay-'+(i%6+1);
    var val = c.isPct ? fmtPct(c.value) : fmtM(c.value||0);
    div.innerHTML='<div class="kpi-label">'+c.label+'</div>'
      +'<div class="kpi-value">'+val+'</div>'
      +'<div class="kpi-sub">'+(!c.isPct ? fmt(c.value||0)+' '+c.sub : '')+'</div>';
    grid.appendChild(div);
  });
}

// ── 월별 추이 차트 ─────────────────────────────────────────────────
function loadTrend(){
  var p=buildParams();
  fetch('/api/monthly-trend?'+p).then(function(r){ return r.json(); }).then(function(data){
    buildTrendChart(data);
  });
}

function buildTrendChart(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  var labels=data.map(function(r){ return r.Year_Month; });
  if(trendChart){ try{trendChart.destroy();}catch(e){} }
  var ctx=resetCanvas('trendChart');
  trendChart=new Chart(ctx,{
    type:'line',
    data:{
      labels:labels,
      datasets:[
        {label:'매출액',data:data.map(function(r){return r.sales_amount;}),
         borderColor:'rgba(59,130,246,1)',backgroundColor:'rgba(59,130,246,.08)',
         tension:.4,fill:true,pointRadius:5,pointHoverRadius:7,borderWidth:2},
        {label:'매출총이익',data:data.map(function(r){return r.gross_profit;}),
         borderColor:'rgba(16,185,129,1)',backgroundColor:'rgba(16,185,129,.06)',
         tension:.4,fill:true,pointRadius:5,pointHoverRadius:7,borderWidth:2},
        {label:'영업이익',data:data.map(function(r){return r.operating_income;}),
         borderColor:'rgba(139,92,246,1)',backgroundColor:'rgba(139,92,246,.06)',
         tension:.4,fill:true,pointRadius:5,pointHoverRadius:7,borderWidth:2},
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        tooltip:{enabled:true,mode:'index',intersect:false,padding:12,cornerRadius:8},
        legend:{labels:{color:c.text,font:{family:'Noto Sans KR',size:13}}}
      },
      scales:{
        x:{ticks:{color:c.textSec},grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}},
        y:{ticks:{color:c.textSec,callback:function(v){return fmtM(v);}},
           grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}}
      },
      layout:{padding:16}
    }
  });
}

// ── 부서별 데이터 ─────────────────────────────────────────────────
function loadDept(){
  var p=buildParams();
  fetch('/api/department?'+p).then(function(r){ return r.json(); }).then(function(data){
    lastDeptData=data;
    buildDeptBarChart(data);
    buildDeptStackChart(data);
    renderDeptTable(data);
  });
}

function buildDeptBarChart(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  var top=data.slice(0,12);
  if(deptBarChart){ try{deptBarChart.destroy();}catch(e){} }
  var ctx=resetCanvas('deptBarChart');
  deptBarChart=new Chart(ctx,{
    type:'bar',
    data:{
      labels:top.map(function(r){return r.Department;}),
      datasets:[
        {label:'매출액',data:top.map(function(r){return r.sales_amount;}),
         backgroundColor:'rgba(59,130,246,.7)',borderRadius:4},
        {label:'매출총이익',data:top.map(function(r){return r.gross_profit;}),
         backgroundColor:'rgba(16,185,129,.7)',borderRadius:4},
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{tooltip:{enabled:true,padding:12,cornerRadius:8},
        legend:{labels:{color:c.text,font:{family:'Noto Sans KR',size:12}}}},
      scales:{
        x:{ticks:{color:c.textSec,maxRotation:45},grid:{display:false}},
        y:{ticks:{color:c.textSec,callback:function(v){return fmtM(v);}},
           grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}}
      },
      layout:{padding:16}
    }
  });
}

function buildDeptStackChart(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  var top=data.slice(0,12);
  if(deptStackChart){ try{deptStackChart.destroy();}catch(e){} }
  var ctx=resetCanvas('deptStackChart');
  deptStackChart=new Chart(ctx,{
    type:'bar',
    data:{
      labels:top.map(function(r){return r.Department;}),
      datasets:[
        {label:'매출원가',data:top.map(function(r){return r.cost_of_sales;}),backgroundColor:'rgba(244,63,94,.6)',borderRadius:0},
        {label:'판관비',data:top.map(function(r){return r.sga_expenses;}),backgroundColor:'rgba(245,158,11,.6)',borderRadius:0},
        {label:'영업이익',data:top.map(function(r){return r.operating_income;}),backgroundColor:'rgba(16,185,129,.7)',borderRadius:4},
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{tooltip:{enabled:true,padding:12,cornerRadius:8,mode:'index',intersect:false},
        legend:{labels:{color:c.text,font:{family:'Noto Sans KR',size:12}}}},
      scales:{
        x:{stacked:true,ticks:{color:c.textSec,maxRotation:45},grid:{display:false}},
        y:{stacked:true,ticks:{color:c.textSec,callback:function(v){return fmtM(v);}},
           grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}}
      },
      layout:{padding:16}
    }
  });
}

function renderDeptTable(data){
  var body=document.getElementById('deptTableBody');
  if(!data.length){ body.innerHTML='<tr><td colspan="9" style="text-align:center;padding:24px;color:var(--text-secondary)">데이터 없음</td></tr>'; return; }
  body.innerHTML=data.map(function(r,i){
    var gm=r.gross_margin||0, om=r.operating_margin||0;
    return '<tr>'
      +'<td><span class="rank-badge '+(i<3?'top3':'')+'">'+(i+1)+'</span></td>'
      +'<td>'+r.Department+'</td>'
      +'<td>'+fmtM(r.sales_amount)+'</td>'
      +'<td>'+fmtM(r.cost_of_sales)+'</td>'
      +'<td>'+fmtM(r.gross_profit)+'</td>'
      +'<td class="'+(gm>=0?'positive-text':'negative-text')+'">'+fmtPct(gm)+'</td>'
      +'<td>'+fmtM(r.sga_expenses)+'</td>'
      +'<td class="'+(r.operating_income>=0?'positive-text':'negative-text')+'">'+fmtM(r.operating_income)+'</td>'
      +'<td class="'+(om>=0?'positive-text':'negative-text')+'">'+fmtPct(om)+'</td>'
      +'</tr>';
  }).join('');
}

// ── 거래처별 데이터 ────────────────────────────────────────────────
function loadCustomer(){
  var p=buildParams();
  fetch('/api/customer?'+p).then(function(r){ return r.json(); }).then(function(data){
    lastCustomerData=data;
    buildCustomerDonut(data.slice(0,10));
    buildCustomerBar(data.slice(0,20));
    renderCustomerTable(data);
  });
}

function buildCustomerDonut(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  var palette=['rgba(59,130,246,.8)','rgba(139,92,246,.8)','rgba(16,185,129,.8)','rgba(245,158,11,.8)','rgba(244,63,94,.8)','rgba(14,165,233,.8)','rgba(168,85,247,.8)','rgba(34,197,94,.8)','rgba(251,191,36,.8)','rgba(248,113,113,.8)'];
  if(customerDonutChart){ try{customerDonutChart.destroy();}catch(e){} }
  var ctx=resetCanvas('customerDonutChart');
  customerDonutChart=new Chart(ctx,{
    type:'doughnut',
    data:{
      labels:data.map(function(r){return r.Customer;}),
      datasets:[{data:data.map(function(r){return r.sales_amount;}),
        backgroundColor:palette,borderWidth:0,hoverOffset:8}]
    },
    options:{
      responsive:true,maintainAspectRatio:false,cutout:'65%',
      plugins:{
        tooltip:{enabled:true,padding:12,cornerRadius:8,callbacks:{label:function(ctx){return ctx.label+': '+fmtM(ctx.raw);}}},
        legend:{position:'right',labels:{color:c.text,font:{family:'Noto Sans KR',size:11},boxWidth:12,padding:8}}
      },
      layout:{padding:16}
    }
  });
}

function buildCustomerBar(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  if(customerBarChart){ try{customerBarChart.destroy();}catch(e){} }
  var ctx=resetCanvas('customerBarChart');
  customerBarChart=new Chart(ctx,{
    type:'bar',
    data:{
      labels:data.map(function(r){return r.Customer;}),
      datasets:[
        {label:'매출액',data:data.map(function(r){return r.sales_amount;}),backgroundColor:'rgba(59,130,246,.7)',borderRadius:4},
        {label:'매출총이익',data:data.map(function(r){return r.gross_profit;}),backgroundColor:'rgba(16,185,129,.7)',borderRadius:4},
      ]
    },
    options:{
      indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{tooltip:{enabled:true,padding:12,cornerRadius:8},
        legend:{labels:{color:c.text,font:{family:'Noto Sans KR',size:12}}}},
      scales:{
        x:{ticks:{color:c.textSec,callback:function(v){return fmtM(v);}},grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}},
        y:{ticks:{color:c.textSec,font:{size:11}},grid:{display:false}}
      },
      layout:{padding:16}
    }
  });
}

function renderCustomerTable(data){
  var body=document.getElementById('customerTableBody');
  if(!data.length){ body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary)">데이터 없음</td></tr>'; return; }
  var max=data[0].sales_amount||1;
  body.innerHTML=data.map(function(r,i){
    var gm=r.gross_margin||0, om=r.operating_margin||0;
    var barW=Math.round((r.sales_amount/max)*120);
    return '<tr>'
      +'<td><span class="rank-badge '+(i<3?'top3':'')+'">'+(i+1)+'</span></td>'
      +'<td><div class="bar-cell"><div class="mini-bar" style="width:'+barW+'px"></div>'+r.Customer+'</div></td>'
      +'<td>'+fmtM(r.sales_amount)+'</td>'
      +'<td>'+fmtM(r.gross_profit)+'</td>'
      +'<td class="'+(gm>=0?'positive-text':'negative-text')+'">'+fmtPct(gm)+'</td>'
      +'<td class="'+(r.operating_income>=0?'positive-text':'negative-text')+'">'+fmtM(r.operating_income)+'</td>'
      +'<td class="'+(om>=0?'positive-text':'negative-text')+'">'+fmtPct(om)+'</td>'
      +'</tr>';
  }).join('');
}

// ── 품목별 데이터 ─────────────────────────────────────────────────
function loadProduct(){
  var p=buildParams();
  fetch('/api/product?'+p).then(function(r){ return r.json(); }).then(function(data){
    lastProductData=data;
    buildProductBar(data.slice(0,20));
    renderProductTable(data);
  });
}

function buildProductBar(data){
  if(typeof Chart==='undefined') return;
  var c=getColors();
  if(productBarChart){ try{productBarChart.destroy();}catch(e){} }
  var ctx=resetCanvas('productBarChart');
  productBarChart=new Chart(ctx,{
    type:'bar',
    data:{
      labels:data.map(function(r){return r.Product_Name;}),
      datasets:[{label:'매출액',data:data.map(function(r){return r.sales_amount;}),
        backgroundColor:'rgba(139,92,246,.7)',borderRadius:4}]
    },
    options:{
      indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{tooltip:{enabled:true,padding:12,cornerRadius:8},
        legend:{labels:{color:c.text}}},
      scales:{
        x:{ticks:{color:c.textSec,callback:function(v){return fmtM(v);}},grid:{color:c.isDark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.06)'}},
        y:{ticks:{color:c.textSec,font:{size:10}},grid:{display:false}}
      },
      layout:{padding:16}
    }
  });
}

function renderProductTable(data){
  var body=document.getElementById('productTableBody');
  if(!data.length){ body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary)">데이터 없음</td></tr>'; return; }
  body.innerHTML=data.map(function(r,i){
    var gm=r.gross_margin||0;
    return '<tr>'
      +'<td><span class="rank-badge '+(i<3?'top3':'')+'">'+(i+1)+'</span></td>'
      +'<td>'+r.Product_Name+'</td>'
      +'<td style="color:var(--text-secondary);font-size:.8125rem">'+r.Product_Code+'</td>'
      +'<td>'+fmt(r.sales_quantity)+'</td>'
      +'<td>'+fmtM(r.sales_amount)+'</td>'
      +'<td>'+fmtM(r.gross_profit)+'</td>'
      +'<td class="'+(gm>=0?'positive-text':'negative-text')+'">'+fmtPct(gm)+'</td>'
      +'</tr>';
  }).join('');
}

// ── 탭 전환 ────────────────────────────────────────────────────────
function switchTab(name){
  document.querySelectorAll('.tab-btn').forEach(function(b,i){
    var names=['overview','dept','customer','product'];
    b.classList.toggle('active', names[i]===name);
  });
  document.querySelectorAll('.tab-panel').forEach(function(p){
    p.classList.remove('active');
  });
  var panel=document.getElementById('tab-'+name);
  if(panel) panel.classList.add('active');
  // 탭 진입 시 차트 resize 트리거
  setTimeout(function(){
    [trendChart,deptBarChart,customerDonutChart,deptStackChart,customerBarChart,productBarChart].forEach(function(ch){
      if(ch) try{ch.resize();}catch(e){}
    });
  },50);
}

// ── 테마 변경 시 차트 리빌드 ───────────────────────────────────────
function onThemeChange(){
  chartsBuilt=false;
  setTimeout(function(){
    buildTrendChart(window._trendData||[]);
    if(lastDeptData.length){ buildDeptBarChart(lastDeptData); buildDeptStackChart(lastDeptData); }
    if(lastCustomerData.length){ buildCustomerDonut(lastCustomerData.slice(0,10)); buildCustomerBar(lastCustomerData.slice(0,20)); }
    if(lastProductData.length){ buildProductBar(lastProductData.slice(0,20)); }
  },100);
}

// ── 전체 로드 ──────────────────────────────────────────────────────
function loadAll(){
  loadKPI();
  loadTrend();
  loadDept();
  loadCustomer();
  loadProduct();
}

// ── 스크롤 리빌 ────────────────────────────────────────────────────
document.querySelectorAll('[data-reveal]').forEach(function(el){ el.classList.add('reveal'); });
var revealObs=new IntersectionObserver(function(entries){
  entries.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('visible'); revealObs.unobserve(e.target); } });
},{threshold:.1});
document.querySelectorAll('.reveal').forEach(function(el){ revealObs.observe(el); });

// ── PNG 다운로드 ────────────────────────────────────────────────────
async function downloadImage(){
  var menu=document.querySelector('.viz-menu');
  menu.style.display='none';
  try{
    var url=await htmlToImage.toPng(document.body,{quality:1,pixelRatio:2});
    var a=document.createElement('a'); a.href=url;
    a.download='fi-dashboard.png'; a.click();
  }catch(e){console.error(e);}
  menu.style.display='';
}

// ── 초기화 ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded',function(){
  loadFilters();
  loadAll();
  chartsBuilt=true;
});

// trend 데이터 캐시 (테마 변경 시 재사용)
var _origLoadTrend=loadTrend;
loadTrend=function(){
  var p=buildParams();
  fetch('/api/monthly-trend?'+p).then(function(r){ return r.json(); }).then(function(data){
    window._trendData=data;
    buildTrendChart(data);
  });
};
</script>
</body>
</html>
```

---

## Task 10: templates/admin.html

**Files:**
- Create: `templates/admin.html`

- [ ] **Step 1: admin.html 작성**

```html
<!DOCTYPE html>
<html lang="ko" class="theme-dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>사용자 관리 — FI Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    html.theme-dark{--bg:#0A0A0A;--surface:#141414;--surface-hover:#1C1C1C;--border:rgba(255,255,255,0.05);--text:#EDEDED;--text-secondary:#888;--accent:#3b82f6;--accent-secondary:#8b5cf6;--positive:#10b981;--negative:#f43f5e;--warning:#f59e0b}
    html.theme-light{--bg:#F4F6FA;--surface:#FFFFFF;--surface-hover:#F5F5F4;--border:rgba(0,0,0,0.07);--text:#0f172a;--text-secondary:#64748b;--accent:#2563eb;--accent-secondary:#7c3aed;--positive:#059669;--negative:#e11d48;--warning:#d97706}
    body{font-family:'Noto Sans KR','Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;-webkit-font-smoothing:antialiased;transition:background .3s,color .3s}
    h1{font-size:2.5rem;font-weight:700;letter-spacing:-.03em}
    h2{font-size:2rem;font-weight:600;letter-spacing:-.03em}
    h3{font-size:1.5rem;font-weight:500}

    .topnav{position:sticky;top:0;z-index:100;background:var(--bg);border-bottom:1px solid var(--border);padding:0 32px;height:60px;display:flex;align-items:center;justify-content:space-between;backdrop-filter:blur(16px)}
    .nav-brand{display:flex;align-items:center;gap:10px}
    .nav-logo{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--accent-secondary));display:flex;align-items:center;justify-content:center}
    .nav-logo svg{width:16px;height:16px;stroke:white;fill:none;stroke-width:2.5;stroke-linecap:round}
    .nav-title{font-size:.9375rem;font-weight:700}
    .nav-right{display:flex;gap:12px;align-items:center}
    .nav-btn{padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--text-secondary);font-size:.8125rem;cursor:pointer;font-family:inherit;transition:background .2s;text-decoration:none;display:inline-flex;align-items:center}
    .nav-btn:hover{background:var(--surface-hover)}

    .container{max-width:900px;margin:0 auto;padding:40px 32px}
    .page-header{margin-bottom:40px}
    .page-title{font-size:1.75rem;font-weight:700;letter-spacing:-.03em;margin-bottom:6px}
    .page-sub{color:var(--text-secondary);font-size:.9375rem}

    /* 추가 폼 */
    .add-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:28px;margin-bottom:32px}
    .add-title{font-size:1rem;font-weight:600;margin-bottom:20px;display:flex;align-items:center;gap:8px}
    .add-title svg{width:18px;height:18px;stroke:var(--accent);fill:none;stroke-width:2;stroke-linecap:round}
    .add-form{display:grid;grid-template-columns:1fr 1fr auto auto;gap:12px;align-items:end}
    .form-field{display:flex;flex-direction:column;gap:6px}
    .form-label{font-size:.75rem;font-weight:500;color:var(--text-secondary);letter-spacing:.03em;text-transform:uppercase}
    .form-input,.form-select{padding:9px 12px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:.875rem;font-family:inherit;outline:none;transition:border-color .2s}
    .form-input:focus,.form-select:focus{border-color:var(--accent)}
    .btn-add{padding:9px 20px;border-radius:8px;border:none;background:var(--accent);color:white;font-size:.875rem;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity .2s;white-space:nowrap}
    .btn-add:hover{opacity:.85}

    /* 사용자 테이블 */
    .table-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .table-header{padding:20px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
    .table-title{font-size:1rem;font-weight:600}
    .user-count{font-size:.8125rem;color:var(--text-secondary)}
    table{width:100%;border-collapse:collapse;font-size:.875rem}
    thead th{padding:11px 16px;text-align:left;font-size:.75rem;font-weight:600;color:var(--text-secondary);background:var(--bg);border-bottom:1px solid var(--border);letter-spacing:.03em;text-transform:uppercase;white-space:nowrap}
    tbody tr{border-bottom:1px solid var(--border);transition:background .15s}
    tbody tr:last-child{border-bottom:none}
    tbody tr:hover{background:var(--surface-hover)}
    tbody td{padding:12px 16px}
    .role-badge{padding:3px 10px;border-radius:20px;font-size:.75rem;font-weight:600}
    .role-badge.admin{background:rgba(139,92,246,.15);color:var(--accent-secondary)}
    .role-badge.viewer{background:rgba(59,130,246,.15);color:var(--accent)}
    .status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
    .status-dot.active{background:var(--positive)}
    .status-dot.inactive{background:var(--text-secondary)}
    .action-btns{display:flex;gap:6px}
    .btn-sm{padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--text-secondary);font-size:.75rem;cursor:pointer;font-family:inherit;transition:background .2s;white-space:nowrap}
    .btn-sm:hover{background:var(--surface-hover)}
    .btn-sm.danger:hover{background:rgba(244,63,94,.1);color:var(--negative);border-color:rgba(244,63,94,.3)}
    .msg{padding:12px 16px;border-radius:8px;font-size:.875rem;margin-bottom:16px;display:none}
    .msg.success{background:rgba(16,185,129,.1);color:var(--positive);border:1px solid rgba(16,185,129,.2)}
    .msg.error{background:rgba(244,63,94,.1);color:var(--negative);border:1px solid rgba(244,63,94,.2)}

    @keyframes fadeInUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
    .animate{animation:fadeInUp .5s ease-out both}
    @media(max-width:768px){.add-form{grid-template-columns:1fr 1fr}.container{padding:24px 16px}}
    @media(max-width:375px){body{overflow-x:hidden}.add-form{grid-template-columns:1fr}}
    @media print{.topnav,.add-card,.action-btns{display:none}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}

    /* viz-menu */
    .viz-menu{position:fixed;top:16px;right:16px;z-index:9999}
    .viz-menu-toggle{width:44px;height:44px;border-radius:12px;background:var(--surface);border:1px solid var(--border);color:var(--text);cursor:pointer;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(12px);transition:all .2s}
    .viz-menu-toggle:hover{background:var(--surface-hover)}
    .viz-menu-dropdown{position:absolute;top:52px;right:0;min-width:180px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:8px;opacity:0;visibility:hidden;transform:translateY(-8px);transition:all .2s}
    .viz-menu-dropdown.open{opacity:1;visibility:visible;transform:translateY(0)}
    .viz-menu-dropdown button{width:100%;padding:10px 14px;border:none;border-radius:8px;background:transparent;color:var(--text);font-size:14px;font-family:inherit;cursor:pointer;text-align:left;display:flex;align-items:center;gap:10px;transition:background .15s}
    .viz-menu-dropdown button:hover{background:var(--surface-hover)}
  </style>
</head>
<body>
<nav class="topnav">
  <div class="nav-brand">
    <div class="nav-logo"><svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div>
    <span class="nav-title">FI Dashboard — 사용자 관리</span>
  </div>
  <div class="nav-right">
    <a href="/dashboard" class="nav-btn">← 대시보드</a>
    <a href="/logout" class="nav-btn">로그아웃</a>
  </div>
</nav>

<main id="main-content">
<div class="container">
  <div class="page-header animate">
    <div class="page-title">사용자 관리</div>
    <div class="page-sub">대시보드 접근 허용 사용자를 관리합니다. AD 계정 기준으로 등록하세요.</div>
  </div>

  <div id="alertMsg" class="msg"></div>

  <!-- 추가 폼 -->
  <div class="add-card animate delay-1">
    <div class="add-title">
      <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
      사용자 추가
    </div>
    <div class="add-form">
      <div class="form-field">
        <label class="form-label">AD 계정 (아이디)</label>
        <input type="text" class="form-input" id="newUsername" placeholder="예: john.doe">
      </div>
      <div class="form-field">
        <label class="form-label">표시 이름</label>
        <input type="text" class="form-input" id="newDisplayName" placeholder="예: 홍길동">
      </div>
      <div class="form-field">
        <label class="form-label">역할</label>
        <select class="form-select" id="newRole">
          <option value="viewer">Viewer</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <button class="btn-add" onclick="addUser()">추가</button>
    </div>
  </div>

  <!-- 사용자 목록 -->
  <div class="table-card animate delay-2">
    <div class="table-header">
      <div class="table-title">등록된 사용자</div>
      <div class="user-count" id="userCount">{{ users|length }}명</div>
    </div>
    <table>
      <thead>
        <tr><th>아이디</th><th>표시 이름</th><th>역할</th><th>상태</th><th>등록일</th><th>작업</th></tr>
      </thead>
      <tbody id="userTableBody">
        {% for u in users %}
        <tr id="row-{{ u.id }}">
          <td style="font-weight:500">{{ u.username }}</td>
          <td style="color:var(--text-secondary)">{{ u.display_name or '-' }}</td>
          <td><span class="role-badge {{ u.role }}">{{ u.role }}</span></td>
          <td>
            <span class="status-dot {{ 'active' if u.is_active else 'inactive' }}"></span>
            {{ '활성' if u.is_active else '비활성' }}
          </td>
          <td style="color:var(--text-secondary);font-size:.8125rem">{{ u.created_at.strftime('%Y-%m-%d') if u.created_at else '-' }}</td>
          <td>
            <div class="action-btns">
              <button class="btn-sm" onclick="changeRole({{ u.id }}, '{{ 'viewer' if u.role == 'admin' else 'admin' }}')">
                → {{ '뷰어로' if u.role == 'admin' else '관리자로' }}
              </button>
              <button class="btn-sm" onclick="toggleUser({{ u.id }})">{{ '비활성화' if u.is_active else '활성화' }}</button>
              <button class="btn-sm danger" onclick="deleteUser({{ u.id }}, '{{ u.username }}')">삭제</button>
            </div>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
</main>

<div class="viz-menu">
  <button class="viz-menu-toggle" onclick="toggleMenu()" aria-label="메뉴">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <line x1="3" y1="5" x2="17" y2="5"/><line x1="3" y1="10" x2="17" y2="10"/><line x1="3" y1="15" x2="17" y2="15"/>
    </svg>
  </button>
  <div class="viz-menu-dropdown" id="vizMenuDropdown">
    <button onclick="cycleTheme()"><span id="themeIcon">🌙</span><span id="themeLabel">Dark</span></button>
    <button onclick="window.print()"><span>🖨️</span><span>인쇄</span></button>
  </div>
</div>

<script>
var savedTheme=localStorage.getItem('viz-theme');
var currentTheme=savedTheme||(window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark');
function applyTheme(t){
  document.documentElement.className='theme-'+t;
  var i=document.getElementById('themeIcon'),l=document.getElementById('themeLabel');
  if(i)i.textContent=t==='dark'?'🌙':'☀️'; if(l)l.textContent=t==='dark'?'Dark':'Light';
  localStorage.setItem('viz-theme',t); currentTheme=t;
}
function cycleTheme(){ applyTheme(currentTheme==='dark'?'light':'dark'); }
applyTheme(currentTheme);

function toggleMenu(){
  var d=document.getElementById('vizMenuDropdown'); if(d)d.classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.viz-menu')){var d=document.getElementById('vizMenuDropdown');if(d)d.classList.remove('open');}
});

function showMsg(text,type){
  var el=document.getElementById('alertMsg');
  el.textContent=text; el.className='msg '+type; el.style.display='block';
  setTimeout(function(){ el.style.display='none'; }, 3500);
}

function addUser(){
  var username=document.getElementById('newUsername').value.trim();
  var displayName=document.getElementById('newDisplayName').value.trim();
  var role=document.getElementById('newRole').value;
  if(!username){ showMsg('AD 계정을 입력하세요','error'); return; }
  fetch('/admin/users/add',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:username,display_name:displayName,role:role})
  }).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('사용자가 추가되었습니다','success'); setTimeout(function(){ location.reload(); },1000); }
    else showMsg(d.error||'오류 발생','error');
  });
}

function deleteUser(id, username){
  if(!confirm(username+'을(를) 삭제하시겠습니까?')) return;
  fetch('/admin/users/'+id+'/delete',{method:'POST'}).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('삭제되었습니다','success'); var row=document.getElementById('row-'+id); if(row)row.remove(); }
    else showMsg(d.error||'오류 발생','error');
  });
}

function changeRole(id, newRole){
  fetch('/admin/users/'+id+'/role',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:newRole})
  }).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('역할이 변경되었습니다','success'); setTimeout(function(){ location.reload(); },800); }
    else showMsg(d.error||'오류 발생','error');
  });
}

function toggleUser(id){
  fetch('/admin/users/'+id+'/toggle',{method:'POST'}).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('상태가 변경되었습니다','success'); setTimeout(function(){ location.reload(); },800); }
    else showMsg(d.error||'오류 발생','error');
  });
}
</script>
</body>
</html>
```

---

## Task 11: 최종 실행 및 검증

**Files:**
- 없음

- [ ] **Step 1: Flask 실행**

```
python app.py
```

Expected: `Running on http://0.0.0.0:5000`

- [ ] **Step 2: 로그인 테스트**

브라우저 `http://127.0.0.1:5000` → 로그인 페이지  
AD 계정으로 로그인 시도 → 화이트리스트 미등록이면 "접근 권한 없음" 메시지 확인

- [ ] **Step 3: 화이트리스트에 자신의 계정 추가**

```sql
INSERT INTO dashboard_users (username, display_name, role)
VALUES ('your_ad_id', '이름', 'admin');
```

- [ ] **Step 4: 대시보드 진입 확인**

로그인 성공 → `/dashboard` 리다이렉트  
KPI 카드, 월별 추이 차트, 4탭(개요/부서별/거래처별/품목별) 정상 렌더링 확인

- [ ] **Step 5: 필터 동작 확인**

월 칩 선택 → "적용" → KPI 카드 & 모든 차트 갱신 확인  
"초기화" → 전체 데이터로 복원 확인

- [ ] **Step 6: 어드민 페이지 확인 (admin 계정)**

`/admin` → 사용자 목록 표시  
사용자 추가/삭제/역할변경 동작 확인

- [ ] **Step 7: 테마 토글 확인**

햄버거 메뉴 → Dark↔Light 전환 시 차트 색상 갱신 확인

---

## 셀프 리뷰 체크리스트

- [x] AD LDAPS 인증 → Task 3
- [x] MariaDB 화이트리스트 → Task 2, Task 3
- [x] 로그인/로그아웃 → Task 4
- [x] 필터 4종 (월/부서/거래처/품명) → Task 5, dashboard.html
- [x] KPI 카드 8개 → Task 5, dashboard.html
- [x] 월별 추이 라인 차트 → Task 6, dashboard.html
- [x] 부서별 바/스택/테이블 → Task 6, dashboard.html
- [x] 거래처별 도넛/수평바/테이블 → Task 6, dashboard.html
- [x] 품목별 바/테이블 → Task 6, dashboard.html
- [x] 어드민 CRUD → Task 7, admin.html
- [x] 다크/라이트 테마 → 모든 HTML
- [x] 반응형 (375px) → 모든 HTML
- [x] AJAX 필터 적용 → dashboard.html JS
