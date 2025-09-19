from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from flask_mail import Mail, Message
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid, mimetypes
from werkzeug.utils import secure_filename
from flask import send_file, abort

import random
load_dotenv()

# 驗證規則（台灣手機 & 一般 Email）
PHONE_RE = re.compile(r'^09\d{2}-?\d{3}-?\d{3}$')       # 09xx-xxx-xxx 或 09xxxxxxxxx
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')    # 簡化 RFC，夠用且穩定



app = Flask(__name__)
app.secret_key = "9OG80KJiLKjfFowu4lqiMEo_Hv3r1EVGzvcP6MR2Av0"  # 建議換成隨機字串
app.permanent_session_lifetime = timedelta(days=7)     # 登入有效時間 7 天

# 設定 mail
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = os.environ.get("MAIL_USE_TLS") == "True"
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_DEFAULT_SENDER")

mail = Mail(app)

# app.jinja_env.cache = {}  # ✅ 關閉模板快取（開發用）

# 建立 PostgreSQL 資料庫連線

def get_db_connection():
    conn = psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )
    return conn

# 下載專區：實體檔案目錄
FILES_DIR = os.path.join(app.root_path, "static", "files")
os.makedirs(FILES_DIR, exist_ok=True)

def ensure_downloads_table():
    """確保 downloads 資料表存在（id/title/filename/uploaded_at）"""
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    title TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    conn.close()

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

# ✅ 自動刷新 session，讓有操作的人不會被登出
@app.before_request
def refresh_session():
    if session.get("username"):
        session.permanent = True

# 禁止快取的 decorator
def nocache(view):
    @wraps(view)
    def _wrapped(*args, **kwargs):
        resp = make_response(view(*args, **kwargs))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, private"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return _wrapped


def ensure_about_row(conn):
    with conn.cursor() as cur:
        # 建表（若尚未建）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS about_page (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL DEFAULT ''
        );
        """)
        # 確保有 id=1 這一列
        cur.execute("SELECT id FROM about_page WHERE id = 1;")
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO about_page (id, content) VALUES (1, '');")
        conn.commit()

def gen_three_hour_slots(start_hour=9, end_hour=21, step=3):
    """產生每 3 小時一個區段，例如 09:00–12:00 ... 18:00–21:00"""
    slots = []
    h = start_hour
    while h < end_hour:
        hh1 = f"{h:02d}:00"
        hh2 = f"{h+step:02d}:00"
        label = f"{hh1}–{hh2}"
        # id 與 label 同步，直接存這段字串最簡單
        slots.append((label, label))
        h += step
    return slots

def get_rent_time_slots():
    # 全站統一使用 en dash（–）
    return [
        ("09:00–12:00", "09:00–12:00"),
        ("13:00–16:00", "13:00–16:00"),
        ("18:00–21:00", "18:00–21:00"),
    ]


# app.secret_key = '9OG80KJiLKjfFowu4lqiMEo_Hv3r1EVGzvcP6MR2Av0'

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
            date < %s
            OR (date = %s AND (
                  (time_slot = '09:00–12:00' AND %s >= '12:00')
               OR (time_slot = '12:00–15:00' AND %s >= '15:00')
               OR (time_slot = '15:00–18:00' AND %s >= '18:00')
               OR (time_slot = '18:00–21:00' AND %s >= '21:00')
            ))
          )
    """, (now.date(), now.date(),
          now.strftime('%H:%M'),
          now.strftime('%H:%M'),
          now.strftime('%H:%M'),
          now.strftime('%H:%M')))
    conn.commit()
    conn.close()


# @app.route("/test")
# def test():
#     return render_template("test.html", cart_count=999, username="測試")


@app.route("/")
@nocache
def index():
    return render_template("index.html")

@app.route("/about")
def about():
    conn = get_db_connection()
    ensure_about_row(conn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT content FROM about_page WHERE id = 1;")
    result = cur.fetchone()
    conn.close()
    content = (result or {}).get("content", "")
    return render_template("about.html", content=content)

@app.route("/edit_about", methods=["GET", "POST"])
@admin_required
def edit_about():
    conn = get_db_connection()
    ensure_about_row(conn)
    if request.method == "POST":
        new_content = request.form.get("content", "").strip()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO about_page (id, content) VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content;
            """, (new_content,))
            conn.commit()
        conn.close()
        flash("更新成功！")
        return redirect(url_for("about"))

    # GET：把現有內容帶回編輯畫面
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT content FROM about_page WHERE id = 1;")
    result = cur.fetchone()
    conn.close()
    content = (result or {}).get("content", "")
    return render_template("edit_about.html", content=content)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")
        answer = request.form.get("captcha_answer")

        # 必填檢查
        if not name or not email or not message or not answer:
            flash("❌ 所有欄位都必填", "warning")
            return redirect(url_for("contact"))

        # 驗證碼檢查
        if str(session.get("captcha_answer")) != str(answer).strip():
            flash("⚠️ 驗證碼錯誤，請再試一次", "danger")
            return redirect(url_for("contact"))
        # Email 格式驗證
        if not EMAIL_RE.match(email or ""):
            flash("❌ Email 格式不正確，請重新輸入", "danger")
            return redirect(url_for("contact"))

        # 寫進 contact_messages
        try:
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO contact_messages (name, email, message) VALUES (%s, %s, %s)",
                        (name, email, message)
                    )
            conn.close()
        except Exception as e:
            flash("⚠️ 儲存留言失敗：" + str(e), "danger")
            return redirect(url_for("contact"))

        # 寄 Email
        try:
            receiver = os.environ.get("CONTACT_TO") or os.environ.get("MAIL_RECEIVER")
            msg = Message(
                subject="🔔 聯絡表單留言",
                recipients=[receiver],
                body=f"""
📩 姓名：{name}
📧 Email：{email}
📝 留言內容：
{message}
                """
            )
            mail.send(msg)
            flash("✅ 留言已送出，我們會盡快回覆您！", "success")
        except Exception as e:
            flash("⚠️ 寄送 email 失敗：" + str(e), "danger")

        return redirect(url_for("contact"))

    # GET：產生驗證碼
    a, b = random.randint(1, 9), random.randint(1, 9)
    session["captcha_answer"] = str(a + b)
    return render_template("contact.html", captcha_question=f"{a} + {b} = ?")


@app.route("/download")
def downloads():
    ensure_downloads_table()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, filename, title, uploaded_at
        FROM downloads
        ORDER BY uploaded_at DESC, id DESC
    """)
    file_list = cur.fetchall()
    conn.close()

    # 產生靜態網址與友善下載檔名
    for row in file_list:
        ext = os.path.splitext(row["filename"])[1]
        row["static_url"] = url_for("static", filename=f"files/{row['filename']}")
        row["download_name"] = f"{row['title']}{ext}"   # e.g. 標題.pdf

    return render_template("download.html", file_list=file_list)

# ====== 下載專區：實際提供下載 ======
@app.route("/download/file/<int:file_id>")
def download_file(file_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT filename, title FROM downloads WHERE id=%s", (file_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        abort(404)

    filename = row["filename"]

    # 防止路徑跳脫
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        abort(400)

    file_path = os.path.join(FILES_DIR, filename)
    if not os.path.isfile(file_path):
        abort(404)

    ext = os.path.splitext(filename)[1]
    download_name = f"{row['title']}{ext}"
    guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # ✅ 用絕對路徑送檔案，瀏覽器不管能不能預覽都會觸發下載
    return send_file(
        file_path,
        as_attachment=True,
        download_name=download_name,
        mimetype=guessed
    )


# ====== 下載專區：刪除（硬碟 + DB） ======
@app.route("/download/delete/<int:file_id>", methods=["POST"])
@admin_required
def delete_download(file_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT filename FROM downloads WHERE id=%s", (file_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        flash("檔案不存在或已被刪除")
        return redirect(url_for("downloads"))

    file_path = os.path.join(FILES_DIR, row["filename"])
    fs_err = None
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            fs_err = str(e)

    cur.execute("DELETE FROM downloads WHERE id=%s", (file_id,))
    conn.commit()
    conn.close()

    if fs_err:
        flash("已刪除資料庫紀錄，但刪檔時發生問題：" + fs_err, "warning")
    else:
        flash("🗑️ 檔案已刪除", "success")
    return redirect(url_for("downloads"))


@app.route("/upload_file", methods=["GET", "POST"])
@admin_required
def upload_file():
    ensure_downloads_table()
    if request.method == "POST":
        file = request.files.get("file")
        title = (request.form.get("title") or "").strip()
        if not file or not file.filename or not title:
            flash("❌ 檔案與標題都必填")
            return redirect(url_for("upload_file"))

        original = secure_filename(file.filename)
        ext = os.path.splitext(original)[1]
        unique = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(FILES_DIR, unique)

        try:
            file.save(save_path)
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO downloads (filename, title) VALUES (%s, %s)",
                        (unique, title)
                    )
            conn.close()
            flash("✅ 上傳成功")
            return redirect(url_for("downloads"))
        except Exception as e:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass
            flash("❌ 上傳失敗：" + str(e))
            return redirect(url_for("upload_file"))

    return render_template("upload_file.html")


@app.route("/news")
def news():
    return render_template("news.html")

@app.route("/rent", methods=["GET", "POST"])
def rent():
    if request.method == "POST":
        location = request.form.get("location")
        date = request.form.get("date")              # YYYY-MM-DD
        time_slot = request.form.get("time_slot")    # 例如 "09:00–12:00"
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

        # ✅【新增】電話/Email 格式驗證（在這裡）
        # PHONE_RE、EMAIL_RE 已在檔案上方宣告
        if not PHONE_RE.match(phone or ""):
            flash("❌ 電話格式錯誤，請輸入 09xx-xxx-xxx（可不輸入連字號）")
            return redirect(url_for("rent"))

        if email and not EMAIL_RE.match(email):
            flash("❌ Email 格式不正確，請重新輸入")
            return redirect(url_for("rent"))

        # ✅【新增】電話統一存成 09xx-xxx-xxx
        digits = re.sub(r"\D", "", phone)[:10]  # 只留前 10 碼
        if len(digits) != 10:
            flash("❌ 電話需為 10 碼手機號碼（09xx-xxx-xxx）")
            return redirect(url_for("rent"))
        phone = f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"

        # 檢查是否已有相同場地+日期+時段（pending/approved 都視為占用）
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM rent_requests
            WHERE location=%s AND date=%s AND time_slot=%s
              AND status IN ('pending','approved')
            """,
            (location, date, time_slot)
        )
        if cur.fetchone():
            conn.close()
            flash("❌ 此時段已被預約")
            return redirect(url_for("rent"))

        # 寫入資料庫（預設狀態 pending）
        cur.execute(
            """
            INSERT INTO rent_requests
                (location, date, time_slot, name, phone, email, note, status, submitted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (location, date, time_slot, name, phone, email, note, 'pending')
        )
        conn.commit()
        conn.close()

        flash("✅ 已送出申請，請等待審核")
        return redirect(url_for("rent"))

    # GET
    return render_template("rent.html", now=datetime.now())

@app.route("/api/rent/disabled_dates", methods=["GET"])
def api_rent_disabled_dates():
    location = (request.args.get("location") or "").strip()
    if not location:
        return jsonify({"disabled_dates": []})

    total_slots_per_day = 3  # 09–12 / 13–16 / 18–21

    conn = get_db_connection()
    cur = conn.cursor()  # 這裡會拿到 RealDictCursor（因為你在 connection 已設定）
    cur.execute("""
        SELECT date, COUNT(DISTINCT time_slot) AS cnt
        FROM rent_requests
        WHERE location=%s
          AND status IN ('pending','approved')
        GROUP BY date
        HAVING COUNT(DISTINCT time_slot) >= %s
        ORDER BY date
    """, (location, total_slots_per_day))
    rows = cur.fetchall()
    conn.close()

    disabled = [r["date"].strftime("%Y-%m-%d") for r in rows]
    return jsonify({"disabled_dates": disabled})

@app.route("/api/rent/timeslots", methods=["GET"])
def api_rent_timeslots():
    """
    GET /api/rent/timeslots?date=YYYY-MM-DD&location=府前教室
    回傳: {"available":[{"id":"09:00–12:00","label":"09:00–12:00"}, ...]}
    """
    location = (request.args.get("location") or "").strip()
    date_str = (request.args.get("date") or "").strip()

    if not location or not date_str:
        return jsonify({"available": []})

    # 驗證日期
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "bad date"}), 400

    # 過去日期沒有可選
    if d < datetime.now().date():
        return jsonify({"available": []})

    # 全部候選時段（改成 3 段）
    all_slots = get_rent_time_slots()

    # 查這天這個場地已被占用（pending/approved 都算）
    conn = get_db_connection()
    cur = conn.cursor()  # RealDictCursor
    cur.execute("""
        SELECT time_slot
        FROM rent_requests
        WHERE location=%s AND date=%s
          AND status IN ('pending','approved')
    """, (location, date_str))
    rows = cur.fetchall()
    conn.close()

    booked = {r["time_slot"] for r in rows}  # ⚠️ RealDictRow 用欄位名取值

    remaining = [
        {"id": slot_id, "label": label}
        for (slot_id, label) in all_slots
        if slot_id not in booked
    ]

    return jsonify({"available": remaining})


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

@app.route("/add_to_cart/<pid>", methods=["GET", "POST"])
def add_to_cart(pid):
    if "username" not in session:
        flash("請先登入才能加入購物車")
        return redirect(url_for("login"))

    user_id = session["username"]
    products = load_products_from_db()

    if pid not in products:
        flash("商品不存在")
        return redirect(url_for("shop"))

    # 取得數量（POST 來自商城表單；GET 則預設 1）
    try:
        qty = int(request.form.get("qty", 1)) if request.method == "POST" else 1
        if qty < 1:
            qty = 1
    except Exception:
        qty = 1

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cart_items (user_id, product_id, quantity)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, product_id)
            DO UPDATE SET quantity = cart_items.quantity + EXCLUDED.quantity
        """, (user_id, pid, qty))
        conn.commit()
        flash(f"✅ 已加入購物車（{qty} 件）")
    except Exception as e:
        print("加入購物車錯誤：", e)
        flash("❌ 加入購物車失敗，請稍後再試")
    finally:
        if conn:
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

@app.route("/update_cart_qty", methods=["POST"])
def update_cart_qty():
    if "username" not in session:
        flash("請先登入")
        return redirect(url_for("login"))

    user_id = session["username"]
    pids = request.form.getlist("pid[]")
    qtys = request.form.getlist("qty[]")

    if not pids or not qtys or len(pids) != len(qtys):
        flash("❌ 更新失敗，資料不完整")
        return redirect(url_for("cart"))

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        for pid, qty_str in zip(pids, qtys):
            try:
                q = int(qty_str)
                if q < 1:
                    q = 1
            except Exception:
                q = 1
            cursor.execute("""
                UPDATE cart_items
                SET quantity = %s
                WHERE user_id = %s AND product_id = %s
            """, (q, user_id, pid))
        conn.commit()
        flash("✅ 數量已更新")
    except Exception as e:
        print("更新購物車數量錯誤：", e)
        flash("❌ 數量更新失敗，請稍後再試")
    finally:
        if conn:
            conn.close()

    return redirect(url_for("cart"))

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

@app.route("/checkout", methods=["POST"])
def checkout():
    if "username" not in session:
        flash("請先登入")
        return redirect(url_for("login"))

    user_id = session["username"]
    pids = request.form.getlist("pid[]")
    qtys = request.form.getlist("qty[]")

    if not pids or not qtys or len(pids) != len(qtys):
        flash("❌ 結帳資料不完整")
        return redirect(url_for("cart"))

    # 轉成整數並過濾非法數量
    cleaned = []
    for pid, qty_str in zip(pids, qtys):
        try:
            q = int(qty_str)
            if q > 0:
                cleaned.append((pid, q))
        except Exception:
            pass
    if not cleaned:
        flash("❌ 沒有可結帳的商品")
        return redirect(url_for("cart"))

    # 從資料庫抓商品資訊
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    only_pids = [pid for pid, _ in cleaned]
    cursor.execute("SELECT pid, name, price FROM products WHERE pid = ANY(%s)", (only_pids,))
    rows = cursor.fetchall()
    conn.close()

    # 組合成結帳清單
    info = {r["pid"]: r for r in rows}
    items = []
    total = 0
    for pid, q in cleaned:
        if pid in info:
            name = info[pid]["name"]
            price = info[pid]["price"]
            subtotal = price * q
            total += subtotal
            items.append({"pid": pid, "name": name, "price": price, "qty": q, "subtotal": subtotal})

    if not items:
        flash("❌ 沒有可結帳的商品")
        return redirect(url_for("cart"))

    return render_template("checkout.html", items=items, total=total)

# 需要在檔案頂端加： from flask import jsonify

@app.route("/api/cart/qty", methods=["POST"])
def api_cart_qty():
    if "username" not in session:
        return jsonify({"ok": False, "error": "login_required"}), 401

    data = request.get_json(silent=True) or {}
    pid = data.get("pid")
    try:
        qty = int(data.get("qty", 1))
    except Exception:
        qty = 1
    if qty < 1:
        qty = 1

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE cart_items
            SET quantity = %s
            WHERE user_id = %s AND product_id = %s
        """, (qty, session["username"], pid))
        conn.commit()
        return jsonify({"ok": True, "qty": qty})
    except Exception as e:
        print("API 更新數量錯誤：", e)
        return jsonify({"ok": False, "error": "server_error"}), 500
    finally:
        if conn:
            conn.close()

@app.after_request
def add_no_cache_headers(resp):
    ctype = resp.headers.get("Content-Type", "")
    # 只處理 HTML（避免影響靜態檔案快取）
    if ctype.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        # 讓代理快取知道內容會依 Cookie（登入）不同
        resp.headers["Vary"] = "Cookie"
    return resp

@app.route("/login", methods=["GET", "POST"])
@nocache
def login():
    # ✅ 已登入者，不准再進 login 頁面
    if session.get("username"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and user["password"] == password:
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True   # ✅ 登入後設成永久
            flash("登入成功")
            return redirect(url_for("index"))
        else:
            flash("帳號或密碼錯誤")

    return render_template("login.html")

@app.route("/logout")
@nocache
def logout():
    cart = session.get("cart")  # 如果要保留購物車
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
@nocache
def register():
    # 已登入者不需再註冊，直接回首頁
    if session.get("username"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        if not username or not password or not confirm:
            flash("所有欄位都必填")
            return render_template("register.html")

        # 密碼規則：6~15 字，且同時含英文字母與數字
        if not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', password):
            flash("密碼須同時包含英文與數字，且長度為 6～15 字")
            return render_template("register.html")

        if password != confirm:
            flash("密碼與確認不一致")
            return render_template("register.html")

        conn = get_db_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # 檢查帳號是否存在
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            exists = cur.fetchone()
            if exists:
                flash("帳號已存在")
                return render_template("register.html")

            # 建立帳號（此版本沿用你的純文字密碼儲存）
            cur.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, password, "member")
            )
            conn.commit()

            # 註冊後自動登入並保持登入狀態
            session["username"] = username
            session["role"] = "member"
            session.permanent = True
            flash("註冊成功，歡迎加入！")
            return redirect(url_for("index"))

        except Exception as e:
            conn.rollback()
            flash(f"註冊失敗：{e}")
            return render_template("register.html")
        finally:
            conn.close()

    # GET
    return render_template("register.html")

@app.route("/change_password", methods=["GET", "POST"])
@nocache
def change_password():
    username = session.get("username")
    if not username:
        flash("請先登入")
        return redirect(url_for("login"))

    if request.method == "POST":
        old     = request.form.get("old_password", "")
        new     = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if not old or not new or not confirm:
            flash("所有欄位都必填")
            return render_template("change_password.html")

        if new != confirm:
            flash("新密碼與確認不一致")
            return render_template("change_password.html")

        # 密碼規則：6~15 字，且同時含英文字母與數字
        if not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', new):
            flash("新密碼須同時包含英文與數字，且長度為 6～15 字")
            return render_template("change_password.html")

        conn = get_db_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT password FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if not user:
                flash("找不到使用者")
                return render_template("change_password.html")

            if user["password"] != old:
                flash("舊密碼錯誤")
                return render_template("change_password.html")

            cur.execute("UPDATE users SET password = %s WHERE username = %s", (new, username))
            conn.commit()

            # 保持登入狀態（可續用）
            session.permanent = True
            flash("密碼已更新")
            return redirect(url_for("index"))

        except Exception as e:
            conn.rollback()
            flash(f"更新失敗：{e}")
            return render_template("change_password.html")
        finally:
            conn.close()

    # GET
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
    # 未登入或查不到資料 → 0
    username = session.get("username")
    if not username:
        return dict(cart_count=0)

    total = 0
    conn = None
    try:
        conn = get_db_connection()
        # 用 RealDictCursor，查回 dict；再用 COALESCE 避免 None
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM cart_items WHERE user_id = %s",
            (username,)
        )
        row = cur.fetchone() or {}
        total = row.get("total", 0)
        print("✅ inject_cart_count → user_id =", username, "total =", total)
    except Exception as e:
        print("⚠️ inject_cart_count error:", e)
    finally:
        if conn:
            conn.close()

    return dict(cart_count=total)



if __name__ == "__main__":
    app.run(debug=True)
