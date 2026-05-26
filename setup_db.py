#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MariaDB dashboard_users table setup script
"""
import pymysql
from config import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

def setup_database():
    """Create dashboard_users table in MariaDB"""
    try:
        # Connect to MariaDB
        print(f"[*] Connecting to MariaDB... {DB_HOST}:{DB_PORT}")
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset='utf8mb4'
        )

        cursor = conn.cursor()
        print("[OK] MariaDB connection successful")

        # Create table SQL
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS dashboard_users (
          id           INT AUTO_INCREMENT PRIMARY KEY,
          username     VARCHAR(100) NOT NULL UNIQUE COMMENT 'AD sAMAccountName (lowercase)',
          display_name VARCHAR(200) DEFAULT '',
          role         ENUM('admin','viewer') DEFAULT 'viewer',
          is_active    TINYINT(1) DEFAULT 1,
          created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        print("\n[*] Executing CREATE TABLE...")
        print("=" * 60)
        cursor.execute(create_table_sql)
        conn.commit()
        print("[OK] CREATE TABLE completed")

        # Verify table structure
        print("\n[*] Verifying table structure (DESCRIBE)...")
        print("=" * 60)
        cursor.execute("DESCRIBE dashboard_users;")
        columns = cursor.fetchall()

        print(f"{'Field':<15} {'Type':<30} {'Null':<5} {'Key':<5} {'Default':<15} {'Extra':<20}")
        print("-" * 95)
        for col in columns:
            field, col_type, null, key, default, extra = col
            print(f"{field:<15} {col_type:<30} {null:<5} {key:<5} {str(default):<15} {extra:<20}")

        # Verify table data
        print("\n[*] Verifying table data (SELECT)...")
        print("=" * 60)
        cursor.execute("SELECT * FROM dashboard_users;")
        rows = cursor.fetchall()

        if not rows:
            print("[OK] Table is empty (as expected)")
        else:
            print(f"[*] Data found: {rows}")

        # Get table information
        print("\n[*] Table information from INFORMATION_SCHEMA...")
        print("=" * 60)
        cursor.execute("""
            SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION, TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'dashboard_users'
        """, (DB_NAME,))
        table_info = cursor.fetchone()
        if table_info:
            print(f"Table Name: {table_info[0]}")
            print(f"Type: {table_info[1]}")
            print(f"Engine: {table_info[2]}")
            print(f"Collation: {table_info[3]}")
            print(f"Row Count: {table_info[4]}")

        cursor.close()
        conn.close()
        print("\n[OK] Setup completed successfully!")
        return True

    except pymysql.Error as e:
        print(f"[ERROR] MariaDB error: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

if __name__ == "__main__":
    success = setup_database()
    exit(0 if success else 1)
