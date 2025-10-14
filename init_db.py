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
    # 確保欄位存在
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
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        mime TEXT,
        size_bigint BIGINT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # contact_messages
    cur.execute("""
    CREATE TABLE IF NOT EXISTS contact_messages (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # ✅ news（最新消息）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS news (
        id BIGSERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT,
        link TEXT,
        publish_date DATE NOT NULL DEFAULT CURRENT_DATE,
        is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
        is_visible BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 自動更新 updated_at
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'trg_news_updated_at'
        ) THEN
            CREATE OR REPLACE FUNCTION set_news_updated_at() RETURNS trigger AS $$
            BEGIN
                NEW.updated_at := NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_news_updated_at
            BEFORE UPDATE ON news
            FOR EACH ROW
            EXECUTE FUNCTION set_news_updated_at();
        END IF;
    END$$;
    """)

    conn.commit()
    conn.close()
    print("✅ 資料表已建立／更新完成")

if __name__ == "__main__":
    init_db()
