import secrets
import functools
import time
import threading
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pymysql
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from google.cloud import bigquery
from google.oauth2 import service_account
import config

# ─── 쿼리 결과 캐시 (데이터가 월 1회 업데이트이므로 서버 재시작 전까지 유지) ──
_query_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 60 * 60 * 24 * 40  # 40일 (서버 재시작이 실질적 무효화)


def _cache_key(sql: str, params) -> str:
    parts = [sql]
    for p in (params or []):
        try:
            parts.append(json.dumps(p.to_api_repr(), sort_keys=True))
        except Exception:
            parts.append(str(p))
    return '||'.join(parts)


def run_query_cached(sql, params=None, ttl=CACHE_TTL):
    key = _cache_key(sql, params)
    with _cache_lock:
        entry = _query_cache.get(key)
        if entry and time.time() - entry[0] < ttl:
            return entry[1]
    result = run_query(sql, params)
    with _cache_lock:
        _query_cache[key] = (time.time(), result)
    return result


def _warm_cache():
    """서버 시작 시 백그라운드에서 주요 쿼리 결과를 미리 캐시에 적재."""
    time.sleep(8)  # Flask 완전 기동 대기
    T = config.BQ_TABLE
    print('[cache] 워밍업 시작...')
    try:
        # 1. 필터 목록 (9개 병렬)
        filter_sqls = [
            f"SELECT DISTINCT Department FROM `{T}` WHERE Department IS NOT NULL ORDER BY Department",
            f"SELECT DISTINCT Customer FROM `{T}` WHERE Customer IS NOT NULL ORDER BY Customer",
            f"SELECT DISTINCT Year_Month FROM `{T}` ORDER BY Year_Month",
            f"SELECT DISTINCT Sales_Type FROM `{T}` WHERE Sales_Type IS NOT NULL ORDER BY Sales_Type",
            f"SELECT DISTINCT Line FROM `{T}` WHERE Line IS NOT NULL ORDER BY Line",
            f"SELECT DISTINCT Category FROM `{T}` WHERE Category IS NOT NULL ORDER BY Category",
            f"SELECT DISTINCT Country FROM `{T}` WHERE Country IS NOT NULL AND Country != '' ORDER BY Country",
            f"SELECT DISTINCT Continent2 FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2 != '' ORDER BY Continent2",
            f"SELECT DISTINCT `Group` FROM `{T}` WHERE `Group` IS NOT NULL AND `Group` != '' ORDER BY `Group`",
        ]

        # 2. KPI / Trend / Breakdown (카테고리 4개 × 기본 무필터)
        cols = "SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Operating_Income) AS operating_income, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin, SUM(Sales_Quantity) AS sales_quantity"
        data_sqls = [
            # KPI 전체 + B2B + B2C
            f"SELECT {cols} FROM `{T}`",
            f"SELECT {cols} FROM `{T}` WHERE Sales_Type='B2B'",
            f"SELECT {cols} FROM `{T}` WHERE Sales_Type='B2C'",
            # 월별 추이
            f"SELECT Year_Month, SUM(Sales_Amount) AS sales_amount, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Cost_of_Sales) AS cost_of_sales FROM `{T}` GROUP BY Year_Month ORDER BY Year_Month",
            f"SELECT Year_Month, SUM(Sales_Amount) AS sales_amount, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Cost_of_Sales) AS cost_of_sales FROM `{T}` WHERE Sales_Type='B2B' GROUP BY Year_Month ORDER BY Year_Month",
            f"SELECT Year_Month, SUM(Sales_Amount) AS sales_amount, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Cost_of_Sales) AS cost_of_sales FROM `{T}` WHERE Sales_Type='B2C' GROUP BY Year_Month ORDER BY Year_Month",
            # 조직별
            f"SELECT `Group`, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` GROUP BY `Group` ORDER BY sales_amount DESC",
            f"SELECT Year_Month, `Group` AS dim_value, SUM(Sales_Amount) AS sales_amount FROM `{T}` WHERE `Group` IS NOT NULL AND `Group`!='' GROUP BY Year_Month,`Group` ORDER BY Year_Month,sales_amount DESC",
            # 지역별
            f"SELECT Continent2, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2!='' GROUP BY Continent2 ORDER BY sales_amount DESC",
            f"SELECT Year_Month, Continent2 AS dim_value, SUM(Sales_Amount) AS sales_amount FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2!='' GROUP BY Year_Month,Continent2 ORDER BY Year_Month,sales_amount DESC",
            # 상품별
            f"SELECT Line, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` GROUP BY Line ORDER BY sales_amount DESC",
            f"SELECT Year_Month, Line AS dim_value, SUM(Sales_Amount) AS sales_amount FROM `{T}` WHERE Line IS NOT NULL AND Line!='' GROUP BY Year_Month,Line ORDER BY Year_Month,sales_amount DESC",
            # 판매유형별
            f"SELECT Sales_Type, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Sales_Quantity) AS sales_quantity, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` GROUP BY Sales_Type ORDER BY sales_amount DESC",
            f"SELECT Year_Month, Sales_Type AS dim_value, SUM(Sales_Amount) AS sales_amount FROM `{T}` WHERE Sales_Type IS NOT NULL AND Sales_Type!='' GROUP BY Year_Month,Sales_Type ORDER BY Year_Month,sales_amount DESC",
        ]

        all_sqls = filter_sqls + data_sqls

        def warm_one(sql):
            try:
                run_query_cached(sql)
            except Exception as e:
                print(f'[cache] 워밍업 실패: {e}')

        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(warm_one, all_sqls))

        print(f'[cache] 워밍업 완료 — {len(all_sqls)}개 쿼리 캐시 적재')
    except Exception as e:
        print(f'[cache] 워밍업 오류: {e}')


# 서버 시작 시 자동 워밍업
threading.Thread(target=_warm_cache, daemon=True).start()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

REMEMBER_COOKIE = 'fi_remember'
REMEMBER_DAYS = 30

@app.route('/favicon.ico')
def favicon():
    return make_response('', 204)


# ─── MariaDB helper ────────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASS,
        database=config.DB_NAME, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


def init_db():
    db = get_db()
    try:
        with db.cursor() as cur:
            # password_hash 컬럼 추가 (없을 경우)
            cur.execute("""
                ALTER TABLE dashboard_users
                ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) DEFAULT NULL
            """)
            # 자동로그인 토큰 테이블
            cur.execute("""
                CREATE TABLE IF NOT EXISTS remember_tokens (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    token VARCHAR(64) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        db.commit()
    finally:
        db.close()


def create_remember_token(username):
    token = secrets.token_hex(32)
    expires = datetime.now() + timedelta(days=REMEMBER_DAYS)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM remember_tokens WHERE username=%s",
                (username,)
            )
            cur.execute(
                "INSERT INTO remember_tokens (username, token, expires_at) VALUES (%s,%s,%s)",
                (username, token, expires)
            )
        db.commit()
        return token
    finally:
        db.close()


def check_remember_token(token):
    if not token:
        return None
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT username FROM remember_tokens WHERE token=%s AND expires_at > NOW()",
                (token,)
            )
            row = cur.fetchone()
        return row['username'] if row else None
    finally:
        db.close()


def clear_remember_token(token):
    if not token:
        return
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM remember_tokens WHERE token=%s", (token,))
        db.commit()
    finally:
        db.close()


# ─── BigQuery helper ───────────────────────────────────────────────
def get_bq_client():
    creds = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    return bigquery.Client(project=config.BQ_PROJECT, credentials=creds)


# ─── 로컬 인증 ─────────────────────────────────────────────────────
def get_user_by_username(username):
    """username으로 사용자 조회 (활성 여부 무관)"""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT id, username, display_name, role, is_active, password_hash "
                "FROM dashboard_users WHERE username=%s",
                (username.lower(),)
            )
            return cur.fetchone()
    finally:
        db.close()


def verify_password(username, password):
    """비밀번호 검증. 성공 시 user dict 반환, 실패 시 None"""
    user = get_user_by_username(username)
    if not user or not user.get('password_hash'):
        return None
    if not user['is_active']:
        return None
    if check_password_hash(user['password_hash'], password):
        return user
    return None


# ─── 데코레이터 ────────────────────────────────────────────────────
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


# ─── 로그인 ────────────────────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Auto-login via remember cookie (GET only)
    if request.method == 'GET':
        token = request.cookies.get(REMEMBER_COOKIE)
        username = check_remember_token(token)
        if username:
            user = get_user_by_username(username)
            if user and user['is_active']:
                session['user'] = {
                    'username': user['username'],
                    'display_name': user['display_name'] or username,
                    'role': user['role']
                }
                return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        auto_login = request.form.get('auto_login') == '1'

        if not username or not password:
            error = '아이디와 비밀번호를 입력하세요.'
        else:
            user = verify_password(username, password)
            if not user:
                # 비밀번호 미설정 여부 확인 → 회원가입 안내
                existing = get_user_by_username(username)
                if existing and not existing.get('password_hash'):
                    error = '비밀번호가 설정되지 않았습니다. 회원가입을 통해 비밀번호를 설정하세요.'
                elif existing and not existing['is_active']:
                    error = '관리자 승인 대기 중입니다. 관리자에게 문의하세요.'
                else:
                    error = '아이디 또는 비밀번호가 올바르지 않습니다.'
            else:
                session['user'] = {
                    'username': user['username'],
                    'display_name': user['display_name'] or username,
                    'role': user['role']
                }
                resp = make_response(redirect(url_for('dashboard')))
                if auto_login:
                    token = create_remember_token(user['username'])
                    resp.set_cookie(
                        REMEMBER_COOKIE, token,
                        max_age=REMEMBER_DAYS * 86400,
                        httponly=True, samesite='Lax'
                    )
                else:
                    resp.delete_cookie(REMEMBER_COOKIE)
                return resp

    return render_template('login.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    error = None
    success = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not username or not password:
            error = '아이디와 비밀번호를 입력하세요.'
        elif len(password) < 6:
            error = '비밀번호는 6자 이상이어야 합니다.'
        elif password != confirm:
            error = '비밀번호가 일치하지 않습니다.'
        else:
            existing = get_user_by_username(username)
            pw_hash = generate_password_hash(password)

            if existing:
                if existing.get('password_hash'):
                    error = '이미 가입된 아이디입니다. 로그인하세요.'
                else:
                    # 관리자가 사전 등록한 계정 → 비밀번호 설정 후 즉시 활성화
                    db = get_db()
                    try:
                        with db.cursor() as cur:
                            cur.execute(
                                "UPDATE dashboard_users SET password_hash=%s, is_active=1"
                                + (", display_name=%s" if display_name else "") +
                                " WHERE username=%s",
                                (pw_hash, display_name, username) if display_name else (pw_hash, username)
                            )
                        db.commit()
                    finally:
                        db.close()
                    session['user'] = {
                        'username': existing['username'],
                        'display_name': display_name or existing['display_name'] or username,
                        'role': existing['role']
                    }
                    return redirect(url_for('dashboard'))
            else:
                # 신규 사용자 → 승인 대기
                db = get_db()
                try:
                    with db.cursor() as cur:
                        cur.execute(
                            "INSERT INTO dashboard_users "
                            "(username, display_name, role, is_active, password_hash) "
                            "VALUES (%s,%s,'viewer',0,%s)",
                            (username, display_name or username, pw_hash)
                        )
                    db.commit()
                    success = '가입 신청이 완료됐습니다. 관리자 승인 후 로그인 가능합니다.'
                except pymysql.err.IntegrityError:
                    error = '이미 가입 신청된 아이디입니다.'
                finally:
                    db.close()

    return render_template('signup.html', error=error, success=success)


@app.route('/logout')
def logout():
    token = request.cookies.get(REMEMBER_COOKIE)
    clear_remember_token(token)
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.delete_cookie(REMEMBER_COOKIE)
    return resp


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard_v2.html', user=session['user'])


# ─── BigQuery 필터 빌더 ────────────────────────────────────────────
def build_bq_filters(args):
    conditions = []
    params = []

    def _arr(key, col, bq_name):
        vals = [v.strip() for v in args.getlist(key) if v.strip()]
        if vals:
            conditions.append(f'{col} IN UNNEST(@{bq_name})')
            params.append(bigquery.ArrayQueryParameter(bq_name, 'STRING', vals))

    months = args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    _arr('group',      '`Group`',    'group_vals')
    _arr('department', 'Department', 'dept_vals')
    _arr('continent',  'Continent2', 'continent_vals')
    _arr('country',    'Country',    'country_vals')
    _arr('customer',   'Customer',   'customer_vals')
    _arr('line',       'Line',       'line_vals')
    _arr('category',   'Category',   'category_vals')
    _arr('sales_type', 'Sales_Type', 'sales_type_vals')

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


# ─── API 엔드포인트 ────────────────────────────────────────────────
@app.route('/api/clear-cache', methods=['POST'])
@admin_required
def api_clear_cache():
    with _cache_lock:
        count = len(_query_cache)
        _query_cache.clear()
    print(f'[cache] 수동 초기화: {count}개 항목 삭제')
    return jsonify({'ok': True, 'cleared': count})


@app.route('/api/filters')
@login_required
def api_filters():
    T = config.BQ_TABLE
    queries = {
        'departments': (f"SELECT DISTINCT Department FROM `{T}` WHERE Department IS NOT NULL AND Department != '' ORDER BY Department", 'Department'),
        'customers':   (f"SELECT DISTINCT Customer  FROM `{T}` WHERE Customer IS NOT NULL AND Customer != '' ORDER BY Customer",   'Customer'),
        'months':      (f"SELECT DISTINCT Year_Month FROM `{T}` ORDER BY Year_Month",                          'Year_Month'),
        'sales_types': (f"SELECT DISTINCT Sales_Type FROM `{T}` WHERE Sales_Type IS NOT NULL AND Sales_Type != '' ORDER BY Sales_Type", 'Sales_Type'),
        'lines':       (f"SELECT DISTINCT Line FROM `{T}` WHERE Line IS NOT NULL AND Line != '' ORDER BY Line",               'Line'),
        'categories':  (f"SELECT DISTINCT Category FROM `{T}` WHERE Category IS NOT NULL AND Category != '' ORDER BY Category",   'Category'),
        'countries':   (f"SELECT DISTINCT Country FROM `{T}` WHERE Country IS NOT NULL AND Country != '' ORDER BY Country", 'Country'),
        'continents':  (f"SELECT DISTINCT Continent2 FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2 != '' ORDER BY Continent2", 'Continent2'),
        'groups':      (f"SELECT DISTINCT `Group` FROM `{T}` WHERE `Group` IS NOT NULL AND `Group` != '' ORDER BY `Group`", 'Group'),
    }
    hier_queries = {
        'group_dept':      f"SELECT DISTINCT `Group`, Department FROM `{T}` WHERE `Group` IS NOT NULL AND `Group` != '' AND Department IS NOT NULL AND Department != '' ORDER BY `Group`, Department",
        'continent_country': f"SELECT DISTINCT Continent2, Country FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2 != '' AND Country IS NOT NULL AND Country != '' ORDER BY Continent2, Country",
        'country_customer':  f"SELECT DISTINCT Country, Customer FROM `{T}` WHERE Country IS NOT NULL AND Country != '' AND Customer IS NOT NULL AND Customer != '' ORDER BY Country, Customer",
        'line_category':   f"SELECT DISTINCT Line, Category FROM `{T}` WHERE Line IS NOT NULL AND Line != '' AND Category IS NOT NULL AND Category != '' ORDER BY Line, Category",
    }

    def fetch_one(item):
        key, (sql, col) = item
        return key, [r[col] for r in run_query_cached(sql)]

    def fetch_hier(item):
        key, sql = item
        rows = run_query_cached(sql)
        mapping = {}
        if key == 'group_dept':
            for r in rows:
                mapping.setdefault(r['Group'], []).append(r['Department'])
        elif key == 'continent_country':
            for r in rows:
                mapping.setdefault(r['Continent2'], []).append(r['Country'])
        elif key == 'country_customer':
            for r in rows:
                mapping.setdefault(r['Country'], []).append(r['Customer'])
        elif key == 'line_category':
            for r in rows:
                mapping.setdefault(r['Line'], []).append(r['Category'])
        return key, mapping

    with ThreadPoolExecutor(max_workers=len(queries) + len(hier_queries)) as ex:
        flat = dict(ex.map(fetch_one, queries.items()))
        hier = dict(ex.map(fetch_hier, hier_queries.items()))

    flat.update(hier)
    return jsonify(flat)


@app.route('/api/kpi')
@login_required
def api_kpi():
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
    rows = run_query_cached(sql, params)
    row = rows[0] if rows else {}
    result = {k: (float(v) if v is not None else 0) for k, v in row.items()}
    return jsonify(result)


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
    rows = run_query_cached(sql, params)
    return jsonify(rows)


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
    rows = run_query_cached(sql, params)
    return jsonify(rows)


@app.route('/api/customer')
@login_required
def api_customer():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Customer,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Customer
        ORDER BY sales_amount DESC
        LIMIT 30
    """
    rows = run_query_cached(sql, params)
    return jsonify(rows)


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
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Product_Name, Product_Code
        ORDER BY sales_amount DESC
        LIMIT 30
    """
    rows = run_query_cached(sql, params)
    return jsonify(rows)


@app.route('/api/sales-type')
@login_required
def api_sales_type():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Sales_Type,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SUM(Sales_Quantity)    AS sales_quantity,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Sales_Type ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/line')
@login_required
def api_line():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Line,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Line ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/category')
@login_required
def api_category():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Category,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Category ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/country')
@login_required
def api_country():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Country,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Country ORDER BY sales_amount DESC
        LIMIT 30
    """
    return jsonify(run_query_cached(sql, params))


def _build_export_filters(args):
    """Shared filter + search logic for export endpoints."""
    where, params = build_bq_filters(args)
    search = args.get('search', '').strip()
    if search:
        sc = ("(LOWER(Customer) LIKE LOWER(@search_q) OR LOWER(Product_Name) LIKE LOWER(@search_q)"
              " OR LOWER(Product_Code) LIKE LOWER(@search_q) OR LOWER(Department) LIKE LOWER(@search_q))")
        where = (where + f' AND {sc}') if where else f'WHERE {sc}'
        params.append(bigquery.ScalarQueryParameter('search_q', 'STRING', f'%{search}%'))
    return where, params


@app.route('/api/export-count')
@login_required
def api_export_count():
    where, params = _build_export_filters(request.args)
    sql = f"SELECT COUNT(*) AS cnt FROM `{config.BQ_TABLE}` {where}"
    rows = run_query_cached(sql, params)
    cnt = rows[0]['cnt'] if rows else 0
    return jsonify({'count': int(cnt)})


@app.route('/api/export-csv')
@login_required
def api_export_csv():
    import csv, io
    where, params = _build_export_filters(request.args)

    chunk_size = int(request.args.get('chunk_size', 0))
    chunk_num  = int(request.args.get('chunk_num',  1))

    SELECT_COLS = ("Year_Month, `Group`, Department, Sales_Type, Line, Category, Country, Customer,"
                   " Product_Name, Product_Code, Specification, Sales_Quantity, Sales_Amount,"
                   " Cost_of_Sales, Gross_Profit, SG_and_A_Expenses, Operating_Income")
    sql = f"SELECT {SELECT_COLS} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month, Sales_Amount DESC"
    if chunk_size > 0:
        offset = (chunk_num - 1) * chunk_size
        sql += f" LIMIT {chunk_size} OFFSET {offset}"

    rows = run_query_cached(sql, params)

    col_names  = ['Year_Month','Group','Department','Sales_Type','Line','Category','Country','Customer',
                  'Product_Name','Product_Code','Specification','Sales_Quantity','Sales_Amount',
                  'Cost_of_Sales','Gross_Profit','SG_and_A_Expenses','Operating_Income']
    col_labels = ['연월','그룹','부서','판매유형','라인','카테고리','국가','거래처','품명','품번','규격',
                  '수량','매출액','매출원가','매출총이익','판관비','공헌이익']

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(col_labels)
    for row in rows:
        writer.writerow([row.get(c, '') if row.get(c) is not None else '' for c in col_names])

    filename = f"FI_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    from flask import Response
    return Response(
        '﻿' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"}
    )


@app.route('/api/raw')
@login_required
def api_raw():
    export = request.args.get('export', '0') == '1'
    where, params = build_bq_filters(request.args)

    # Optional full-text search across key string columns
    search = request.args.get('search', '').strip()
    if search:
        search_cond = "(LOWER(Customer) LIKE LOWER(@search_q) OR LOWER(Product_Name) LIKE LOWER(@search_q) OR LOWER(Product_Code) LIKE LOWER(@search_q) OR LOWER(Department) LIKE LOWER(@search_q))"
        where = (where + f' AND {search_cond}') if where else f'WHERE {search_cond}'
        params.append(bigquery.ScalarQueryParameter('search_q', 'STRING', f'%{search}%'))

    def serialize(raw):
        rows = []
        for row in raw:
            r = {}
            for k, v in row.items():
                r[k] = int(v) if isinstance(v, int) else (float(v) if isinstance(v, float) else (v or ''))
            rows.append(r)
        return rows

    SELECT_COLS = """
        Year_Month, Department, `Group`, Sales_Type, Line, Category, Country,
        Customer, Product_Name, Product_Code, Specification,
        Sales_Quantity, Sales_Amount, Cost_of_Sales, Gross_Profit,
        SG_and_A_Expenses, Operating_Income
    """

    if export:
        sql = f"SELECT {SELECT_COLS} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT 50000"
        rows = serialize(run_query_cached(sql, params))
        return jsonify({'total': len(rows), 'rows': rows})

    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(10, int(request.args.get('per_page', 100))))
    except ValueError:
        page, per_page = 1, 100
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) AS cnt FROM `{config.BQ_TABLE}` {where}"
    total = (run_query_cached(count_sql, params) or [{'cnt': 0}])[0]['cnt']

    sql = f"SELECT {SELECT_COLS} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT {per_page} OFFSET {offset}"
    rows = serialize(run_query_cached(sql, params))
    return jsonify({'total': int(total), 'page': page, 'per_page': per_page, 'rows': rows})


# ─── 어드민 ────────────────────────────────────────────────────────
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


_ALLOWED_DIM = {'Sales_Type','Department','Line','Category','Continent2','Customer','Country','Group'}
_BQ_RESERVED = {'Group'}

def _col(dim):
    return f'`{dim}`' if dim in _BQ_RESERVED else dim

@app.route('/api/monthly-by-dim')
@login_required
def api_monthly_by_dim():
    dim = request.args.get('dim', '').strip()
    if dim not in _ALLOWED_DIM:
        return jsonify({'error': 'invalid dim'}), 400
    col = _col(dim)
    where, params = build_bq_filters(request.args)
    null_cond = f"{col} IS NOT NULL AND {col} != ''"
    full_where = (where + f' AND {null_cond}') if where else f'WHERE {null_cond}'
    sql = f"""
        SELECT Year_Month, {col} AS dim_value, SUM(Sales_Amount) AS sales_amount
        FROM `{config.BQ_TABLE}`
        {full_where}
        GROUP BY Year_Month, {col}
        ORDER BY Year_Month, sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/group')
@login_required
def api_group():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            `Group`,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY `Group` ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/continent')
@login_required
def api_continent():
    where, params = build_bq_filters(request.args)
    cont_cond = "Continent2 IS NOT NULL AND Continent2 != ''"
    if where:
        full_where = where + f' AND {cont_cond}'
    else:
        full_where = f'WHERE {cont_cond}'
    sql = f"""
        SELECT
            Continent2,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {full_where}
        GROUP BY Continent2 ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


# ─── 통합 프리패치 엔드포인트 ──────────────────────────────────────
# 프론트에서 4~9번 개별 호출하던 걸 1번 왕복으로 통합
@app.route('/api/prefetch')
@login_required
def api_prefetch():
    T = config.BQ_TABLE
    cat = request.args.get('cat', 'org')
    vl  = int(request.args.get('vl', '0'))
    is_sales = (cat == 'sales')

    where, params = build_bq_filters(request.args)

    # KPI SQL
    def kpi_sql(w):
        return f"""
            SELECT SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales,
                   SUM(Gross_Profit) AS gross_profit,
                   SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount))*100 AS gross_margin,
                   SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Operating_Income) AS operating_income,
                   SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount))*100 AS operating_margin,
                   SUM(Sales_Quantity) AS sales_quantity
            FROM `{T}` {w}
        """

    # Trend SQL
    def trend_sql(w):
        return f"""
            SELECT Year_Month, SUM(Sales_Amount) AS sales_amount, SUM(Gross_Profit) AS gross_profit,
                   SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses,
                   SUM(Cost_of_Sales) AS cost_of_sales
            FROM `{T}` {w} GROUP BY Year_Month ORDER BY Year_Month
        """

    # dim → monthly-by-dim
    _dim_map = {
        ('org', 0): 'Group', ('org', 1): 'Department',
        ('region', 0): 'Continent2', ('region', 1): 'Country', ('region', 2): 'Customer',
        ('product', 0): 'Line', ('product', 1): 'Category',
        ('sales', 0): 'Sales_Type',
    }
    dim = _dim_map.get((cat, vl))

    def tbd_sql(w, d):
        col = f'`{d}`' if d in ('Group',) else d
        null_c = f"{col} IS NOT NULL AND {col} != ''"
        fw = (w + f' AND {null_c}') if w else f'WHERE {null_c}'
        return f"""
            SELECT Year_Month, {col} AS dim_value, SUM(Sales_Amount) AS sales_amount
            FROM `{T}` {fw} GROUP BY Year_Month, {col} ORDER BY Year_Month, sales_amount DESC
        """

    # Breakdown SQL
    _bkd_sql = {
        ('org', 0):     lambda w: f"SELECT `Group`, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY `Group` ORDER BY sales_amount DESC",
        ('org', 1):     lambda w: f"SELECT Department, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Department ORDER BY sales_amount DESC",
        ('region', 0):  lambda w: f"SELECT Continent2, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {(w + ' AND') if w else 'WHERE'} Continent2 IS NOT NULL AND Continent2!='' GROUP BY Continent2 ORDER BY sales_amount DESC",
        ('region', 1):  lambda w: f"SELECT Country, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Country ORDER BY sales_amount DESC LIMIT 30",
        ('region', 2):  lambda w: f"SELECT Customer, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Customer ORDER BY sales_amount DESC LIMIT 30",
        ('product', 0): lambda w: f"SELECT Line, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Line ORDER BY sales_amount DESC",
        ('product', 1): lambda w: f"SELECT Category, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Category ORDER BY sales_amount DESC",
        ('product', 2): lambda w: f"SELECT Product_Name, Product_Code, SUM(Sales_Quantity) AS sales_quantity, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Product_Name,Product_Code ORDER BY sales_amount DESC LIMIT 30",
        ('sales', 0):   lambda w: f"SELECT Sales_Type, SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SUM(Sales_Quantity) AS sales_quantity, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin FROM `{T}` {w} GROUP BY Sales_Type ORDER BY sales_amount DESC",
    }

    # Build params for B2B / B2C (sales category only)
    def _build_where_for(sv):
        from werkzeug.datastructures import ImmutableMultiDict
        d = request.args.to_dict(flat=False)
        if sv == 'all':
            d.pop('sales_type', None)
        else:
            d['sales_type'] = [sv]
        return build_bq_filters(ImmutableMultiDict([(k, v) for k, vs in d.items() for v in vs]))

    # Assemble parallel tasks
    breakdown_sql = _bkd_sql.get((cat, vl), lambda w: '')(where)
    tasks = {
        'kpi':   (kpi_sql(where), params),
        'trend': (trend_sql(where), params),
    }
    if breakdown_sql:
        tasks['breakdown'] = (breakdown_sql, params)
    if dim:
        tasks['trendByDim'] = (tbd_sql(where, dim), params)
    if is_sales:
        w_all, p_all = _build_where_for('all')
        w_b2b, p_b2b = _build_where_for('B2B')
        w_b2c, p_b2c = _build_where_for('B2C')
        tasks['kpiAll']   = (kpi_sql(w_all),   p_all)
        tasks['kpiB2B']   = (kpi_sql(w_b2b),   p_b2b)
        tasks['kpiB2C']   = (kpi_sql(w_b2c),   p_b2c)
        tasks['trendB2B'] = (trend_sql(w_b2b),  p_b2b)
        tasks['trendB2C'] = (trend_sql(w_b2c),  p_b2c)

    def fetch_task(item):
        key, (sql, prm) = item
        return key, run_query_cached(sql, prm)

    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        results = dict(ex.map(fetch_task, tasks.items()))

    def fmt_kpi(rows):
        row = rows[0] if rows else {}
        return {k: (float(v) if v is not None else 0) for k, v in row.items()}

    out = {
        'kpi':       fmt_kpi(results.get('kpi', [])),
        'trend':     results.get('trend', []),
        'breakdown': results.get('breakdown', []),
        'trendByDim': results.get('trendByDim', []),
    }
    if is_sales:
        out['kpiAll']   = fmt_kpi(results.get('kpiAll', []))
        out['kpiB2B']   = fmt_kpi(results.get('kpiB2B', []))
        out['kpiB2C']   = fmt_kpi(results.get('kpiB2C', []))
        out['trendB2B'] = results.get('trendB2B', [])
        out['trendB2C'] = results.get('trendB2C', [])

    return jsonify(out)


@app.route('/api/cache/clear', methods=['POST'])
@admin_required
def api_cache_clear():
    """월 데이터 업데이트 후 관리자가 호출해 캐시 초기화 + 재워밍."""
    with _cache_lock:
        _query_cache.clear()
    threading.Thread(target=_warm_cache, daemon=True).start()
    return jsonify({'ok': True, 'message': '캐시 초기화 및 재워밍 시작'})


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
