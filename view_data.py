import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
cur = conn.cursor()

cur.execute("SELECT * FROM users")
users = cur.fetchall()
print("🔍 Users:")
for user in users:
    print(user)

cur.execute("SELECT * FROM products")
products = cur.fetchall()
print("\n🛍️ Products:")
for p in products:
    print(p)

cur.execute("SELECT * FROM cart_items")
cart_items = cur.fetchall()
print("\n🧺 Cart Items:")
for item in cart_items:
    print(item)

cur.execute("SELECT * FROM rent_requests ORDER BY submitted_at DESC")
rents = cur.fetchall()

print("\n📅 租借申請紀錄：")
for r in rents:
    print(f"地點: {r['location']} | 日期: {r['date']} | 時段: {r['time_slot']}")
    print(f"申請人: {r['name']} | 電話: {r['phone']} | 備註: {r['note'] or '無'}")
    print(f"送出時間: {r['submitted_at']}")
    print("-" * 40)

conn.close()
