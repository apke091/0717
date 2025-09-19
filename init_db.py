import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'member'
    );
    """)

    # products
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        pid TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL
    );
    """)

    # rent_requests
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rent_requests (
        id SERIAL PRIMARY KEY,
        location TEXT NOT NULL,
        date DATE NOT NULL,
        time_slot TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        note TEXT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending'
    );
    """)
    # 確保欄位存在（即使上面已建過也不會報錯）
    cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS email TEXT;")
    cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';")

    # cart_items
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cart_items (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        UNIQUE (user_id, product_id),
        FOREIGN KEY (user_id) REFERENCES users(username),
        FOREIGN KEY (product_id) REFERENCES products(pid)
    );
    """)

    # about_page
    cur.execute("""
    CREATE TABLE IF NOT EXISTS about_page (
        id SERIAL PRIMARY KEY,
        content TEXT NOT NULL DEFAULT ''
    );
    """)

    # 初始化 about_page（若沒有任何資料）
    cur.execute("SELECT COUNT(*) AS count FROM about_page;")
    count = cur.fetchone()["count"]
    if count == 0:
        cur.execute("""
            INSERT INTO about_page (content) VALUES (%s)
        """, ("""
            <h1>關於精油工會</h1>
            <p>我們致力於推廣芳香療法、精油教育與應用，連結產業與社會，創造健康永續生活。</p>
            <ul><li>（這是初始內容，之後可在後台編輯頁修改）</li></ul>
        """,))

    # downloads
    cur.execute("""
    CREATE TABLE IF NOT EXISTS downloads (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,          -- 實際存到磁碟上的檔名（避免碰撞）
        original_name TEXT NOT NULL,     -- 使用者上傳的原始檔名（列表顯示用）
        mime TEXT,
        size_bigint BIGINT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # ✅ contact_messages：聯絡我們留言
    cur.execute("""
    CREATE TABLE IF NOT EXISTS contact_messages (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()
    print("✅ 資料表已建立／更新完成")

if __name__ == "__main__":
    init_db()
