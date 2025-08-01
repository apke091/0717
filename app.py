from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

# app = Flask(__name__)
# app.jinja_env.cache = {}  # ✅ 關閉模板快取（開發用）

# 建立 PostgreSQL 資料庫連線

def get_db_connection():
    conn = psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )
    return conn

# 從資料庫載入商品資料

def load_products_from_db():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM products")
    rows = cursor.fetchall()
    conn.close()
    products = {}
    for row in rows:
        products[row["pid"]] = {
            "name": row["name"],
            "price": int(row["price"])
        }
    return products

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# 管理員權限驗證

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            flash("您沒有權限執行此操作")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def delete_expired_rent_requests():
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now()

    cur.execute("""
        DELETE FROM rent_requests
        WHERE status = 'approved'
        AND (
            (date < %s)
            OR (date = %s AND (
                (time_slot = '09:00–12:00' AND %s >= '12:00')
                OR (time_slot = '13:00-16:00' AND %s >= '16:00')
                OR (time_slot = '18:00–21:00' AND %s >= '21:00')
            ))
        )
    """, (now.date(), now.date(), now.strftime('%H:%M'), now.strftime('%H:%M'), now.strftime('%H:%M')))
    conn.commit()
    conn.close()

# @app.route("/test")
# def test():
#     return render_template("test.html", cart_count=999, username="測試")


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/about")
def about():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT content FROM about_page WHERE id = 1")
    result = cur.fetchone()
    conn.close()
    return render_template("about.html", content=result["content"])



@app.route("/edit_about", methods=["GET", "POST"])
@admin_required
def edit_about():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        new_content = request.form["content"]
        cur.execute("UPDATE about_page SET content = %s WHERE id = 1", (new_content,))
        conn.commit()
        conn.close()
        flash("更新成功！")
        return redirect(url_for("about"))

    cur.execute("SELECT content FROM about_page WHERE id = 1")
    content = cur.fetchone()["content"]
    conn.close()
    return render_template("edit_about.html", content=content)

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/download")
def download():
    return render_template("download.html")

@app.route("/news")
def news():
    return render_template("news.html")

@app.route("/rent", methods=["GET", "POST"])
def rent():
    if request.method == "POST":
        location = request.form.get("location")
        date = request.form.get("date")
        time_slot = request.form.get("time_slot")
        name = request.form.get("name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        note = request.form.get("note") or ""

        # 防止選過去日期
        today = datetime.now().date()
        selected_date = datetime.strptime(date, "%Y-%m-%d").date()
        if selected_date < today:
            flash("❌ 不能選擇今天以前的日期")
            return redirect(url_for("rent"))

        # 檢查是否已有相同場地+日期+時段 且已核准的紀錄
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM rent_requests WHERE location=%s AND date=%s AND time_slot=%s AND status='approved'",
            (location, date, time_slot)
        )
        existing = cur.fetchone()
        if existing:
            conn.close()
            flash("❌ 此時段已被預約")
            return redirect(url_for("rent"))

        # 寫入資料庫（包含 email 欄位）
        cur.execute(
            "INSERT INTO rent_requests (location, date, time_slot, name, phone, email, note, status, submitted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            (location, date, time_slot, name, phone, email, note, 'pending')
        )
        conn.commit()
        conn.close()

        flash("✅ 已送出申請，請等待審核")
        return redirect(url_for("rent"))

    # 傳入今天的日期限制 HTML 選項
    return render_template("rent.html", now=datetime.now())

@app.route("/manage_rents", methods=["GET", "POST"])
@admin_required
def manage_rents():
    delete_expired_rent_requests()  # 一進來就清除過期資料

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == "POST":
        rent_id = request.form["id"]
        action = request.form["action"]
        if action == "approve":
            cur.execute("UPDATE rent_requests SET status='approved' WHERE id=%s", (rent_id,))
        elif action == "reject":
            cur.execute("DELETE FROM rent_requests WHERE id=%s", (rent_id,))
        conn.commit()

    cur.execute("SELECT * FROM rent_requests ORDER BY submitted_at DESC")
    rents = cur.fetchall()
    conn.close()
    return render_template("manage_rents.html", rents=rents)

@app.route("/shop")
def shop():
    products = load_products_from_db()
    return render_template("shop.html", products=products)

@app.route("/add_to_cart/<pid>")
def add_to_cart(pid):
    if "username" not in session:
        flash("請先登入才能加入購物車")
        return redirect(url_for("login"))

    user_id = session["username"]  # 登入帳號當作 user_id
    products = load_products_from_db()

    if pid not in products:
        flash("商品不存在")
        return redirect(url_for("shop"))
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 嘗試插入商品，如果已存在就加一筆數量
        cursor.execute("""
            INSERT INTO cart_items (user_id, product_id, quantity)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, product_id)
            DO UPDATE SET quantity = cart_items.quantity + 1
        """, (user_id, pid))

        conn.commit()
        flash("✅ 已加入購物車")

    except Exception as e:
        print("加入購物車錯誤：", e)
        flash("❌ 加入購物車失敗，請稍後再試")

    finally:
        conn.close()

    return redirect(url_for("shop"))

@app.route("/cart")
def cart():
    if "username" not in session:
        flash("請先登入才能查看購物車")
        return redirect(url_for("login"))

    user_id = session["username"]

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 查詢使用者的購物車，連結產品名稱與價格
    cursor.execute("""
        SELECT 
            p.pid,
            p.name,
            p.price,
            c.quantity,
            (p.price * c.quantity) AS subtotal
        FROM cart_items c
        JOIN products p ON c.product_id = p.pid
        WHERE c.user_id = %s
    """, (user_id,))

    items = cursor.fetchall()
    total = sum(item["subtotal"] for item in items)

    conn.close()

    return render_template("cart.html", items=items, total=total)

@app.route("/remove_from_cart/<pid>")
def remove_from_cart(pid):
    if "username" not in session:
        flash("請先登入")
        return redirect(url_for("login"))

    user_id = session["username"]
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s AND product_id = %s", (user_id, pid))
        conn.commit()
        flash("🗑️ 已從購物車移除")
    except Exception as e:
        print("刪除購物車項目錯誤：", e)
        flash("❌ 無法移除，請稍後再試")
    finally:
        conn.close()

    return redirect(url_for("cart"))

@app.context_processor
def inject_cart_count():
    if "username" not in session:
        print("❌ 沒登入，不查詢購物車")
        return {"cart_count": 0}

    try:
        user_id = session["username"]
        print("✅ 正在查詢購物車數量，user_id =", user_id)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(quantity) AS sum FROM cart_items WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        conn.close()

        # print("🎯 查詢結果：", result)

        count = result.get("sum", 0) if result else 0
    except Exception as e:
        print("⚠️ 購物車查詢錯誤：", e)
        count = 0

    print("✅ 最終 cart_count =", count)
    return {"cart_count": count}

@app.route("/manage_products", methods=["GET", "POST"])
@admin_required
def manage_products():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == "POST":
        pid = request.form.get("pid")
        name = request.form.get("name")
        price = request.form.get("price")
        if not pid or not name or not price:
            flash("請填寫所有欄位")
        else:
            try:
                cursor.execute("INSERT INTO products (pid, name, price) VALUES (%s, %s, %s)",
                               (pid, name, int(price)))
                conn.commit()
                flash("✅ 商品新增成功")
                return redirect(url_for("manage_products"))
            except psycopg2.IntegrityError:
                conn.rollback()
                flash("商品 ID 已存在")
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    conn.close()
    return render_template("manage_products.html", products=products)


@app.route("/delete_product/<pid>", methods=["POST"])
@admin_required
def delete_product(pid):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先刪掉購物車裡的相關項目（可選）
    cursor.execute("DELETE FROM cart_items WHERE product_id = %s", (pid,))

    # 再刪除商品
    cursor.execute("DELETE FROM products WHERE pid = %s", (pid,))

    conn.commit()
    conn.close()
    flash("🗑️ 商品與相關購物車項目已刪除")
    return redirect(url_for("manage_products"))

@app.route("/clear_cart", methods=["POST"])
def clear_cart():
    if "username" not in session:
        flash("請先登入")
        return redirect(url_for("login"))

    user_id = session["username"]
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
        conn.commit()
        flash("🧹 已清空購物車")
    except Exception as e:
        print("清空購物車錯誤：", e)
        flash("❌ 清空失敗，請稍後再試")
    finally:
        conn.close()

    return redirect(url_for("cart"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()
        if user and user["password"] == password:
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("登入成功")
            return redirect(url_for("index"))
        else:
            flash("帳號或密碼錯誤")
    return render_template("login.html")

@app.route("/logout")
def logout():
    cart = session.get("cart")
    session.clear()
    session["cart"] = cart or {}
    flash("已登出")
    return redirect(url_for("login"))

@app.route("/manage_users", methods=["GET", "POST"])
@admin_required
def manage_users():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username")
        if action == "delete":
            cursor.execute("DELETE FROM users WHERE username = %s", (username,))
            flash(f"已刪除帳號：{username}")
        elif action == "toggle_role":
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            current_role = cursor.fetchone()["role"]
            new_role = "admin" if current_role == "member" else "member"
            cursor.execute("UPDATE users SET role = %s WHERE username = %s", (new_role, username))
            flash(f"已將 {username} 的權限更改為 {new_role}")
        conn.commit()
    cursor.execute("SELECT username, role FROM users")
    users = cursor.fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm")
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()
        if existing_user:
            flash("帳號已存在")
        elif password != confirm:
            flash("密碼與確認不一致")
        elif not re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', password):
            flash("密碼須含英文與數字，且長度為 6～15 字")
        else:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                           (username, password, "member"))
            conn.commit()
            session["username"] = username
            session["role"] = "member"
            flash("註冊成功，歡迎加入！")
            conn.close()
            return redirect(url_for("index"))
        conn.close()
    return render_template("register.html")

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    username = session.get("username")
    if not username:
        flash("請先登入")
        return redirect(url_for("login"))
    if request.method == "POST":
        old = request.form.get("old_password")
        new = request.form.get("new_password")
        confirm = request.form.get("confirm_password")
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if not user:
            flash("找不到使用者")
        elif user["password"] != old:
            flash("舊密碼錯誤")
        elif new != confirm:
            flash("新密碼與確認不一致")
        elif not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', new):
            flash("新密碼須包含英文與數字，且長度為 6～15 字")
        else:
            cursor.execute("UPDATE users SET password = %s WHERE username = %s", (new, username))
            conn.commit()
            flash("密碼已更新")
            conn.close()
            return redirect(url_for("index"))
        conn.close()
    return render_template("change_password.html")

@app.route("/upload", methods=["GET", "POST"])
@admin_required
def upload_video():
    video_folder = os.path.join(app.static_folder, "videos")
    os.makedirs(video_folder, exist_ok=True)
    if request.method == "POST":
        file = request.files.get("video")
        if file and file.filename.endswith(".mp4"):
            save_path = os.path.join(video_folder, file.filename)
            if os.path.exists(save_path):
                flash("已有同名影片，請重新命名")
                return redirect(url_for("upload_video"))
            file.save(save_path)
            flash("影片上傳成功！")
            return redirect(url_for("upload_video"))
        else:
            flash("請選擇 mp4 檔案")
            return redirect(request.url)
    videos = [f for f in os.listdir(video_folder) if f.endswith(".mp4")]
    return render_template("upload.html", videos=videos)

@app.route("/delete/<filename>", methods=["POST"])
@admin_required
def delete_video(filename):
    path = os.path.join(app.static_folder, "videos", filename)
    if os.path.exists(path):
        os.remove(path)
        flash(f"已刪除：{filename}")
    else:
        flash("找不到影片")
    return redirect(url_for("upload_video"))

@app.route("/video")
def video_gallery():
    folder = os.path.join(app.static_folder, "videos")
    os.makedirs(folder, exist_ok=True)
    videos = [f for f in os.listdir(folder) if f.endswith(".mp4")]
    return render_template("video.html", videos=videos)

@app.context_processor
def inject_cart_count():
    cart_count = 0
    if "username" in session:
        user_id = session["username"]
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(quantity) FROM cart_items WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            cart_count = result[0] or 0
        except Exception as e:
            print("取得購物車數量錯誤：", e)
        finally:
            if conn:
                conn.close()
    return dict(cart_count=cart_count)


if __name__ == "__main__":
    app.run(debug=True)
