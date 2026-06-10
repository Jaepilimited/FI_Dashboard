import secrets
import functools
from datetime import datetime, timedelta
import pymysql
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from google.cloud import bigquery
from google.oauth2 import service_account
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

REMEMBER_COOKIE = 'fi_remember'
REMEMBER_DAYS = 30


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
    return render_template('dashboard.html', user=session['user'])


@app.route('/report')
@login_required
def report():
    return render_template('report.html', user=session['user'])


# ─── BigQuery 필터 빌더 ────────────────────────────────────────────
def build_bq_filters(args):
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

    sales_type = args.get('sales_type', '').strip()
    if sales_type:
        conditions.append('Sales_Type = @sales_type')
        params.append(bigquery.ScalarQueryParameter('sales_type', 'STRING', sales_type))

    line = args.get('line', '').strip()
    if line:
        conditions.append('Line = @line')
        params.append(bigquery.ScalarQueryParameter('line', 'STRING', line))

    category = args.get('category', '').strip()
    if category:
        conditions.append('Category = @category')
        params.append(bigquery.ScalarQueryParameter('category', 'STRING', category))

    country = args.get('country', '').strip()
    if country:
        conditions.append('Country = @country')
        params.append(bigquery.ScalarQueryParameter('country', 'STRING', country))

    continent = args.get('continent', '').strip()
    if continent:
        conditions.append('Continent = @continent')
        params.append(bigquery.ScalarQueryParameter('continent', 'STRING', continent))

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    return where, params


def run_query(sql, params=None):
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    rows = client.query(sql, job_config=job_config).result()
    return [dict(row) for row in rows]


# ─── API 엔드포인트 ────────────────────────────────────────────────
@app.route('/api/filters')
@login_required
def api_filters():
    sql  = f"SELECT DISTINCT Department FROM `{config.BQ_TABLE}` WHERE Department IS NOT NULL ORDER BY Department"
    sql2 = f"SELECT DISTINCT Customer  FROM `{config.BQ_TABLE}` WHERE Customer IS NOT NULL ORDER BY Customer"
    sql3 = f"SELECT DISTINCT Year_Month FROM `{config.BQ_TABLE}` ORDER BY Year_Month"
    sql4 = f"SELECT DISTINCT Sales_Type FROM `{config.BQ_TABLE}` WHERE Sales_Type IS NOT NULL ORDER BY Sales_Type"
    sql5 = f"SELECT DISTINCT Line FROM `{config.BQ_TABLE}` WHERE Line IS NOT NULL ORDER BY Line"
    sql6 = f"SELECT DISTINCT Category FROM `{config.BQ_TABLE}` WHERE Category IS NOT NULL ORDER BY Category"
    sql7 = f"SELECT DISTINCT Country FROM `{config.BQ_TABLE}` WHERE Country IS NOT NULL AND Country != '' ORDER BY Country"

    return jsonify({
        'departments': [r['Department'] for r in run_query(sql)],
        'customers':   [r['Customer']   for r in run_query(sql2)],
        'months':      [r['Year_Month'] for r in run_query(sql3)],
        'sales_types': [r['Sales_Type'] for r in run_query(sql4)],
        'lines':       [r['Line']       for r in run_query(sql5)],
        'categories':  [r['Category']   for r in run_query(sql6)],
        'countries':   [r['Country']    for r in run_query(sql7)],
    })


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
    rows = run_query(sql, params)
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
    rows = run_query(sql, params)
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
    rows = run_query(sql, params)
    return jsonify(rows)


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


@app.route('/api/sales-type')
@login_required
def api_sales_type():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Sales_Type,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SUM(Sales_Quantity)    AS sales_quantity,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Sales_Type ORDER BY sales_amount DESC
    """
    return jsonify(run_query(sql, params))


@app.route('/api/line')
@login_required
def api_line():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Line,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Line ORDER BY sales_amount DESC
    """
    return jsonify(run_query(sql, params))


@app.route('/api/category')
@login_required
def api_category():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Category,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Category ORDER BY sales_amount DESC
    """
    return jsonify(run_query(sql, params))


@app.route('/api/country')
@login_required
def api_country():
    where, params = build_bq_filters(request.args)
    sql = f"""
        SELECT
            Country,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {where}
        GROUP BY Country ORDER BY sales_amount DESC
        LIMIT 30
    """
    return jsonify(run_query(sql, params))


@app.route('/api/continent')
@login_required
def api_continent():
    where, params = build_bq_filters(request.args)
    cont_cond = "Continent IS NOT NULL AND Continent != ''"
    full_where = (where + f' AND {cont_cond}') if where else f'WHERE {cont_cond}'
    sql = f"""
        SELECT
            Continent,
            SUM(Sales_Amount)      AS sales_amount,
            SUM(Gross_Profit)      AS gross_profit,
            SUM(Operating_Income)  AS operating_income,
            SAFE_DIVIDE(SUM(Gross_Profit), SUM(Sales_Amount)) * 100 AS gross_margin,
            SAFE_DIVIDE(SUM(Operating_Income), SUM(Sales_Amount)) * 100 AS operating_margin
        FROM `{config.BQ_TABLE}`
        {full_where}
        GROUP BY Continent ORDER BY sales_amount DESC
    """
    return jsonify(run_query(sql, params))


@app.route('/api/raw')
@login_required
def api_raw():
    export = request.args.get('export', '0') == '1'
    where, params = build_bq_filters(request.args)

    def serialize(raw):
        rows = []
        for row in raw:
            r = {}
            for k, v in row.items():
                r[k] = int(v) if isinstance(v, int) else (float(v) if isinstance(v, float) else (v or ''))
            rows.append(r)
        return rows

    SELECT_COLS = """
        Year_Month, Department, Sales_Type, Line, Category, Country,
        Customer, Product_Name, Product_Code, Specification,
        Sales_Quantity, Sales_Amount, Cost_of_Sales, Gross_Profit,
        SG_and_A_Expenses, Operating_Income
    """

    if export:
        sql = f"SELECT {SELECT_COLS} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT 50000"
        rows = serialize(run_query(sql, params))
        return jsonify({'total': len(rows), 'rows': rows})

    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(10, int(request.args.get('per_page', 100))))
    except ValueError:
        page, per_page = 1, 100
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) AS cnt FROM `{config.BQ_TABLE}` {where}"
    total = (run_query(count_sql, params) or [{'cnt': 0}])[0]['cnt']

    sql = f"SELECT {SELECT_COLS} FROM `{config.BQ_TABLE}` {where} ORDER BY Year_Month DESC, Sales_Amount DESC LIMIT {per_page} OFFSET {offset}"
    rows = serialize(run_query(sql, params))
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


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
