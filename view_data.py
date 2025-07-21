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

conn.close()
