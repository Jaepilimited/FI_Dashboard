"""
최초 관리자 계정 생성 스크립트
실행: python create_admin.py
"""
import pymysql
import config

def main():
    username = 'jeffrey'
    display_name = 'Jeffrey'
    role = 'admin'

    db = pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASS,
        database=config.DB_NAME, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with db.cursor() as cur:
            # 이미 있으면 role과 is_active만 업데이트
            cur.execute(
                """INSERT INTO dashboard_users (username, display_name, role, is_active)
                   VALUES (%s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE
                     display_name=VALUES(display_name),
                     role=VALUES(role),
                     is_active=1""",
                (username, display_name, role)
            )
        db.commit()
        print(f"[OK] admin created: {username} (role=admin)")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
