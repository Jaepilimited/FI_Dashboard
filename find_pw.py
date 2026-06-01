import pymysql
from werkzeug.security import check_password_hash

conn = pymysql.connect(host='127.0.0.1', port=3306, user='skin1004', password='skin1004!',
                       database='skin1004_ai', charset='utf8mb4',
                       cursorclass=pymysql.cursors.DictCursor)
with conn.cursor() as c:
    c.execute("SELECT username, password_hash FROM dashboard_users WHERE username='jeffrey'")
    r = c.fetchone()
    h = r['password_hash'] if r else None
    print('hash exists:', bool(h))
    for pw in ['admin1004!', 'Admin1004!', 'jeffrey1004', 'skin1004!', 'admin', '1004', 'jeffrey']:
        if h and check_password_hash(h, pw):
            print(f'✅ password: {pw}')
conn.close()
