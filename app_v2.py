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

OTHERS_GROUPS = ['ETC', 'FI', 'Sales Operation', '전사']
_GN = "CASE WHEN `Group` IN ('ETC','FI','Sales Operation','전사') THEN 'Others' ELSE `Group` END"

# Division 파생식: FI_SM JOIN 컨텍스트용 (fi=FI_Final alias, dm=div_map alias)
_DIV_EXPR_FI = """COALESCE(dm.Division, CASE
    WHEN fi.Department LIKE 'DD_Distribution%' THEN '유통2본부'
    WHEN fi.Department = 'B2B1' THEN '영업본부'
    ELSE fi.Department END)"""

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


_DATE_NAME_HINTS = {'date', 'month', 'year', 'time', 'period', 'quarter', 'week', 'day'}

def _get_tableau_fields():
    cache_key = '__tableau_fields__'
    with _cache_lock:
        entry = _query_cache.get(cache_key)
        if entry and time.time() - entry[0] < 3600:
            return entry[1]
    client = get_bq_client()
    table = client.get_table(config.BQ_TABLE)
    dimensions, measures, date_dims = [], [], []
    for field in table.schema:
        ftype = field.field_type.upper()
        fname_lower = field.name.lower()
        if ftype in ('DATE', 'DATETIME', 'TIMESTAMP'):
            dimensions.append(field.name)
            date_dims.append(field.name)
        elif ftype == 'STRING':
            dimensions.append(field.name)
            if any(hint in fname_lower for hint in _DATE_NAME_HINTS):
                date_dims.append(field.name)
        elif ftype in ('INT64', 'INTEGER', 'FLOAT64', 'FLOAT', 'NUMERIC', 'BIGNUMERIC'):
            measures.append(field.name)
    result = (dimensions, measures, date_dims)
    with _cache_lock:
        _query_cache[cache_key] = (time.time(), result)
    return result


# ─── 테이블 스키마 introspection (Brand/Continent1 등 선택 컬럼 존재 여부 캐시) ──
_columns_cache = None
_columns_lock = threading.Lock()


def table_columns():
    """BQ 테이블의 실제 컬럼 집합을 1회 조회 후 캐시. 실패 시 빈 집합.

    Brand / Continent1 같은 선택 컬럼이 테이블에 존재할 때만
    원시데이터 컬럼·필터 드롭다운을 노출하기 위해 사용 (없으면 조용히 생략).
    """
    global _columns_cache
    if _columns_cache is not None:
        return _columns_cache
    with _columns_lock:
        if _columns_cache is not None:
            return _columns_cache
        cols = set()
        try:
            parts = config.BQ_TABLE.replace('`', '').split('.')
            table_name = parts[-1]
            schema_ref = '.'.join(parts[:-1]) + '.INFORMATION_SCHEMA.COLUMNS'
            sql = f"SELECT column_name FROM `{schema_ref}` WHERE table_name = @t"
            rows = run_query(sql, [bigquery.ScalarQueryParameter('t', 'STRING', table_name)])
            cols = {r['column_name'] for r in rows}
        except Exception as e:
            print('[schema] 컬럼 조회 실패 (선택 컬럼 비활성):', e)
        _columns_cache = cols
        return _columns_cache


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

        print(f'[cache] 워밍업 완료 ({len(all_sqls)}개 쿼리 캐시 적재)')
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


@app.route('/report')
@login_required
def report():
    return render_template('report.html', user=session['user'])


# ─── BigQuery 필터 빌더 ────────────────────────────────────────────
def _arr_filter(conditions, params, args, key, col, bq_name):
    vals = [v.strip() for v in args.getlist(key) if v.strip()]
    if vals:
        conditions.append(f'{col} IN UNNEST(@{bq_name})')
        params.append(bigquery.ArrayQueryParameter(bq_name, 'STRING', vals))


def _serialize_rows(raw):
    rows = []
    for row in raw:
        r = {}
        for k, v in row.items():
            r[k] = int(v) if isinstance(v, int) else (float(v) if isinstance(v, float) else (v or ''))
        rows.append(r)
    return rows


def _related_table(suffix):
    parts = config.BQ_TABLE.replace('`', '').split('.')
    return '.'.join(parts[:-1]) + '.' + suffix


def build_bq_filters(args):
    conditions = []
    params = []

    def _arr(key, col, bq_name):
        _arr_filter(conditions, params, args, key, col, bq_name)

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

    # division 필터: FI_SM에서 Department로 역매핑 (FI_Final에 Division 컬럼 없음)
    div_vals = [v.strip() for v in args.getlist('division') if v.strip()]
    if div_vals:
        _sm = _fi_sm_table()
        _null_div = [
            ('DD_Distribution 2_Part 1', '유통2본부'),
            ('DD_Distribution 2_Part 2', '유통2본부'),
            ('DD_Distribution 2_Part 3', '유통2본부'),
            ('B2B1', '영업본부'),
        ]
        extra = [f"SELECT '{d}' AS Department" for d, dv in _null_div if dv in div_vals]
        extra_sql = (' UNION DISTINCT ' + ' UNION DISTINCT '.join(extra)) if extra else ''
        conditions.append(
            f'Department IN (SELECT Department FROM `{_sm}` '
            f'WHERE Division IN UNNEST(@div_vals){extra_sql})'
        )
        params.append(bigquery.ArrayQueryParameter('div_vals', 'STRING', div_vals))

    # 선택 컬럼(테이블에 존재할 때만) — 브랜드·권역
    _cols = table_columns()
    if 'Brand' in _cols:
        _arr('brand', 'Brand', 'brand_vals')
    if 'Continent1' in _cols:
        _arr('continent1', 'Continent1', 'cont1_vals')

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


# ─── Tableau Builder API ───────────────────────────────────────────
@app.route('/api/tableau/fields')
@login_required
def api_tableau_fields():
    dims, meas, date_dims = _get_tableau_fields()
    return jsonify({'dimensions': dims, 'measures': meas, 'date_dims': date_dims})


_PL_BLOCK_ANCHORS = {'sales', 'gross', 'sgaD', 'direct', 'sgaO', 'contrib', 'sgaC', 'op'}
_PL_SUB_KEYS = {'adv', 'log', 'fee', 'hr', 'etc'}
_PL_SECTION_IDS = {'all', 'SK', 'UM'}


def _validate_pl_config(cfg):
    """kind='pl' config 구조 검증. 문제 없으면 None, 있으면 에러 메시지 문자열 반환."""
    if not isinstance(cfg, dict):
        return 'config must be an object'
    rows = cfg.get('rows', {})
    if not isinstance(rows, dict):
        return 'rows must be an object'
    block_order = rows.get('blockOrder', [])
    if not isinstance(block_order, list) or not all(isinstance(x, str) and x in _PL_BLOCK_ANCHORS for x in block_order):
        return 'rows.blockOrder must be a list of valid block anchors'
    sub_order = rows.get('subOrder', {})
    if not isinstance(sub_order, dict):
        return 'rows.subOrder must be an object'
    for anchor, keys in sub_order.items():
        if anchor not in ('sgaD', 'sgaO', 'sgaC'):
            return f'invalid subOrder anchor: {anchor}'
        if not isinstance(keys, list) or not all(isinstance(k, str) and k in _PL_SUB_KEYS for k in keys):
            return f'subOrder[{anchor}] must be a list of valid sub-keys'
    hidden = rows.get('hidden', [])
    valid_hidden_ids = {f'{a}.{k}' for a in ('sgaD', 'sgaO', 'sgaC') for k in _PL_SUB_KEYS}
    if not isinstance(hidden, list) or not all(isinstance(x, str) and x in valid_hidden_ids for x in hidden):
        return 'rows.hidden must be a list of valid sub-account row ids'
    custom = rows.get('custom', [])
    if not isinstance(custom, list):
        return 'rows.custom must be a list'
    for c in custom:
        if not isinstance(c, dict):
            return 'each rows.custom entry must be an object'
        if not isinstance(c.get('id'), str) or not isinstance(c.get('label'), str) or not isinstance(c.get('formula'), str):
            return 'rows.custom entries need string id/label/formula'
        if c.get('afterId') not in _PL_BLOCK_ANCHORS:
            return 'rows.custom.afterId must be a valid block anchor'
        if 'valueFormat' in c and c['valueFormat'] not in ('money', 'percent'):
            return 'rows.custom.valueFormat must be money or percent'
    sections = cfg.get('sections', {})
    if not isinstance(sections, dict):
        return 'sections must be an object'
    for key in ('order', 'hidden'):
        vals = sections.get(key, [])
        if not isinstance(vals, list) or not all(isinstance(x, str) and x in _PL_SECTION_IDS for x in vals):
            return f'sections.{key} must be a list of valid section ids'
    dept_overrides = sections.get('deptOverrides', {})
    if not isinstance(dept_overrides, dict) or not all(v in ('SK', 'UM', 'exclude') for v in dept_overrides.values()):
        return 'sections.deptOverrides must map department names to SK/UM/exclude'
    return None


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
    if kind == 'pl':
        err = _validate_pl_config(cfg)
        if err:
            return jsonify({'error': err}), 400
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


@app.route('/api/views/<int:view_id>', methods=['PUT'])
@login_required
def api_views_update(view_id):
    username = session['user']['username']
    data = request.get_json() or {}
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT id, kind FROM user_views WHERE id=%s AND username=%s",
                (view_id, username)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({'error': '권한 없음'}), 403
            if 'config' in data and row['kind'] == 'pl':
                err = _validate_pl_config(data['config'])
                if err:
                    return jsonify({'error': err}), 400
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


@app.route('/api/tableau/query', methods=['POST'])
@login_required
def api_tableau_query():
    data = request.get_json() or {}
    cfg = data.get('config', {})
    dims, meas_list, _date_dims = _get_tableau_fields()
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
    _valid_aggs = {'SUM', 'AVG', 'MIN', 'MAX', 'COUNT', 'COUNTD'}
    measure_aggs = cfg.get('measureAggs') or {}
    for m in measures:
        raw_agg = str(measure_aggs.get(m, 'SUM')).upper()
        agg = raw_agg if raw_agg in _valid_aggs else 'SUM'
        if agg == 'COUNTD':
            select_parts.append(f'COUNT(DISTINCT `{m}`) AS `{m}`')
        else:
            select_parts.append(f'{agg}(`{m}`) AS `{m}`')

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


@app.route('/api/tableau/filter-values')
@login_required
def api_tableau_filter_values():
    field = request.args.get('field', '')
    dims, meas_list, _date_dims = _get_tableau_fields()
    if field not in set(dims + meas_list):
        return jsonify({'error': '유효하지 않은 필드'}), 400
    sql = f"SELECT DISTINCT `{field}` FROM `{config.BQ_TABLE}` WHERE `{field}` IS NOT NULL ORDER BY `{field}` LIMIT 500"
    try:
        rows = run_query_cached(sql, [], ttl=300)
        values = [str(r[field]) for r in rows if r[field] is not None]
        return jsonify({'values': values})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    # 대륙(Continent2) — 항상 존재. 권역(Continent1)·브랜드(Brand)는 컬럼이 있을 때만.
    _fcols = table_columns()
    queries['continents2'] = (f"SELECT DISTINCT Continent2 FROM `{T}` WHERE Continent2 IS NOT NULL AND Continent2 != '' ORDER BY Continent2", 'Continent2')
    if 'Continent1' in _fcols:
        queries['continents1'] = (f"SELECT DISTINCT Continent1 FROM `{T}` WHERE Continent1 IS NOT NULL AND Continent1 != '' ORDER BY Continent1", 'Continent1')
    if 'Brand' in _fcols:
        queries['brands'] = (f"SELECT DISTINCT Brand FROM `{T}` WHERE Brand IS NOT NULL AND Brand != '' ORDER BY Brand", 'Brand')
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

    # 선택 컬럼(테이블에 존재할 때만) — 브랜드·권역, build_bq_filters와 동일 관례
    _cols = table_columns()
    col_defs = [('Year_Month', '연월'), ('Group', '그룹'), ('Department', '부서')]
    if 'Brand' in _cols:
        col_defs.append(('Brand', '브랜드'))
    col_defs.append(('Sales_Type', '판매유형'))
    if 'Continent1' in _cols:
        col_defs.append(('Continent1', '권역'))
    col_defs += [
        ('Continent2', '대륙'), ('Country', '국가'), ('Customer', '거래처'),
        ('Line', '라인'), ('Category', '카테고리'), ('Product_Name', '품명'),
        ('Product_Code', '품번'), ('Specification', '규격'),
        ('Sales_Quantity', '수량'), ('Sales_Amount', '매출액'), ('Cost_of_Sales', '매출원가'),
        ('Gross_Profit', '매출총이익'), ('SG_and_A_Expenses', '판관비'), ('Operating_Income', '영업이익'),
    ]
    col_names  = [c for c, _ in col_defs]
    col_labels = [l for _, l in col_defs]

    select_cols = ', '.join(f'`{c}`' if c == 'Group' else c for c in col_names)
    sql = f"SELECT {select_cols} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month, Sales_Amount DESC"
    if chunk_size > 0:
        offset = (chunk_num - 1) * chunk_size
        sql += f" LIMIT {chunk_size} OFFSET {offset}"

    rows = run_query_cached(sql, params)

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

    if export:
        sql = f"SELECT * FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT 50000"
        rows = _serialize_rows(run_query_cached(sql, params))
        cols = list(rows[0].keys()) if rows else []
        return jsonify({'total': len(rows), 'columns': cols, 'rows': rows})

    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(10, int(request.args.get('per_page', 100))))
    except ValueError:
        page, per_page = 1, 100
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) AS cnt FROM `{config.BQ_TABLE}` {where}"
    total = (run_query_cached(count_sql, params) or [{'cnt': 0}])[0]['cnt']

    sql = f"SELECT * FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT {per_page} OFFSET {offset}"
    rows = _serialize_rows(run_query_cached(sql, params))
    cols = list(rows[0].keys()) if rows else list(table_columns())
    return jsonify({'total': int(total), 'page': page, 'per_page': per_page, 'columns': cols, 'rows': rows})


def _fi_final_sm_table():
    return _related_table('FI_Final_SM')


def _fi_sga_agg_table():
    return _related_table('FI_SGA_Agg')

# 비율·비중 컬럼 — 일반 사용자에게 노출하지 않음
_SGA_EXCLUDE = (
    'country_ratio, continent1_ratio, continent2_ratio, '
    'brand_ratio, line_ratio, category_ratio, sales_type_ratio, '
    'alloc_pct_of_dept, alloc_pct_of_acct'
)
_SGA_SELECT = f'SELECT * EXCEPT({_SGA_EXCLUDE})'


def _paginated_raw_response(table, conditions, params, order_by, select='SELECT *'):
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

    if request.args.get('export', '0') == '1':
        sql = f"{select} FROM `{table}` {where} ORDER BY {order_by} LIMIT 50000"
        rows = _serialize_rows(run_query_cached(sql, params))
        cols = list(rows[0].keys()) if rows else []
        return jsonify({'total': len(rows), 'columns': cols, 'rows': rows})

    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(10, int(request.args.get('per_page', 100))))
    except ValueError:
        page, per_page = 1, 100
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}` {where}"
    total = (run_query_cached(count_sql, params) or [{'cnt': 0}])[0]['cnt']

    sql = f"{select} FROM `{table}` {where} ORDER BY {order_by} LIMIT {per_page} OFFSET {offset}"
    rows = _serialize_rows(run_query_cached(sql, params))
    cols = list(rows[0].keys()) if rows else []
    return jsonify({'total': int(total), 'page': page, 'per_page': per_page, 'columns': cols, 'rows': rows})


@app.route('/api/raw_adj')
@login_required
def api_raw_adj():
    """FI_Final 조정 내역 — Product_Code IS NULL인 조정 행(조정)을 반환."""
    where, params = build_bq_filters(request.args)
    adj_cond = "Product_Code IS NULL AND Product_Name = '(조정)'"
    full_where = f"WHERE {adj_cond}" if not where else f"{where} AND {adj_cond}"
    sql = f"""
        SELECT Year_Month, `Group`, Department,
            NULL AS Customer,
            Sales_Amount  AS Sales_Adj,
            Cost_of_Sales AS COGS_Adj
        FROM `{config.BQ_TABLE}`
        {full_where}
          AND (Sales_Amount != 0 OR Cost_of_Sales != 0)
        ORDER BY Year_Month DESC, Department
    """
    rows = run_query_cached(sql, params)
    result = []
    for r in rows:
        result.append({
            'Year_Month': r['Year_Month'],
            'Group':      r['Group'],
            'Department': r['Department'],
            'Customer':   None,
            'Sales_Adj':  int(r['Sales_Adj']) if r['Sales_Adj'] is not None else None,
            'COGS_Adj':   int(r['COGS_Adj'])  if r['COGS_Adj']  is not None else None,
        })
    return jsonify(result)


@app.route('/api/raw_sm')
@login_required
def api_raw_sm():
    SM = _fi_sm_table()
    conditions = []
    params = []

    months = request.args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    _arr_filter(conditions, params, request.args, 'department',          'Department',          'dept_vals')
    _arr_filter(conditions, params, request.args, 'cost_center_class',   'Cost_Center_Class',   'ccc_vals')
    _arr_filter(conditions, params, request.args, 'indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
    _arr_filter(conditions, params, request.args, 'main_category',       'Main_Category',       'maincat_vals')

    return _paginated_raw_response(SM, conditions, params, 'Year_Month DESC, Amount DESC')


@app.route('/api/raw_final_sm')
@login_required
def api_raw_final_sm():
    FSM = _fi_final_sm_table()
    conditions = []
    params = []

    months = request.args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    _arr_filter(conditions, params, request.args, 'department',          'Department',          'dept_vals')
    _arr_filter(conditions, params, request.args, 'item_class',          'Item_Class',          'item_class_vals')
    _arr_filter(conditions, params, request.args, 'indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
    _arr_filter(conditions, params, request.args, 'main_category',       'Main_Category',       'maincat_vals')

    return _paginated_raw_response(FSM, conditions, params, 'Year_Month DESC, Amount DESC')


@app.route('/api/raw_export')
@login_required
def api_raw_export():
    """SM / FSM / SGA 소스 행 제한 없는 CSV 스트리밍 다운로드."""
    import csv, io
    from flask import stream_with_context, Response as FlaskResponse

    source = request.args.get('source', 'sm')
    conditions, params = [], []

    months = request.args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    def _arr(key, col, bq_name):
        _arr_filter(conditions, params, request.args, key, f'`{col}`', bq_name)

    if source == 'sm':
        table = _fi_sm_table()
        order = 'Year_Month DESC, Amount DESC'
        _arr('department',          'Department',          'dept_vals')
        _arr('indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
        _arr('main_category',       'Main_Category',       'maincat_vals')
        name = 'FI_SM'
    elif source == 'fsm':
        table = _fi_final_sm_table()
        order = 'Year_Month DESC, Amount DESC'
        _arr('department',          'Department',          'dept_vals')
        _arr('item_class',          'Item_Class',          'item_class_vals')
        _arr('indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
        _arr('main_category',       'Main_Category',       'maincat_vals')
        name = 'FI_Final_SM'
    elif source == 'sga':
        table = _fi_sga_agg_table()
        order = 'Year_Month DESC, allocated_amount DESC'
        _arr('department',          'Department',          'dept_vals')
        _arr('country',             'Country',             'country_vals')
        _arr('brand',               'Brand',               'brand_vals')
        _arr('cost_class',          'Cost_Class',          'cost_class_vals')
        _arr('indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
        _arr('main_category',       'SM_Main_Category',    'maincat_vals')
        name = 'FI_SGA_Agg'
    else:
        return jsonify({'error': 'invalid source'}), 400

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    select = _SGA_SELECT if source == 'sga' else 'SELECT *'
    sql = f"{select} FROM `{table}` {where} ORDER BY {order}"

    def generate():
        client = get_bq_client()
        job_config = bigquery.QueryJobConfig(query_parameters=params or [])
        bq_rows = client.query(sql, job_config=job_config).result()
        buf = io.StringIO()
        writer = csv.writer(buf)
        first = True
        for row in bq_rows:
            d = dict(row)
            if first:
                buf.write('﻿')  # BOM — Excel UTF-8 인식용
                writer.writerow(list(d.keys()))
                first = False
            writer.writerow([
                '' if v is None else (int(v) if isinstance(v, int) else (float(v) if isinstance(v, float) else v))
                for v in d.values()
            ])
            chunk = buf.getvalue()
            buf.seek(0); buf.truncate(0)
            yield chunk.encode('utf-8')

    filename = f'{name}_Export.csv'
    return FlaskResponse(
        stream_with_context(generate()),
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{filename}",
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/raw_sga_agg')
@login_required
def api_raw_sga_agg():
    AGG = _fi_sga_agg_table()
    conditions = []
    params = []

    months = request.args.getlist('months')
    if months:
        conditions.append('Year_Month IN UNNEST(@months)')
        params.append(bigquery.ArrayQueryParameter('months', 'STRING', months))

    _arr_filter(conditions, params, request.args, 'department',          'Department',          'dept_vals')
    _arr_filter(conditions, params, request.args, 'country',             'Country',             'country_vals')
    _arr_filter(conditions, params, request.args, 'brand',               'Brand',               'brand_vals')
    _arr_filter(conditions, params, request.args, 'cost_class',          'Cost_Class',          'cost_class_vals')
    _arr_filter(conditions, params, request.args, 'indirect_cost_class', 'Indirect_Cost_Class', 'icc_vals')
    _arr_filter(conditions, params, request.args, 'main_category',       'SM_Main_Category',    'maincat_vals')

    return _paginated_raw_response(AGG, conditions, params, 'Year_Month DESC, allocated_amount DESC', select=_SGA_SELECT)


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


@app.route('/admin/users/<int:uid>/reset-password', methods=['POST'])
@admin_required
def admin_reset_user_password(uid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE dashboard_users SET password_hash=NULL WHERE id=%s", (uid,)
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


@app.route('/api/org-group')
@login_required
def api_org_group():
    where, params = build_bq_filters(request.args)
    T = config.BQ_TABLE
    sql = f"""
        SELECT
            {_GN} AS `Group`,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{T}`
        {where}
        GROUP BY {_GN} ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/org-division')
@login_required
def api_org_division():
    where, params = build_bq_filters(request.args)
    T = config.BQ_TABLE
    SM = _fi_sm_table()
    sql = f"""
        WITH div_map AS (
            SELECT Department, ANY_VALUE(Division) AS Division
            FROM `{SM}` WHERE Division IS NOT NULL GROUP BY Department
        ),
        fi AS (SELECT * FROM `{T}` {where})
        SELECT {_DIV_EXPR_FI} AS Division,
            SUM(fi.Sales_Amount)      AS sales_amount,
            SUM(fi.Cost_of_Sales)     AS cost_of_sales,
            SUM(fi.Gross_Profit)      AS gross_profit,
            SUM(fi.Operating_Income)  AS operating_income,
            SUM(fi.SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(fi.Gross_Profit), SUM(fi.Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(fi.Operating_Income), SUM(fi.Sales_Amount)) * 100 AS operating_margin
        FROM fi LEFT JOIN div_map dm ON fi.Department = dm.Department
        GROUP BY Division ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


@app.route('/api/continent1')
@login_required
def api_continent1():
    where, params = build_bq_filters(request.args)
    cont_cond = "Continent1 IS NOT NULL AND Continent1 != ''"
    full_where = (where + f' AND {cont_cond}') if where else f'WHERE {cont_cond}'
    T = config.BQ_TABLE
    sql = f"""
        SELECT
            Continent1,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Cost_of_Sales)     AS cost_of_sales,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(SG_and_A_Expenses) AS sga_expenses,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{T}`
        {full_where}
        GROUP BY Continent1 ORDER BY sales_amount DESC
    """
    return jsonify(run_query_cached(sql, params))


# ─── 통합 프리패치 엔드포인트 ──────────────────────────────────────
# 프론트에서 4~9번 개별 호출하던 걸 1번 왕복으로 통합
@app.route('/api/prefetch')
@login_required
def api_prefetch():
    T = config.BQ_TABLE
    SM = _fi_sm_table()
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

    def sga_class_sql(w):
        return f"""
            WITH ff AS (
                SELECT Department, Year_Month, SUM(SG_and_A_Expenses) AS sga
                FROM `{T}` {w} GROUP BY Department, Year_Month
            ),
            sm AS (
                SELECT Department, Year_Month, Indirect_Cost_Class AS cls, SUM(Amount) AS amt
                FROM `{SM}` GROUP BY Department, Year_Month, Indirect_Cost_Class
            ),
            sm_tot AS (SELECT Department, Year_Month, SUM(Amount) AS tot FROM `{SM}` GROUP BY Department, Year_Month)
            SELECT
                SUM(CASE WHEN sm.cls='직접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_direct,
                SUM(CASE WHEN sm.cls='조직간접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_org_indirect,
                SUM(CASE WHEN sm.cls='SSG간접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_ssg_indirect
            FROM ff
            JOIN sm     ON ff.Department=sm.Department     AND ff.Year_Month=sm.Year_Month
            JOIN sm_tot ON ff.Department=sm_tot.Department AND ff.Year_Month=sm_tot.Year_Month
        """

    def sga_class_trend_sql(w):
        return f"""
            WITH ff AS (
                SELECT Department, Year_Month, SUM(SG_and_A_Expenses) AS sga
                FROM `{T}` {w} GROUP BY Department, Year_Month
            ),
            sm AS (
                SELECT Department, Year_Month, Indirect_Cost_Class AS cls, SUM(Amount) AS amt
                FROM `{SM}` GROUP BY Department, Year_Month, Indirect_Cost_Class
            ),
            sm_tot AS (SELECT Department, Year_Month, SUM(Amount) AS tot FROM `{SM}` GROUP BY Department, Year_Month)
            SELECT ff.Year_Month,
                SUM(CASE WHEN sm.cls='직접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_direct,
                SUM(CASE WHEN sm.cls='조직간접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_org_indirect,
                SUM(CASE WHEN sm.cls='SSG간접' THEN CAST(ff.sga AS FLOAT64)*SAFE_DIVIDE(sm.amt,sm_tot.tot) ELSE 0 END) AS sga_ssg_indirect
            FROM ff
            JOIN sm     ON ff.Department=sm.Department     AND ff.Year_Month=sm.Year_Month
            JOIN sm_tot ON ff.Department=sm_tot.Department AND ff.Year_Month=sm_tot.Year_Month
            GROUP BY ff.Year_Month ORDER BY ff.Year_Month
        """

    # dim → monthly-by-dim
    _dim_map = {
        ('org', 0): 'Brand', ('org', 1): None, ('org', 2): 'Department',
        ('region', 0): 'Continent1', ('region', 1): 'Continent2', ('region', 2): 'Country', ('region', 3): 'Customer',
        ('product', 0): 'Line', ('product', 1): 'Category', ('product', 2): 'Product_Name',
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
    _m = "SUM(Sales_Amount) AS sales_amount, SUM(Cost_of_Sales) AS cost_of_sales, SUM(Gross_Profit) AS gross_profit, SUM(Operating_Income) AS operating_income, SUM(SG_and_A_Expenses) AS sga_expenses, SAFE_DIVIDE(SUM(Gross_Profit),SUM(Sales_Amount))*100 AS gross_margin, SAFE_DIVIDE(SUM(Operating_Income),SUM(Sales_Amount))*100 AS operating_margin"

    def nf(col, w):
        nc = f"{col} IS NOT NULL AND {col} != ''"
        return f"{w} AND {nc}" if w else f"WHERE {nc}"

    _bkd_sql = {
        ('org', 0):     lambda w: f"SELECT Brand, {_m} FROM `{T}` {w} GROUP BY Brand ORDER BY sales_amount DESC",
        ('org', 1):     lambda w: f"""
            WITH div_map AS (SELECT Department, ANY_VALUE(Division) AS Division FROM `{SM}` WHERE Division IS NOT NULL GROUP BY Department),
            fi AS (SELECT * FROM `{T}` {w})
            SELECT {_DIV_EXPR_FI} AS Division,
                SUM(fi.Sales_Amount) AS sales_amount, SUM(fi.Cost_of_Sales) AS cost_of_sales,
                SUM(fi.Gross_Profit) AS gross_profit, SUM(fi.Operating_Income) AS operating_income,
                SUM(fi.SG_and_A_Expenses) AS sga_expenses,
                SAFE_DIVIDE(SUM(fi.Gross_Profit),SUM(fi.Sales_Amount))*100 AS gross_margin,
                SAFE_DIVIDE(SUM(fi.Operating_Income),SUM(fi.Sales_Amount))*100 AS operating_margin
            FROM fi LEFT JOIN div_map dm ON fi.Department = dm.Department
            GROUP BY Division ORDER BY sales_amount DESC
        """,
        ('org', 2):     lambda w: f"SELECT Department, {_m} FROM `{T}` {nf('Department', w)} GROUP BY Department ORDER BY sales_amount DESC",
        ('region', 0):  lambda w: f"SELECT Continent1, {_m} FROM `{T}` {nf('Continent1', w)} GROUP BY Continent1 ORDER BY sales_amount DESC",
        ('region', 1):  lambda w: f"SELECT Continent2, {_m} FROM `{T}` {nf('Continent2', w)} GROUP BY Continent2 ORDER BY sales_amount DESC",
        ('region', 2):  lambda w: f"SELECT Country, {_m} FROM `{T}` {nf('Country', w)} GROUP BY Country ORDER BY sales_amount DESC LIMIT 50",
        ('region', 3):  lambda w: f"SELECT Customer, {_m} FROM `{T}` {nf('Customer', w)} GROUP BY Customer ORDER BY sales_amount DESC LIMIT 30",
        ('product', 0): lambda w: f"SELECT Line, {_m} FROM `{T}` {nf('Line', w)} GROUP BY Line ORDER BY sales_amount DESC",
        ('product', 1): lambda w: f"SELECT Category, {_m} FROM `{T}` {nf('Category', w)} GROUP BY Category ORDER BY sales_amount DESC",
        ('product', 2): lambda w: f"SELECT Product_Name, Product_Code, SUM(Sales_Quantity) AS sales_quantity, {_m} FROM `{T}` {nf('Product_Name', w)} GROUP BY Product_Name, Product_Code ORDER BY sales_amount DESC LIMIT 30",
        ('sales', 0):   lambda w: f"SELECT Sales_Type, {_m} FROM `{T}` {nf('Sales_Type', w)} GROUP BY Sales_Type ORDER BY sales_amount DESC",
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
    tasks = {
        'kpi':       (kpi_sql(where), params),
        'trend':     (trend_sql(where), params),
        'breakdown': (_bkd_sql.get((cat, vl), lambda w: '')(where), params),
    }
    if dim:
        tasks['trendByDim'] = (tbd_sql(where, dim), params)
    tasks['sgaClass']      = (sga_class_sql(where), params)
    tasks['sgaClassTrend'] = (sga_class_trend_sql(where), params)
    if is_sales:
        w_all, p_all = _build_where_for('all')
        w_b2b, p_b2b = _build_where_for('B2B')
        w_b2c, p_b2c = _build_where_for('B2C')
        tasks['kpiAll']   = (kpi_sql(w_all),   p_all)
        tasks['kpiB2B']   = (kpi_sql(w_b2b),   p_b2b)
        tasks['kpiB2C']   = (kpi_sql(w_b2c),   p_b2c)
        tasks['trendB2B'] = (trend_sql(w_b2b),  p_b2b)
        tasks['trendB2C'] = (trend_sql(w_b2c),  p_b2c)
        tasks['sgaClassAll']      = (sga_class_sql(w_all),  p_all)
        tasks['sgaClassB2B']      = (sga_class_sql(w_b2b),  p_b2b)
        tasks['sgaClassB2C']      = (sga_class_sql(w_b2c),  p_b2c)
        tasks['sgaClassTrendB2B'] = (sga_class_trend_sql(w_b2b), p_b2b)
        tasks['sgaClassTrendB2C'] = (sga_class_trend_sql(w_b2c), p_b2c)

    def fetch_task(item):
        key, (sql, prm) = item
        # 차원이 없는 카테고리(overview 등)는 breakdown SQL이 빈 문자열 → 빈 쿼리 BigQuery 400 방지
        if not sql or not sql.strip():
            return key, []
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

    def _merge_sga_class(kpi_dict, sga_rows):
        row = sga_rows[0] if sga_rows else {}
        kpi_dict['sga_direct']       = float(row.get('sga_direct')       or 0)
        kpi_dict['sga_org_indirect'] = float(row.get('sga_org_indirect') or 0)
        kpi_dict['sga_ssg_indirect'] = float(row.get('sga_ssg_indirect') or 0)

    def _merge_sga_class_trend(trend_list, sga_trend_rows):
        ct = {str(r['Year_Month']): r for r in sga_trend_rows}
        for row in trend_list:
            ym = str(row.get('Year_Month', ''))
            c = ct.get(ym, {})
            row['sga_direct']       = float(c.get('sga_direct')       or 0)
            row['sga_org_indirect'] = float(c.get('sga_org_indirect') or 0)
            row['sga_ssg_indirect'] = float(c.get('sga_ssg_indirect') or 0)

    _merge_sga_class(out['kpi'], results.get('sgaClass', []))
    _merge_sga_class_trend(out['trend'], results.get('sgaClassTrend', []))

    if is_sales:
        _merge_sga_class(out['kpiAll'], results.get('sgaClassAll', []))
        _merge_sga_class(out['kpiB2B'], results.get('sgaClassB2B', []))
        _merge_sga_class(out['kpiB2C'], results.get('sgaClassB2C', []))
        _merge_sga_class_trend(out['trendB2B'], results.get('sgaClassTrendB2B', []))
        _merge_sga_class_trend(out['trendB2C'], results.get('sgaClassTrendB2C', []))

    return jsonify(out)


@app.route('/api/cache/clear', methods=['POST'])
@admin_required
def api_cache_clear():
    """월 데이터 업데이트 후 관리자가 호출해 캐시 초기화 + 재워밍."""
    with _cache_lock:
        _query_cache.clear()
    threading.Thread(target=_warm_cache, daemon=True).start()
    return jsonify({'ok': True, 'message': '캐시 초기화 및 재워밍 시작'})



# ─── 손익계산서 (P&L) API ──────────────────────────────────────────
# 차원별 매출~영업이익 + SG&A를 직접/조직간접/SSG간접 × 5세분류로 월별 반환
_PL_ALLOWED_DIM = {
    'Brand', 'Group', 'Division', 'Department', 'Continent1', 'Continent2',
    'Country', 'Customer', 'Line', 'Category', 'Product_Name', 'Sales_Type',
}
_PL_PIVOT_ALLOWED_DIM = {
    'Department', 'Line', 'Category', 'Country', 'Continent2', 'Customer',
    'Sales_Type', 'Group',
}
_PL_BQ_RESERVED = {'Group'}  # 백틱 필요 컬럼

# FI_SM 테이블 경로 (config.BQ_TABLE에서 project.dataset 추출)
def _fi_sm_table():
    return _related_table('FI_SM')


@app.route('/api/pl')
@login_required
def api_pl():
    dim = request.args.get('dim', '').strip()
    if dim not in _PL_ALLOWED_DIM:
        return jsonify({'error': f'invalid dim. allowed: {sorted(_PL_ALLOWED_DIM)}'}), 400

    where, params = build_bq_filters(request.args)
    T = config.BQ_TABLE
    SM = _fi_sm_table()
    _null_label = '조정' if dim in ('Line', 'Category', 'Product_Name') else '(없음)'

    if dim == 'Division':
        # Division은 FI_Final에 없으므로 FI_SM JOIN으로 파생
        sql_a = f"""
            WITH div_map AS (
                SELECT Department, ANY_VALUE(Division) AS Division
                FROM `{SM}` WHERE Division IS NOT NULL GROUP BY Department
            ),
            fi AS (SELECT * FROM `{T}` {where})
            SELECT {_DIV_EXPR_FI} AS node, fi.Year_Month,
                SUM(fi.Sales_Amount) AS sales,
                SUM(fi.Cost_of_Sales) AS cogs,
                SUM(fi.Gross_Profit) AS gross,
                SUM(fi.Operating_Income) AS op
            FROM fi LEFT JOIN div_map dm ON fi.Department = dm.Department
            GROUP BY node, fi.Year_Month
        """
        sql_b = f"""
            WITH div_map AS (
                SELECT Department, ANY_VALUE(Division) AS Division
                FROM `{SM}` WHERE Division IS NOT NULL GROUP BY Department
            ),
            fi AS (SELECT * FROM `{T}` {where}),
            ff AS (
                SELECT {_DIV_EXPR_FI} AS node, fi.Department, fi.Year_Month,
                    SUM(fi.SG_and_A_Expenses) AS sga
                FROM fi LEFT JOIN div_map dm ON fi.Department = dm.Department
                GROUP BY node, fi.Department, fi.Year_Month
            ),
            sm AS (
                SELECT Department, Year_Month,
                    Indirect_Cost_Class AS cls,
                    CASE Main_Category
                        WHEN '광고선전비' THEN 'adv'
                        WHEN '물류비'     THEN 'log'
                        WHEN '수수료'     THEN 'fee'
                        WHEN '인건비'     THEN 'hr'
                        ELSE 'etc'
                    END AS cat,
                    SUM(Amount) AS amt
                FROM `{SM}`
                GROUP BY Department, Year_Month, Indirect_Cost_Class, Main_Category
            ),
            sm_tot AS (
                SELECT Department, Year_Month, SUM(Amount) AS tot
                FROM `{SM}`
                GROUP BY Department, Year_Month
            )
            SELECT ff.node, ff.Year_Month, sm.cls, sm.cat,
                SUM(CAST(ff.sga AS FLOAT64) * sm.amt / NULLIF(sm_tot.tot, 0)) AS val
            FROM ff
            JOIN sm     ON ff.Department = sm.Department     AND ff.Year_Month = sm.Year_Month
            JOIN sm_tot ON ff.Department = sm_tot.Department AND ff.Year_Month = sm_tot.Year_Month
            GROUP BY ff.node, ff.Year_Month, sm.cls, sm.cat
        """
    else:
        # 백틱 처리: Group은 BQ 예약어
        dimcol = f'`{dim}`' if dim in _PL_BQ_RESERVED else dim

        # 파트 A: 노드×월 직접 측정값 (sales / cogs / gross / op)
        sql_a = f"""
            SELECT {dimcol} AS node, Year_Month,
                SUM(Sales_Amount)      AS sales,
                SUM(Cost_of_Sales)     AS cogs,
                SUM(Gross_Profit)      AS gross,
                SUM(Operating_Income)  AS op
            FROM `{T}` {where}
            GROUP BY node, Year_Month
        """

        # 파트 B: SGA 배분 (노드×월×cls×cat)
        # ff: 노드+부서+월 단위 SGA, sm: FI_SM 비율 원천, sm_tot: 부서×월 합계
        sql_b = f"""
            WITH ff AS (
                SELECT {dimcol} AS node, Department, Year_Month,
                    SUM(SG_and_A_Expenses) AS sga
                FROM `{T}` {where}
                GROUP BY node, Department, Year_Month
            ),
            sm AS (
                SELECT Department, Year_Month,
                    Indirect_Cost_Class AS cls,
                    CASE Main_Category
                        WHEN '광고선전비' THEN 'adv'
                        WHEN '물류비'     THEN 'log'
                        WHEN '수수료'     THEN 'fee'
                        WHEN '인건비'     THEN 'hr'
                        ELSE 'etc'
                    END AS cat,
                    SUM(Amount) AS amt
                FROM `{SM}`
                GROUP BY Department, Year_Month, Indirect_Cost_Class, Main_Category
            ),
            sm_tot AS (
                SELECT Department, Year_Month, SUM(Amount) AS tot
                FROM `{SM}`
                GROUP BY Department, Year_Month
            )
            SELECT ff.node, ff.Year_Month, sm.cls, sm.cat,
                SUM(CAST(ff.sga AS FLOAT64) * sm.amt / NULLIF(sm_tot.tot, 0)) AS val
            FROM ff
            JOIN sm     ON ff.Department = sm.Department     AND ff.Year_Month = sm.Year_Month
            JOIN sm_tot ON ff.Department = sm_tot.Department AND ff.Year_Month = sm_tot.Year_Month
            GROUP BY ff.node, ff.Year_Month, sm.cls, sm.cat
        """

    # 두 쿼리를 병렬 실행
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(run_query_cached, sql_a, params)
        fut_b = ex.submit(run_query_cached, sql_b, params)
        rows_a = fut_a.result()
        rows_b = fut_b.result()

    # cls 매핑: FI_SM의 Indirect_Cost_Class 값 → JSON 키 prefix
    _cls_map = {'직접': 'sgaD', '조직간접': 'sgaO', 'SSG간접': 'sgaC'}
    _cat_keys = ['adv', 'log', 'fee', 'hr', 'etc']

    # 월 목록 수집 (오름차순)
    months_set = set()
    for r in rows_a:
        if r['Year_Month']:
            months_set.add(str(r['Year_Month']))
    for r in rows_b:
        if r['Year_Month']:
            months_set.add(str(r['Year_Month']))
    months = sorted(months_set)
    month_idx = {m: i for i, m in enumerate(months)}
    n = len(months)

    # 노드별 데이터 초기화
    nodes = {}

    def _node(name):
        if name not in nodes:
            nd = {
                'name': name,
                'sales': [0] * n, 'cogs': [0] * n,
                'gross': [0] * n, 'op':   [0] * n,
            }
            for prefix in ('sgaD', 'sgaO', 'sgaC'):
                nd[prefix] = [0.0] * n
                for cat in _cat_keys:
                    nd[f'{prefix}_{cat}'] = [0.0] * n
            nodes[name] = nd
        return nodes[name]

    # 파트 A 병합
    for r in rows_a:
        nm = str(r['node']) if r['node'] is not None else _null_label
        ym = str(r['Year_Month']) if r['Year_Month'] else None
        if ym not in month_idx:
            continue
        idx = month_idx[ym]
        nd = _node(nm)
        nd['sales'][idx] += (r['sales'] or 0)
        nd['cogs'][idx]  += (r['cogs']  or 0)
        nd['gross'][idx] += (r['gross'] or 0)
        nd['op'][idx]    += (r['op']    or 0)

    # 파트 B 병합
    for r in rows_b:
        nm = str(r['node']) if r['node'] is not None else _null_label
        ym = str(r['Year_Month']) if r['Year_Month'] else None
        if ym not in month_idx:
            continue
        idx = month_idx[ym]
        prefix = _cls_map.get(str(r['cls'] or ''), None)
        cat = str(r['cat'] or 'etc')
        if cat not in _cat_keys:
            cat = 'etc'
        val = float(r['val'] or 0)
        if prefix is None:
            continue
        nd = _node(nm)
        nd[f'{prefix}_{cat}'][idx] += val

    # cls 합계 (sgaD = sgaD_adv + sgaD_log + ...) 계산
    for nd in nodes.values():
        for prefix in ('sgaD', 'sgaO', 'sgaC'):
            for i in range(n):
                nd[prefix][i] = sum(nd[f'{prefix}_{cat}'][i] for cat in _cat_keys)

    # 노드 정렬: sales 총합 내림차순
    sorted_nodes = sorted(nodes.values(), key=lambda nd: sum(nd['sales']), reverse=True)

    # 정수 반올림
    def _int_arr(arr):
        return [int(round(v)) for v in arr]

    result_nodes = []
    for nd in sorted_nodes:
        out = {
            'name':  nd['name'],
            'sales': _int_arr(nd['sales']),
            'cogs':  _int_arr(nd['cogs']),
            'gross': _int_arr(nd['gross']),
            'op':    _int_arr(nd['op']),
        }
        for prefix in ('sgaD', 'sgaO', 'sgaC'):
            out[prefix] = _int_arr(nd[prefix])
            for cat in _cat_keys:
                out[f'{prefix}_{cat}'] = _int_arr(nd[f'{prefix}_{cat}'])
        result_nodes.append(out)

    return jsonify({'months': months, 'nodes': result_nodes})


@app.route('/api/pl-pivot')
@login_required
def api_pl_pivot():
    dims = [dim.strip() for dim in request.args.getlist('dims')]
    if not 1 <= len(dims) <= 4 or any(dim not in _PL_PIVOT_ALLOWED_DIM for dim in dims):
        return jsonify({'error': f'invalid dims. allowed: {sorted(_PL_PIVOT_ALLOWED_DIM)}'}), 400

    where, params = build_bq_filters(request.args)
    T = config.BQ_TABLE
    SM = _fi_sm_table()
    dimcols = [f'`{dim}`' if dim in _PL_BQ_RESERVED else dim for dim in dims]
    dim_sql = ', '.join(dimcols)
    ff_cols = dimcols + ([] if 'Department' in dims else ['Department'])
    ff_sql = ', '.join(ff_cols)
    ff_dim_sql = ', '.join(f'ff.{col}' for col in dimcols)

    sql_a = f"""
        SELECT {dim_sql}, Year_Month,
            SUM(Sales_Amount) AS sales,
            SUM(Cost_of_Sales) AS cogs,
            SUM(Gross_Profit) AS gross
        FROM `{T}` {where}
        GROUP BY {dim_sql}, Year_Month
    """
    sql_b = f"""
        WITH ff AS (
            SELECT {ff_sql}, Year_Month,
                SUM(SG_and_A_Expenses) AS sga
            FROM `{T}` {where}
            GROUP BY {ff_sql}, Year_Month
        ),
        sm AS (
            SELECT Department, Year_Month,
                Indirect_Cost_Class AS cls,
                SUM(Amount) AS amt
            FROM `{SM}`
            GROUP BY Department, Year_Month, Indirect_Cost_Class
        ),
        sm_tot AS (
            SELECT Department, Year_Month, SUM(Amount) AS tot
            FROM `{SM}`
            GROUP BY Department, Year_Month
        )
        SELECT {ff_dim_sql}, ff.Year_Month, sm.cls,
            SUM(CAST(ff.sga AS FLOAT64) * sm.amt / NULLIF(sm_tot.tot, 0)) AS val
        FROM ff
        JOIN sm      ON ff.Department = sm.Department      AND ff.Year_Month = sm.Year_Month
        JOIN sm_tot  ON ff.Department = sm_tot.Department  AND ff.Year_Month = sm_tot.Year_Month
        GROUP BY {ff_dim_sql}, ff.Year_Month, sm.cls
    """

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(run_query_cached, sql_a, params)
        fut_b = ex.submit(run_query_cached, sql_b, params)
        rows_a = fut_a.result()
        rows_b = fut_b.result()

    def _dim_values(row):
        return tuple(
            str(row[dim]) if row[dim] is not None else ('조정' if dim in ('Line', 'Category') else '(없음)')
            for dim in dims
        )

    merged = {}

    def _row(key):
        if key not in merged:
            merged[key] = {
                'd': list(key[0]), 'ym': key[1],
                'sales': 0, 'cogs': 0, 'gross': 0,
                'sgaD': 0.0, 'sgaO': 0.0, 'sgaC': 0.0,
            }
        return merged[key]

    months = set()
    for source in (rows_a, rows_b):
        for row in source:
            if row['Year_Month']:
                months.add(str(row['Year_Month']))

    for row in rows_a:
        ym = str(row['Year_Month']) if row['Year_Month'] else None
        if ym is None:
            continue
        out = _row((_dim_values(row), ym))
        out['sales'] += row['sales'] or 0
        out['cogs'] += row['cogs'] or 0
        out['gross'] += row['gross'] or 0

    cls_map = {'직접': 'sgaD', '조직간접': 'sgaO', 'SSG간접': 'sgaC'}
    for row in rows_b:
        ym = str(row['Year_Month']) if row['Year_Month'] else None
        prefix = cls_map.get(str(row['cls'] or ''))
        if ym is None or prefix is None:
            continue
        _row((_dim_values(row), ym))[prefix] += float(row['val'] or 0)

    result_rows = []
    for row in merged.values():
        row['sales'] = int(round(row['sales']))
        row['cogs'] = int(round(row['cogs']))
        row['gross'] = int(round(row['gross']))
        for prefix in ('sgaD', 'sgaO', 'sgaC'):
            row[prefix] = round(row[prefix], 2)
        result_rows.append(row)

    return jsonify({'months': sorted(months), 'dims': dims, 'rows': result_rows})


@app.route('/api/pl-source-export')
@login_required
def api_pl_source_export():
    import csv, io as _io
    item      = request.args.get('item', '').strip()
    dim       = request.args.get('dim', '').strip()
    dim_val   = request.args.get('dim_val', '').strip()
    months    = [m for m in request.args.getlist('months') if m]
    sec       = request.args.get('sec', 'all').strip()
    depts_raw = request.args.get('depts', '').strip()

    if not months or not item:
        return jsonify({'error': 'months and item are required'}), 400

    T  = config.BQ_TABLE
    SM = _fi_sm_table()

    # Month placeholders
    m_params = [bigquery.ScalarQueryParameter(f'm{i}', 'STRING', m) for i, m in enumerate(months)]
    m_list   = ', '.join(f'@m{i}' for i in range(len(months)))

    # Brand filter
    sec_lower = sec.lower()
    if sec_lower == 'sk' or sec == 'SK':
        brand_cond = "AND Brand = 'SK'"
    elif sec_lower in ('dist', 'um') or sec == 'UM':
        brand_cond = "AND Brand = 'UM'"
    else:
        brand_cond = ''

    # Dim value filter (parameterized)
    dim_cond  = ''
    dim_param = []
    if dim_val and not dim_val.startswith('__') and dim in _PL_ALLOWED_DIM:
        safe_col = f'`{dim}`' if dim in _PL_BQ_RESERVED else dim
        dim_cond  = f'AND {safe_col} = @dim_val'
        dim_param = [bigquery.ScalarQueryParameter('dim_val', 'STRING', dim_val)]

    # Depts filter (org mode: list of departments)
    depts_cond   = ''
    depts_params = []
    if depts_raw and not dim_cond:
        depts = [d.strip() for d in depts_raw.split(',') if d.strip()]
        if depts:
            ph = ', '.join(f'@dp{i}' for i in range(len(depts)))
            depts_cond   = f'AND Department IN ({ph})'
            depts_params = [bigquery.ScalarQueryParameter(f'dp{i}', 'STRING', d) for i, d in enumerate(depts)]

    is_sga = item.startswith('sga')

    if is_sga:
        parts  = item.split('.')
        prefix = parts[0]
        sub    = parts[1] if len(parts) > 1 else None

        cls_map = {'sgaD': '직접', 'sgaO': '조직간접', 'sgaC': 'SSG간접'}
        cat_map = {'adv': '광고선전비', 'log': '물류비', 'fee': '수수료', 'hr': '인건비'}

        cls_extra, cls_cond = [], ''
        if prefix in cls_map:
            cls_extra = [bigquery.ScalarQueryParameter('cls_val', 'STRING', cls_map[prefix])]
            cls_cond  = 'AND Indirect_Cost_Class = @cls_val'

        cat_extra, cat_cond = [], ''
        if sub and sub != 'etc' and sub in cat_map:
            cat_extra = [bigquery.ScalarQueryParameter('cat_val', 'STRING', cat_map[sub])]
            cat_cond  = 'AND Main_Category = @cat_val'
        elif sub == 'etc':
            excl_vals = list(cat_map.values())
            ph_ex     = ', '.join(f'@ex{i}' for i in range(len(excl_vals)))
            cat_extra = [bigquery.ScalarQueryParameter(f'ex{i}', 'STRING', v) for i, v in enumerate(excl_vals)]
            cat_cond  = f'AND Main_Category NOT IN ({ph_ex})'

        # FI_SM: only Department dim is meaningful
        if dim == 'Department' and dim_cond:
            sm_dim_cond, sm_dim_params = dim_cond, dim_param
        elif depts_cond:
            sm_dim_cond, sm_dim_params = depts_cond, depts_params
        else:
            sm_dim_cond, sm_dim_params = '', []

        sql    = f"SELECT * FROM `{SM}` WHERE Year_Month IN ({m_list}) {cls_cond} {cat_cond} {sm_dim_cond} ORDER BY Year_Month, Department, Cost_Account"
        params = m_params + cls_extra + cat_extra + sm_dim_params
        table_name = 'FI_SM'
    else:
        sql    = f"SELECT * FROM `{T}` WHERE Year_Month IN ({m_list}) {brand_cond} {dim_cond} {depts_cond} ORDER BY Year_Month, Department, Customer, Product_Code"
        params = m_params + dim_param + depts_params
        table_name = 'FI_Final'

    try:
        rows = run_query(sql, params)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if not rows:
        resp = make_response('﻿Year_Month,결과\n,데이터없음\n')
        resp.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        resp.headers['Content-Disposition'] = 'attachment; filename="no_data.csv"'
        return resp

    output = _io.StringIO()
    cols   = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=cols)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ('' if v is None else v) for k, v in row.items()})

    safe_item = 'raw' if item in ('__all__', '') else item.replace('.', '_')
    safe_dim  = dim_val if (dim_val and not dim_val.startswith('__')) else (depts_raw.split(',')[0].strip() if depts_raw else 'all')
    m_label   = months[0] if len(months) == 1 else f"{months[0]}_{months[-1]}"
    filename  = f'{table_name}_{safe_item}_{safe_dim}_{m_label}.csv'

    resp = make_response('﻿' + output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
