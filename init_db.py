import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import traceback

load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )

def init_db():
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # ========== users ==========
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'member'
        );
        """)

        # ========== products ==========
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            pid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        );
        """)

        # ========== rent_requests ==========
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
        # 這兩行是保險，已存在就不會新增
        cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS email TEXT;")
        cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';")
        # >>> 新增：自由起訖時間欄位（若不存在就加）
        cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS start_time TIME;")
        cur.execute("ALTER TABLE rent_requests ADD COLUMN IF NOT EXISTS end_time   TIME;")

        # >>> 新增：把舊的 time_slot（09:00-12:00 / 09:00–12:00）回填到新欄位
        cur.execute("""
            UPDATE rent_requests
            SET start_time = split_part(replace(time_slot,'–','-'), '-', 1)::time,
                end_time   = split_part(replace(time_slot,'–','-'), '-', 2)::time
            WHERE time_slot IS NOT NULL
              AND (start_time IS NULL OR end_time IS NULL);
        """)

        # >>> 建索引：之後查詢撞時段會更快
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rent_loc_date ON rent_requests(location, date);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_rent_loc_date_time ON rent_requests(location, date, start_time, end_time);")

        # ========== cart_items ==========
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

        # ========== about_page ==========
        cur.execute("""
        CREATE TABLE IF NOT EXISTS about_page (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL DEFAULT ''
        );
        """)
        # 初始 about_page（若沒有任何資料）
        cur.execute("SELECT COUNT(*) AS count FROM about_page;")
        if (cur.fetchone()["count"] or 0) == 0:
            cur.execute("""
                INSERT INTO about_page (content) VALUES (%s)
            """, ("""
                <h1>關於精油工會</h1>
                <p>我們致力於推廣芳香療法、精油教育與應用，連結產業與社會，創造健康永續生活。</p>
                <ul><li>（這是初始內容，之後可在後台編輯頁修改）</li></ul>
            """,))

        # ========== downloads ==========
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

        # ========== contact_messages ==========
        cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_messages (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # ========== news ==========
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
        # 自動更新 news.updated_at（僅在不存在觸發器時建立）
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_news_updated_at') THEN
                CREATE OR REPLACE FUNCTION set_news_updated_at() RETURNS trigger AS $f$
                BEGIN
                    NEW.updated_at := NOW();
                    RETURN NEW;
                END;
                $f$ LANGUAGE plpgsql;

                CREATE TRIGGER trg_news_updated_at
                BEFORE UPDATE ON news
                FOR EACH ROW
                EXECUTE FUNCTION set_news_updated_at();
            END IF;
        END$$;
        """)

        # ========== courses（課程專區，若你保留 /courses）==========
        cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            dm_file TEXT,
            signup_link TEXT,
            pinned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_courses_created_at ON courses(created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_courses_pinned ON courses(pinned);")

        # ========== 課程回顧（唯一、乾淨版）==========
        # 分類表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS review_categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            sort_order INTEGER DEFAULT 0
        );
        """)
        # 主文表
        cur.execute("""
        CREATE TABLE IF NOT EXISTS course_reviews (
            id SERIAL PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES review_categories(id) ON DELETE RESTRICT,
            title TEXT NOT NULL,
            event_date DATE,
            cover_path TEXT,
            summary TEXT,
            content_html TEXT,
            status TEXT DEFAULT 'published',   -- published | draft
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # 媒體表（沿用你現有的 size_bytes）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS review_media (
            id SERIAL PRIMARY KEY,
            review_id INTEGER NOT NULL REFERENCES course_reviews(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,              -- uploads/reviews/<review_id>/<uuid>.<ext>
            file_name TEXT,                       -- 原始檔名
            mime TEXT NOT NULL,                   -- image/jpeg / video/mp4 ...
            size_bytes BIGINT,                    -- 檔案大小
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # 補齊新欄位（若已存在就略過）
        cur.execute("ALTER TABLE review_media ADD COLUMN IF NOT EXISTS width INT;")
        cur.execute("ALTER TABLE review_media ADD COLUMN IF NOT EXISTS height INT;")
        cur.execute("ALTER TABLE review_media ADD COLUMN IF NOT EXISTS file_path_480 TEXT;")
        cur.execute("ALTER TABLE review_media ADD COLUMN IF NOT EXISTS file_path_960 TEXT;")
        cur.execute("ALTER TABLE review_media ADD COLUMN IF NOT EXISTS file_path_webp TEXT;")

        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_review_media_review ON review_media(review_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_review_media_sort ON review_media(review_id, sort_order, created_at, id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_course_reviews_category ON course_reviews(category_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_course_reviews_status ON course_reviews(status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_course_reviews_date ON course_reviews((COALESCE(event_date, created_at)));")

        # --- 先把 sort_order 去重，避免等下 UNIQUE INDEX 建不成功 ---
        cur.execute("""
        WITH ranked AS (
          SELECT id,
                 review_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY review_id
                   ORDER BY COALESCE(sort_order, 0), created_at, id
                 ) - 1 AS rn
          FROM review_media
        ),
        upd AS (
          UPDATE review_media m
          SET sort_order = r.rn
          FROM ranked r
          WHERE m.id = r.id AND COALESCE(m.sort_order, -1) <> r.rn
          RETURNING 1
        )
        SELECT COUNT(*) FROM upd;
        """)

        # 建立唯一索引（不再用 DO $$ 包）
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_review_media_order ON review_media(review_id, sort_order);")

        # 舊表相容：如有 review_photos 且 review_media 為空，搬一次
        cur.execute("""
        DO $$
        BEGIN
          IF to_regclass('public.review_photos') IS NOT NULL THEN
            IF NOT EXISTS (SELECT 1 FROM review_media) THEN
              INSERT INTO review_media (review_id, file_path, file_name, mime, sort_order, created_at)
              SELECT review_id,
                     image_path,
                     caption,
                     'image/*'::text,
                     COALESCE(sort_order, 0),
                     NOW()
              FROM review_photos;
            END IF;
          END IF;
        END$$;
        """)

        # 預設塞一個分類（若沒有任何分類）
        cur.execute("SELECT COUNT(*) AS ximen FROM review_categories;")
        if (cur.fetchone()["ximen"] or 0) == 0:
            cur.execute(
                "INSERT INTO review_categories (name, slug, sort_order) VALUES (%s,%s,%s);",
                ("一般課程", "general", 0)
            )

        conn.commit()
        print("✅ 資料表已建立／更新完成（含課程回顧三表）")

    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        try:
            print("\n[PG ERROR]", getattr(e, "pgerror", ""))
            print(getattr(e, "diag", ""))
        except:
            pass
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
