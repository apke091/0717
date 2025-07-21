import sqlite3
import psycopg2
import os
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()

# SQLite 連線
sqlite_conn = sqlite3.connect("user.db")
sqlite_cursor = sqlite_conn.cursor()

# PostgreSQL 連線
pg_conn = psycopg2.connect(
    os.environ["DATABASE_URL"],
    cursor_factory=RealDictCursor
)
pg_cursor = pg_conn.cursor()

# 搬 users 資料
sqlite_cursor.execute("SELECT username, password, role FROM users")
for row in sqlite_cursor.fetchall():
    pg_cursor.execute("""
        INSERT INTO users (username, password, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, (row[0], row[1], row[2]))

# 搬 products 資料
sqlite_cursor.execute("SELECT pid, name, price FROM products")
for row in sqlite_cursor.fetchall():
    pg_cursor.execute("""
        INSERT INTO products (pid, name, price)
        VALUES (%s, %s, %s)
        ON CONFLICT (pid) DO NOTHING
    """, (row[0], row[1], row[2]))

# 儲存並關閉
pg_conn.commit()
sqlite_conn.close()
pg_conn.close()

print("✅ SQLite → PostgreSQL 資料已匯入完畢")
