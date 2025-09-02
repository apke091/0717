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
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'member'
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        pid TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL
    );
    """)

    cursor.execute("""
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

    # 確保 email 欄位存在（避免 insert 出錯）
    cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='rent_requests' AND column_name='email'
                ) THEN
                    ALTER TABLE rent_requests ADD COLUMN email TEXT;
                END IF;
            END
            $$;
        """)
    # cursor.execute("ALTER TABLE rent_requests ADD COLUMN status TEXT DEFAULT 'pending';")

    cursor.execute("""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS about_page (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL
        );
    """)

    # 確保至少有一筆初始資料
    cursor.execute("SELECT COUNT(*) FROM about_page;")
    count = cursor.fetchone()["count"]
    if count == 0:
        cursor.execute("INSERT INTO about_page (content) VALUES (%s)", (
            '''
            <h1>關於精油工會</h1>
            <p>我們致力於推廣芳香療法、精油教育與應用，連結產業與社會，創造健康永續生活。</p>
            <ul><li>初始資料...</li></ul>
            ''',
        ))
    cursor.execute("""
            CREATE TABLE downloads (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL,        -- 實際檔名
            title TEXT NOT NULL,           -- 管理員輸入的標題
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)


    conn.commit()
    conn.close()
    print("✅ 資料表已建立")


if __name__ == "__main__":
    init_db()
