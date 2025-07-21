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

    conn.commit()
    conn.close()
    print("✅ 資料表已建立")


if __name__ == "__main__":
    init_db()
