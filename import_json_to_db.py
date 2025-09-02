# # import_json_to_db.py
# import sqlite3
# import json
#
# conn = sqlite3.connect("user.db")
# cursor = conn.cursor()
#
# # 🔹 匯入 users.json
# with open("users.json", "r", encoding="utf-8") as f:
#     users = json.load(f)
#
# for username, user_data in users.items():
#     cursor.execute(
#         "INSERT OR REPLACE INTO users (username, password, role) VALUES (?, ?, ?)",
#         (username, user_data["password"], user_data["role"])
#     )
#
# print("✅ 匯入 users.json 完成")
#
# # 🔹 匯入 products.json
# with open("products.json", "r", encoding="utf-8") as f:
#     products = json.load(f)
#
# for pid, p in products.items():
#     cursor.execute("""
#         INSERT OR REPLACE INTO products (pid, name, price)
#         VALUES (?, ?, ?)
#     """, (pid, p["name"], p["price"]))
#
# conn.commit()
# conn.close()
# print("✅ 匯入 products.json 完成")
# make_admin.py







# #帳號升級admin
# import os
# import psycopg2
# from psycopg2.extras import RealDictCursor
# from dotenv import load_dotenv
#
# load_dotenv()  # 讀 .env 的 DATABASE_URL
# username = input("輸入要升級為管理員的帳號： ").strip()
#
# dsn = os.environ["DATABASE_URL"]
# conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
# cur = conn.cursor()
#
# cur.execute("UPDATE users SET role = 'admin' WHERE username = %s", (username,))
# if cur.rowcount == 0:
#     print("找不到這個帳號。")
# else:
#     conn.commit()
#     print(f"✅ {username} 已是 admin")
#
# conn.close()
#
