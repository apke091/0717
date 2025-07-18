import sqlite3

DB_NAME = "user.db"  # 🟢 用同一個資料庫！

def init_users_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def init_products_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            pid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def insert_default_admin():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    existing = cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",)).fetchone()
    if not existing:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       ("admin", "123456", "admin"))
        print("✅ 已新增預設管理員帳號：admin / 123456")
    else:
        print("🔹 admin 帳號已存在，略過")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_users_table()
    init_products_table()
    insert_default_admin()
    print("✅ 資料庫初始化完成（users + products）")
