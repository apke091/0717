from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from flask_mail import Mail, Message
import os, re, uuid, mimetypes
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
TZ = timezone(timedelta(hours=8))  # Asia/Taipei
from werkzeug.utils import secure_filename
from flask import send_file, abort
import flask as _flask
from pathlib import Path
from PIL import Image  # requirements.txt 記得加 Pillow>=10.0


import random
load_dotenv()
# ====== 上傳/媒體 共用工具（放在 imports 後、任何使用之前） ======

# 允許的媒體副檔名（圖片 + 影片）
ALLOWED_MEDIA_EXTS = {
    "jpg", "jpeg", "png", "webp", "gif",
    "mp4", "mov", "m4v", "webm"
}

def allowed_ext(filename: str, allow_set: set) -> bool:
    """檢查副檔名是否在允許清單中。"""
    if not filename:
        return False
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allow_set

def guess_mime(name_or_path: str) -> str:
    """用副檔名推測 MIME；未知時回傳 octet-stream。"""
    return mimetypes.guess_type(name_or_path)[0] or "application/octet-stream"

def safe_uuid_filename(original_name: str) -> str:
    """
    以原始副檔名建立不重複檔名，例如 'fuqian.jpg' -> '<uuid>.jpg'。
    若沒有副檔名則直接用 uuid。
    """
    base = secure_filename(original_name) or "file"
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if ext:
        return f"{uuid.uuid4().hex}.{ext}"
    return uuid.uuid4().hex

# 驗證規則（台灣手機 & 一般 Email）
PHONE_RE = re.compile(r'^09\d{2}-?\d{3}-?\d{3}$')       # 09xx-xxx-xxx 或 09xxxxxxxxx
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')    # 簡化 RFC，夠用且穩定

app = Flask(__name__)
app.secret_key = "9OG80KJiLKjfFowu4lqiMEo_Hv3r1EVGzvcP6MR2Av0"  # 建議換成隨機字串
app.permanent_session_lifetime = timedelta(days=7)     # 登入有效時間 7 天

# 放在檔案最上面統一設定
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER_NEWS = os.path.join(BASE_DIR, "uploads", "news")
ALLOWED_NEWS_EXTS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "ppt", "pptx"}
os.makedirs(UPLOAD_FOLDER_NEWS, exist_ok=True)

# 設定 mail
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = os.environ.get("MAIL_USE_TLS") == "True"
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_DEFAULT_SENDER")
mail = Mail(app)

# 檔案儲存設定
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads")).resolve()
REVIEW_UPLOAD_SUBDIR = "reviews"
ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_MB = 12
THUMB_SIZES = [480, 960]
WEBP_QUALITY = 82
JPEG_QUALITY = 85

# 檔名處理/縮圖工具
_slugify_re = re.compile(r"[^fuqian-z0-9\-]+")
def slugify_filename(name: str) -> str:
    base = os.path.splitext(name)[0].lower().strip().replace(" ", "-")
    base = _slugify_re.sub("-", base).strip("-") or "file"
    return base

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def unique_path(dirpath: Path, stem: str, ext: str) -> Path:
    return dirpath / f"{stem}__{uuid.uuid4().hex[:8]}.{ext}"

def _guess_mime(p: Path) -> str:
    return mimetypes.guess_type(str(p))[0] or "application/octet-stream"

def resize_fit_width(img: Image.Image, width: int) -> Image.Image:
    if img.width <= width:
        return img.copy()
    ratio = width / float(img.width)
    new_h = max(1, int(img.height * ratio))
    return img.resize((width, new_h), Image.LANCZOS)

# 最小版：若你已跑過 init_db，這裡就什麼都不做，避免缺函式報錯
def ensure_review_tables():
    return

# ===== flash 自動判斷類別（避免忘了帶 category）======
if not hasattr(_flask, "_original_flash"):
    _flask._original_flash = _flask.flash  # 保存原始 flash 函式

def _infer_flash_category(message):
    text = str(message); low = text.lower()
    success_keys = ["✅", "成功", "已送出", "已加入", "已更新", "上傳成功", "登入成功", "已清空", "已移除", "已刪除", "更新成功", "影片上傳成功"]
    danger_keys  = ["❌", "錯誤", "失敗", "不能", "不可", "不存在", "找不到", "不完整", "無法", "驗證碼錯誤", "已存在", "不能選擇", "沒有可結帳"]
    warning_keys = ["⚠", "提醒", "請選擇", "請填寫", "必填", "警告"]
    if any(k in text or k in low for k in success_keys): return "success"
    if any(k in text or k in low for k in danger_keys):  return "danger"
    if any(k in text or k in low for k in warning_keys): return "warning"
    return "info"

def flash(message, category=None):
    if category is None or not str(category).strip():
        category = _infer_flash_category(message)
    return _flask._original_flash(message, category)
# ==============================================

def allowed_news_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_NEWS_EXTS

# 建立 PostgreSQL 資料庫連線
def get_db_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)

# 上傳資料夾 & 允許副檔名（課程DM）
UPLOAD_FOLDER_COURSES = os.path.join(BASE_DIR, "uploads", "courses")
ALLOWED_COURSE_EXTS = {"pdf", "jpg", "jpeg", "png"}
os.makedirs(UPLOAD_FOLDER_COURSES, exist_ok=True)

def ensure_courses_table():
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
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
    conn.close()

LOCATION_ALBUMS = {
    "府前教室": "rent/fuqian",
    "西門教室": "rent/ximen",
}

VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

def list_images(static_subdir: str):
    base_dir = Path(app.static_folder) / static_subdir
    if not base_dir.exists():
        return []
    files = sorted([p.name for p in base_dir.iterdir() if p.suffix.lower() in VALID_EXTS])
    return [url_for('static', filename=f"{static_subdir}/{name}") for name in files]

def build_albums():
    return {loc: list_images(subdir) for loc, subdir in LOCATION_ALBUMS.items()}

def allowed_course_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_COURSE_EXTS

def save_course_dm(file_storage):
    if not file_storage or not file_storage.filename.strip():
        return None
    fn = secure_filename(file_storage.filename)
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext not in ALLOWED_COURSE_EXTS:
        return None
    uniq = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(UPLOAD_FOLDER_COURSES, uniq)
    file_storage.save(abs_path)
    return f"courses/{uniq}"

def delete_course_dm_if_exists(relpath: str):
    if not relpath or not relpath.startswith("courses/"):
        return
    abs_path = os.path.join(BASE_DIR, "uploads", relpath.replace("courses/", f"courses{os.sep}"))
    if os.path.exists(abs_path):
        try: os.remove(abs_path)
        except Exception: pass

# 下載專區：實體檔案目錄
FILES_DIR = os.path.join(app.root_path, "static", "files")
os.makedirs(FILES_DIR, exist_ok=True)

def ensure_downloads_table():
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
    return {row["pid"]: {"name": row["name"], "price": int(row["price"])} for row in rows}

# ✅ 自動刷新 session
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
        cur.execute("""
        CREATE TABLE IF NOT EXISTS about_page (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL DEFAULT ''
        );
        """)
        cur.execute("SELECT id FROM about_page WHERE id = 1;")
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO about_page (id, content) VALUES (1, '');")
        conn.commit()

# ===== 時段常數（統一使用這一份）=====
# 格式: (value, start_hm, end_hm)
TIME_SLOTS = [
    ("09:00-12:00", "09:00", "12:00"),
    ("13:00-16:00", "13:00", "16:00"),
    ("18:00-21:00", "18:00", "21:00"),
]

def get_rent_time_slots():
    # 提供顯示用標籤（將 - 換為 –）
    return [(val.replace("-", "–"), val.replace("-", "–")) for (val, _s, _e) in TIME_SLOTS]

def get_booked_slots(conn, y, m, d, location):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT time_slot
            FROM rent_requests
            WHERE date = %s AND location = %s AND status IN ('approved', 'pending')
        """, (datetime(y, m, d, tzinfo=TZ).date(), location))
        rows = cur.fetchall()
    return {(r["time_slot"] or "").replace("–", "-").strip() for r in rows}

def delete_expired_rent_requests():
    """
    刪除已過期的核准租借（以 TIME_SLOTS 為準）
    規則：只刪 status='approved'，且
      - 日期小於今天，或
      - 同日且該時段的「結束時間」已過
    """
    now = datetime.now(TZ)
    today = now.date()
    now_hm = now.strftime("%H:%M")
    end_map = {slot: end for (slot, _start, end) in TIME_SLOTS}

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM rent_requests
                WHERE status='approved' AND date < %s
            """, (today,))
            for slot, end_hm in end_map.items():
                slot_en  = slot
                slot_emd = slot.replace("-", "–")
                cur.execute("""
                    DELETE FROM rent_requests
                    WHERE status = 'approved'
                      AND date = %s
                      AND (time_slot = %s OR time_slot = %s)
                      AND %s >= %s
                """, (today, slot_en, slot_emd, now_hm, end_hm))
    conn.close()

# 管理員權限驗證
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            flash("您沒有權限執行此操作")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# ================= 頁面 =================
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

        if not name or not email or not message or not answer:
            flash("❌ 所有欄位都必填", "warning"); return redirect(url_for("contact"))
        if str(session.get("captcha_answer")) != str(answer).strip():
            flash("⚠️ 驗證碼錯誤，請再試一次", "danger"); return redirect(url_for("contact"))
        if not EMAIL_RE.match(email or ""):
            flash("❌ Email 格式不正確，請重新輸入", "danger"); return redirect(url_for("contact"))

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
            flash("⚠️ 儲存留言失敗：" + str(e), "danger"); return redirect(url_for("contact"))

        try:
            receiver = os.environ.get("CONTACT_TO") or os.environ.get("MAIL_RECEIVER")
            msg = Message(
                subject="🔔 聯絡表單留言",
                recipients=[receiver],
                body=f"📩 姓名：{name}\n📧 Email：{email}\n📝 留言內容：\n{message}\n"
            )
            mail.send(msg)
            flash("✅ 留言已送出，我們會盡快回覆您！", "success")
        except Exception as e:
            flash("⚠️ 寄送 email 失敗：" + str(e), "danger")

        return redirect(url_for("contact"))

    a, b = random.randint(1, 9), random.randint(1, 9)
    session["captcha_answer"] = str(a + b)
    return render_template("contact.html", captcha_question=f"{a} + {b} = ?")

# ===== 下載專區 =====
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
    for row in file_list:
        ext = os.path.splitext(row["filename"])[1]
        row["static_url"] = url_for("static", filename=f"files/{row['filename']}")
        row["download_name"] = f"{row['title']}{ext}"
    return render_template("download.html", file_list=file_list)

@app.route("/download/file/<int:file_id>")
def download_file(file_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT filename, title FROM downloads WHERE id=%s", (file_id,))
    row = cur.fetchone()
    conn.close()
    if not row: abort(404)

    filename = row["filename"]
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        abort(400)

    file_path = os.path.join(FILES_DIR, filename)
    if not os.path.isfile(file_path): abort(404)

    ext = os.path.splitext(filename)[1]
    download_name = f"{row['title']}{ext}"
    guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_file(file_path, as_attachment=True, download_name=download_name, mimetype=guessed)

@app.route("/download/delete/<int:file_id>", methods=["POST"])
@admin_required
def delete_download(file_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT filename FROM downloads WHERE id=%s", (file_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); flash("檔案不存在或已被刪除"); return redirect(url_for("downloads"))

    file_path = os.path.join(FILES_DIR, row["filename"])
    fs_err = None
    if os.path.exists(file_path):
        try: os.remove(file_path)
        except Exception as e: fs_err = str(e)

    cur.execute("DELETE FROM downloads WHERE id=%s", (file_id,))
    conn.commit(); conn.close()

    if fs_err: flash("已刪除資料庫紀錄，但刪檔時發生問題：" + fs_err, "warning")
    else:      flash("🗑️ 檔案已刪除", "success")
    return redirect(url_for("downloads"))

@app.route("/upload_file", methods=["GET", "POST"])
@admin_required
def upload_file():
    ensure_downloads_table()
    if request.method == "POST":
        file = request.files.get("file")
        title = (request.form.get("title") or "").strip()
        if not file or not file.filename or not title:
            flash("❌ 檔案與標題都必填"); return redirect(url_for("upload_file"))

        original = secure_filename(file.filename)
        ext = os.path.splitext(original)[1]
        unique = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(FILES_DIR, unique)

        try:
            file.save(save_path)
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO downloads (filename, title) VALUES (%s, %s)", (unique, title))
            conn.close()
            flash("✅ 上傳成功"); return redirect(url_for("downloads"))
        except Exception as e:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass
            flash("❌ 上傳失敗：" + str(e)); return redirect(url_for("upload_file"))

    return render_template("upload_file.html")

@app.route("/news")
def news():
    return render_template("news.html")

# ===== 租借 =====
@app.route("/rent", methods=["GET", "POST"])
def rent():
    if request.method == "POST":
        location = (request.form.get("location") or "").strip()
        date = (request.form.get("date") or "").strip()
        time_slot = (request.form.get("time_slot") or "").strip()
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        note = (request.form.get("note") or "").strip()

        if not (location and date and time_slot and name and phone):
            flash("❌ 必填欄位未填寫完整"); return redirect(url_for("rent"))

        today = datetime.now(TZ).date()
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            flash("❌ 日期格式錯誤"); return redirect(url_for("rent"))
        if selected_date < today:
            flash("❌ 不能選擇今天以前的日期"); return redirect(url_for("rent"))

        if not PHONE_RE.match(phone):
            flash("❌ 電話格式錯誤，請輸入 09xx-xxx-xxx（可不輸入連字號）"); return redirect(url_for("rent"))

        email = (email or "").strip()
        if not email:            flash("❌ Email 為必填"); return redirect(url_for("rent"))
        if not EMAIL_RE.match(email): flash("❌ Email 格式不正確，請重新輸入"); return redirect(url_for("rent"))

        digits = re.sub(r"\D", "", phone)[:10]
        if len(digits) != 10:
            flash("❌ 電話需為 10 碼手機號碼（09xx-xxx-xxx）"); return redirect(url_for("rent"))
        phone = f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM rent_requests
            WHERE location=%s AND date=%s AND time_slot=%s
              AND status IN ('pending','approved')
        """, (location, date, time_slot))
        if cur.fetchone():
            conn.close(); flash("❌ 此時段已被預約"); return redirect(url_for("rent"))

        cur.execute("""
            INSERT INTO rent_requests
                (location, date, time_slot, name, phone, email, note, status, submitted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
        """, (location, date, time_slot, name, phone, email, note))
        conn.commit(); conn.close()

        flash("✅ 已送出申請，請等待審核"); return redirect(url_for("rent"))

    return render_template("rent.html", now=datetime.now(TZ).isoformat())

@app.route("/api/rent/disabled_dates", methods=["GET"])
def api_rent_disabled_dates():
    location = (request.args.get("location") or "").strip()
    if not location:
        return jsonify({"disabled_dates": []})

    total_slots_per_day = 3
    conn = get_db_connection()
    cur = conn.cursor()
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
    location = (request.args.get("location") or "").strip()
    date_str = (request.args.get("date") or "").strip()
    if not location or not date_str:
        return jsonify({"available": []})

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "bad date"}), 400

    today = datetime.now(TZ).date()
    now   = datetime.now(TZ)
    if d < today:
        return jsonify({"available": []})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT time_slot
        FROM rent_requests
        WHERE location=%s AND date=%s
          AND status IN ('pending','approved')
    """, (location, date_str))
    rows = cur.fetchall()
    conn.close()
    booked = {(r["time_slot"] or "").replace("–", "-").strip() for r in rows}

    available = []
    for val, start_hm, end_hm in TIME_SLOTS:
        if val in booked: continue
        if d == today:
            sh, sm = map(int, start_hm.split(":"))
            start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=TZ)
            if start_dt <= now: continue
        available.append({"id": val, "label": val.replace("-", "–")})
    return jsonify({"available": available})

@app.route("/manage_rents", methods=["GET", "POST"])
@admin_required
def manage_rents():
    delete_expired_rent_requests()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == "POST":
        rent_id = request.form["id"]
        action = request.form["action"]
        if action == "approve":
            cur.execute("UPDATE rent_requests SET status='approved' WHERE id=%s", (rent_id,))
        elif action == "reject":
            cur.execute("UPDATE rent_requests SET status='rejected' WHERE id=%s", (rent_id,))
        conn.commit()

    cur.execute("SELECT * FROM rent_requests ORDER BY submitted_at DESC")
    rents = cur.fetchall()
    conn.close()
    return render_template("manage_rents.html", rents=rents)

# ===== 購物車/商品 =====
@app.route("/shop")
def shop():
    products = load_products_from_db()
    return render_template("shop.html", products=products)

@app.route("/add_to_cart/<pid>", methods=["GET", "POST"])
def add_to_cart(pid):
    if "username" not in session:
        flash("請先登入才能加入購物車"); return redirect(url_for("login"))

    user_id = session["username"]
    products = load_products_from_db()
    if pid not in products:
        flash("商品不存在"); return redirect(url_for("shop"))

    try:
        qty = int(request.form.get("qty", 1)) if request.method == "POST" else 1
        if qty < 1: qty = 1
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
        conn.commit(); flash(f"✅ 已加入購物車（{qty} 件）")
    except Exception as e:
        print("加入購物車錯誤：", e); flash("❌ 加入購物車失敗，請稍後再試")
    finally:
        if conn: conn.close()

    return redirect(url_for("shop"))

@app.route("/cart")
def cart():
    if "username" not in session:
        flash("請先登入才能查看購物車"); return redirect(url_for("login"))
    user_id = session["username"]

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT p.pid, p.name, p.price, ximen.quantity, (p.price * ximen.quantity) AS subtotal
        FROM cart_items ximen
        JOIN products p ON ximen.product_id = p.pid
        WHERE ximen.user_id = %s
    """, (user_id,))
    items = cursor.fetchall()
    total = sum(item["subtotal"] for item in items)
    conn.close()
    return render_template("cart.html", items=items, total=total)

@app.route("/update_cart_qty", methods=["POST"])
def update_cart_qty():
    if "username" not in session:
        flash("請先登入"); return redirect(url_for("login"))

    user_id = session["username"]
    single_pid = request.form.get("pid")
    single_qty = request.form.get("qty")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if single_pid and single_qty:
            try: q = max(1, int(single_qty))
            except Exception: q = 1
            cur.execute("""
                UPDATE cart_items SET quantity = %s
                WHERE user_id = %s AND product_id = %s
            """, (q, user_id, single_pid))
            conn.commit(); flash("✅ 數量已更新"); return redirect(url_for("cart"))

        pids = request.form.getlist("pid[]")
        qtys = request.form.getlist("qty[]")
        if not pids or not qtys or len(pids) != len(qtys):
            flash("❌ 更新失敗，資料不完整"); return redirect(url_for("cart"))

        for pid, qty_str in zip(pids, qtys):
            try: q = max(1, int(qty_str))
            except Exception: q = 1
            cur.execute("""
                UPDATE cart_items SET quantity = %s
                WHERE user_id = %s AND product_id = %s
            """, (q, user_id, pid))
        conn.commit(); flash("✅ 數量已更新")
    except Exception as e:
        print("更新購物車數量錯誤：", e); flash("❌ 數量更新失敗，請稍後再試")
    finally:
        conn.close()
    return redirect(url_for("cart"))

@app.route("/remove_from_cart/<pid>")
def remove_from_cart(pid):
    if "username" not in session:
        flash("請先登入"); return redirect(url_for("login"))

    user_id = session["username"]
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s AND product_id = %s", (user_id, pid))
        conn.commit(); flash("🗑️ 已從購物車移除")
    except Exception as e:
        print("刪除購物車項目錯誤：", e); flash("❌ 無法移除，請稍後再試")
    finally:
        if conn: conn.close()
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
                conn.commit(); flash("✅ 商品新增成功"); return redirect(url_for("manage_products"))
            except psycopg2.IntegrityError:
                conn.rollback(); flash("商品 ID 已存在")
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    conn.close()
    return render_template("manage_products.html", products=products)

@app.route("/delete_product/<pid>", methods=["POST"])
@admin_required
def delete_product(pid):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cart_items WHERE product_id = %s", (pid,))
    cursor.execute("DELETE FROM products WHERE pid = %s", (pid,))
    conn.commit(); conn.close()
    flash("🗑️ 商品與相關購物車項目已刪除"); return redirect(url_for("manage_products"))

@app.route("/clear_cart", methods=["POST"])
def clear_cart():
    if "username" not in session:
        flash("請先登入"); return redirect(url_for("login"))
    user_id = session["username"]
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
        conn.commit(); flash("🧹 已清空購物車")
    except Exception as e:
        print("清空購物車錯誤：", e); flash("❌ 清空失敗，請稍後再試")
    finally:
        if conn: conn.close()
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["POST"])
def checkout():
    if "username" not in session:
        flash("請先登入"); return redirect(url_for("login"))

    user_id = session["username"]
    pids = request.form.getlist("pid[]")
    qtys = request.form.getlist("qty[]")
    if not pids or not qtys or len(pids) != len(qtys):
        flash("❌ 結帳資料不完整"); return redirect(url_for("cart"))

    cleaned = []
    for pid, qty_str in zip(pids, qtys):
        try:
            q = int(qty_str)
            if q > 0: cleaned.append((pid, q))
        except Exception:
            pass
    if not cleaned:
        flash("❌ 沒有可結帳的商品"); return redirect(url_for("cart"))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    only_pids = [pid for pid, _ in cleaned]
    cursor.execute("SELECT pid, name, price FROM products WHERE pid = ANY(%s)", (only_pids,))
    rows = cursor.fetchall()
    conn.close()

    info = {r["pid"]: r for r in rows}
    items, total = [], 0
    for pid, q in cleaned:
        if pid in info:
            name = info[pid]["name"]; price = info[pid]["price"]
            subtotal = price * q; total += subtotal
            items.append({"pid": pid, "name": name, "price": price, "qty": q, "subtotal": subtotal})
    if not items:
        flash("❌ 沒有可結帳的商品"); return redirect(url_for("cart"))

    return render_template("checkout.html", items=items, total=total)

# ===== 課程專區 =====
@app.route("/courses")
def courses():
    ensure_courses_table()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, title, description, dm_file, signup_link, pinned, created_at
        FROM courses
        ORDER BY pinned DESC, created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("courses.html", courses=rows)

@app.route("/manage_courses", methods=["GET", "POST"])
@admin_required
def manage_courses():
    ensure_courses_table()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        signup_link = (request.form.get("signup_link") or "").strip()
        pinned = request.form.get("pinned") == "on"
        dm_rel = None
        if not title:
            flash("請填寫標題"); return redirect(url_for("manage_courses"))
        if "dm_file" in request.files:
            dm_rel = save_course_dm(request.files["dm_file"])
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO courses (title, description, dm_file, signup_link, pinned)
                    VALUES (%s, %s, %s, %s, %s)
                """, (title, description, dm_rel, signup_link, pinned))
        conn.close()
        flash("課程已新增"); return redirect(url_for("manage_courses"))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, title, description, dm_file, signup_link, pinned, created_at
        FROM courses
        ORDER BY pinned DESC, created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("manage_courses.html", courses=rows)

@app.route("/manage_courses/<int:course_id>/update", methods=["POST"])
@admin_required
def update_course(course_id):
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    signup_link = (request.form.get("signup_link") or "").strip()
    pinned = request.form.get("pinned") == "on"
    if not title:
        flash("請填寫標題"); return redirect(url_for("manage_courses"))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT dm_file FROM courses WHERE id=%s", (course_id,))
    old = cur.fetchone(); old_dm = (old or {}).get("dm_file")

    new_dm = old_dm
    if "dm_file" in request.files and request.files["dm_file"].filename.strip():
        maybe = save_course_dm(request.files["dm_file"])
        if maybe:
            new_dm = maybe
            if old_dm and old_dm != new_dm:
                delete_course_dm_if_exists(old_dm)

    cur.execute("""
        UPDATE courses
        SET title=%s, description=%s, signup_link=%s, pinned=%s, dm_file=%s
        WHERE id=%s
    """, (title, description, signup_link, pinned, new_dm, course_id))
    conn.commit(); conn.close()
    flash("課程已更新"); return redirect(url_for("manage_courses"))

@app.route("/manage_courses/<int:course_id>/delete", methods=["POST"])
@admin_required
def delete_course(course_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT dm_file FROM courses WHERE id=%s", (course_id,))
    row = cur.fetchone(); dm_rel = (row or {}).get("dm_file")
    cur.execute("DELETE FROM courses WHERE id=%s", (course_id,))
    conn.commit(); conn.close()
    delete_course_dm_if_exists(dm_rel)
    flash("課程已刪除"); return redirect(url_for("manage_courses"))

@app.route("/download/course-dm/<path:filename>")
def download_course_dm(filename):
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        abort(400)
    abs_path = os.path.join(UPLOAD_FOLDER_COURSES, filename)
    if not os.path.isfile(abs_path): abort(404)
    mime = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    return send_file(abs_path, as_attachment=True, download_name=filename, mimetype=mime)

# =========================
# === 課程回顧（新模組） ===
# =========================
UPLOAD_FOLDER_REVIEWS = os.path.join(BASE_DIR, "uploads", "reviews")
os.makedirs(UPLOAD_FOLDER_REVIEWS, exist_ok=True)

def slugify(name: str) -> str:
    s = re.sub(r"\s+", "-", (name or "").strip())
    s = re.sub(r"[^fuqian-zA-Z0-9\-]+", "", s)
    return s.lower()

def ensure_review_tables():
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS review_categories (
              id SERIAL PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              slug TEXT UNIQUE NOT NULL,
              sort_order INTEGER DEFAULT 0
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS course_reviews (
              id SERIAL PRIMARY KEY,
              category_id INTEGER NOT NULL REFERENCES review_categories(id) ON DELETE RESTRICT,
              title TEXT NOT NULL,
              event_date DATE,
              cover_path TEXT,
              summary TEXT,
              content_html TEXT,
              status TEXT DEFAULT 'published',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS review_media (
              id SERIAL PRIMARY KEY,
              review_id INTEGER NOT NULL REFERENCES course_reviews(id) ON DELETE CASCADE,
              file_path TEXT NOT NULL,
              file_name TEXT,
              mime TEXT NOT NULL,
              size_bytes BIGINT,
              sort_order INTEGER DEFAULT 0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_review_media_review ON review_media(review_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_review_media_sort ON review_media(review_id, sort_order, created_at);")

            # 舊 review_photos → 一次性搬移
            cur.execute("SELECT to_regclass('public.review_photos') AS t;")
            has_old = (cur.fetchone() or {}).get("t")
            if has_old:
                cur.execute("SELECT COUNT(*) AS ximen FROM review_media;")
                if (cur.fetchone() or {}).get("ximen", 0) == 0:
                    cur.execute("""
                        INSERT INTO review_media (review_id, file_path, file_name, mime, sort_order, created_at)
                        SELECT review_id, image_path, caption, 'image/*', COALESCE(sort_order,0), NOW()
                        FROM review_photos;
                    """)
    conn.close()

# 取用 /uploads 下的檔案（圖片/影片 inline，其餘下載）
@app.route("/u/<path:relpath>")
def serve_upload(relpath):
    uploads_root = (Path(BASE_DIR) / "uploads").resolve()
    target = (uploads_root / relpath).resolve()
    # 防止 path traversal
    if not str(target).startswith(str(uploads_root)) or not target.is_file():
        abort(404)

    mime = guess_mime(target)
    as_attachment = not (mime.startswith("image/") or mime.startswith("video/"))
    resp = send_file(target, mimetype=mime, as_attachment=as_attachment,
                     download_name=target.name, conditional=True)
    # 圖片/影片可快取，其餘不快取
    resp.headers["Cache-Control"] = "public, max-age=86400" if not as_attachment else "no-store"
    return resp


@app.route("/reviews")
def reviews():
    ensure_review_tables()
    cat_slug = (request.args.get("cat") or "").strip() or None
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,name,slug FROM review_categories ORDER BY sort_order, name;")
            categories = cur.fetchall()
            if cat_slug:
                cur.execute("""
                SELECT r.*, ximen.name AS category_name, ximen.slug AS category_slug
                FROM course_reviews r
                JOIN review_categories ximen ON ximen.id=r.category_id
                WHERE r.status='published' AND ximen.slug=%s
                ORDER BY COALESCE(r.event_date, r.created_at) DESC, r.id DESC
                """, (cat_slug,))
            else:
                cur.execute("""
                SELECT r.*, ximen.name AS category_name, ximen.slug AS category_slug
                FROM course_reviews r
                JOIN review_categories ximen ON ximen.id=r.category_id
                WHERE r.status='published'
                ORDER BY COALESCE(r.event_date, r.created_at) DESC, r.id DESC
                """)
            items = cur.fetchall()
    conn.close()
    return render_template("reviews.html", categories=categories, items=items, cat_slug=cat_slug)

# ====== 回顧：前台單篇 ======
@app.route("/reviews/<int:rid>")
def review_detail(rid: int):
    ensure_review_tables()
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT r.*, ximen.name AS category_name, ximen.slug AS category_slug
            FROM course_reviews r
            JOIN review_categories ximen ON ximen.id=r.category_id
            WHERE r.id=%s
            """, (rid,))
            review = cur.fetchone()
            if not review: abort(404)
            cur.execute("""
            SELECT id, file_path, file_name, mime
            FROM review_media
            WHERE review_id=%s
            ORDER BY sort_order, created_at, id
            """, (rid,))
            media_list = cur.fetchall()
    conn.close()
    return render_template("review_detail.html", review=review, media_list=media_list)

# ====== 回顧：後台列表 + 新增 ======
@app.route("/admin/reviews", methods=["GET","POST"])
@admin_required
def admin_reviews():
    ensure_review_tables()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category_id = request.form.get("category_id")
        event_date = (request.form.get("event_date") or "").strip() or None
        summary = (request.form.get("summary") or "").strip()   # 可留空
        content_html = (request.form.get("content_html") or "").strip()  # 可留空
        status = (request.form.get("status") or "published").strip()
        cover = request.files.get("cover")

        if not title or not category_id:
            flash("請填寫標題與分類","warning"); return redirect(url_for("admin_reviews"))

        cover_path = None
        if cover and cover.filename:
            saved = safe_uuid_filename(cover.filename)
            cover_abs = os.path.join(UPLOAD_FOLDER_REVIEWS, saved)
            cover.save(cover_abs)
            cover_path = f"reviews/{saved}"

        conn = get_db_connection()
        new_id = None
        try:
            with conn:
                with conn.cursor() as cur:
                    if event_date:
                        cur.execute("""
                        INSERT INTO course_reviews(category_id,title,event_date,cover_path,summary,content_html,status)
                        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id
                        """, (category_id, title, event_date, cover_path, summary, content_html, status))
                    else:
                        cur.execute("""
                        INSERT INTO course_reviews(category_id,title,cover_path,summary,content_html,status)
                        VALUES(%s,%s,%s,%s,%s,%s) RETURNING id
                        """, (category_id, title, cover_path, summary, content_html, status))
                    new_id = cur.fetchone()["id"]
            flash("課程回顧已新增，現在可以上傳相片/影片囉！","success")
        except Exception as e:
            flash(f"新增失敗：{e}","danger")
        finally:
            conn.close()
        if new_id:
            return redirect(url_for("admin_review_edit", rid=new_id))
        return redirect(url_for("admin_reviews"))

    # GET
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM review_categories ORDER BY sort_order, name;")
            cats = cur.fetchall()
            cur.execute("""
            SELECT r.id, r.title, r.status, r.event_date, ximen.name AS category_name,
                   COALESCE(m.cnt,0) AS media_count
            FROM course_reviews r
            JOIN review_categories ximen ON ximen.id=r.category_id
            LEFT JOIN (SELECT review_id, COUNT(*) AS cnt FROM review_media GROUP BY review_id) m ON m.review_id=r.id
            ORDER BY COALESCE(r.event_date, r.created_at) DESC, r.id DESC
            """)
            rows = cur.fetchall()
    conn.close()
    return render_template("admin_reviews.html", cats=cats, rows=rows)

# 新增分類
@app.route("/admin/reviews/categories/new", methods=["POST"])
@admin_required
def admin_create_review_category():
    ensure_review_tables()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("請輸入分類名稱","warning"); return redirect(url_for("admin_reviews"))
    slug = slugify(name)
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO review_categories(name,slug)
                VALUES(%s,%s)
                ON CONFLICT (name) DO NOTHING
                """, (name, slug))
        flash("分類已建立/存在","success")
    except Exception as e:
        flash(f"建立分類失敗：{e}","danger")
    finally:
        conn.close()
    return redirect(url_for("admin_reviews"))

# ---- Jinja 日期格式化濾鏡：strftime / datefmt ----
from datetime import datetime, date

@app.template_filter("strftime")
def jinja_strftime(value, fmt="%Y-%m-%d"):
    """允許在模板用 {{ dt|strftime("%Y-%m-%d") }}。
    支援 datetime/date/ISO 字串；值為空就回空字串。
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    if isinstance(value, date):
        return value.strftime(fmt)
    # 嘗試把字串當 ISO 解析
    try:
        return datetime.fromisoformat(str(value)).strftime(fmt)
    except Exception:
        # 解析不了就原樣輸出（避免再噴錯）
        return str(value)

# 可選別名：{{ dt|datefmt("%Y/%m/%d") }} 也能用
@app.template_filter("datefmt")
def jinja_datefmt(value, fmt="%Y-%m-%d"):
    return jinja_strftime(value, fmt)


# ====== 後台：編輯單篇（含媒體管理） ======
@app.route("/admin/reviews/<int:rid>/edit", methods=["GET","POST"])
@admin_required
def admin_review_edit(rid):
    ensure_review_tables()
    conn = get_db_connection()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category_id = request.form.get("category_id")
        event_date = (request.form.get("event_date") or "").strip() or None
        status = (request.form.get("status") or "published").strip()
        cover = request.files.get("cover")

        if not title or not category_id:
            flash("請填寫標題與分類","warning")
            return redirect(url_for("admin_review_edit", rid=rid))

        cover_path = None
        if cover and cover.filename:
            saved = safe_uuid_filename(cover.filename)
            cover_abs = os.path.join(UPLOAD_FOLDER_REVIEWS, saved)
            cover.save(cover_abs)
            cover_path = f"reviews/{saved}"

        with conn:
            with conn.cursor() as cur:
                if cover_path:
                    cur.execute("""
                    UPDATE course_reviews
                    SET title=%s, category_id=%s, event_date=%s, status=%s, cover_path=%s
                    WHERE id=%s
                    """, (title, category_id, event_date, status, cover_path, rid))
                else:
                    cur.execute("""
                    UPDATE course_reviews
                    SET title=%s, category_id=%s, event_date=%s, status=%s
                    WHERE id=%s
                    """, (title, category_id, event_date, status, rid))
        conn.close()
        flash("已更新","success")
        return redirect(url_for("admin_review_edit", rid=rid))

    # GET：載資料
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT r.*, ximen.name AS category_name
            FROM course_reviews r
            JOIN review_categories ximen ON ximen.id=r.category_id
            WHERE r.id=%s
            """, (rid,))
            review = cur.fetchone()
            if not review:
                flash("找不到回顧","danger")
                return redirect(url_for("admin_reviews"))
            cur.execute("SELECT id,name FROM review_categories ORDER BY sort_order, name;")
            cats = cur.fetchall()
            cur.execute("""
            SELECT id, file_path, file_name, mime, sort_order, created_at
            FROM review_media
            WHERE review_id=%s
            ORDER BY sort_order, created_at, id
            """, (rid,))
            media_list = cur.fetchall()
    conn.close()
    return render_template("admin_review_edit.html", review=review, cats=cats, media_list=media_list)

# 刪除整篇回顧（連帶媒體檔與DB）
@app.route("/admin/reviews/<int:rid>/delete", methods=["POST"])
@admin_required
def admin_review_delete(rid):
    ensure_review_tables()
    # 先把檔案從硬碟移除
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM review_media WHERE review_id=%s", (rid,))
            files = cur.fetchall()
            for f in files:
                rel = (f or {}).get("file_path")
                if rel and rel.startswith("reviews/"):
                    abs_path = os.path.join(BASE_DIR, "uploads", rel.replace("reviews/", f"reviews{os.sep}"))
                    if os.path.isfile(abs_path):
                        try: os.remove(abs_path)
                        except: pass
            # 刪 DB（有 ON DELETE CASCADE）
            cur.execute("DELETE FROM course_reviews WHERE id=%s", (rid,))
    conn.close()
    flash("🗑️ 已刪除回顧與其媒體","success")
    return redirect(url_for("admin_reviews"))

# 單篇後台上傳：支援多檔；圖片自動產 480/960 縮圖 & WEBP
@app.route("/admin/reviews/<int:rid>/media/upload", methods=["POST"])
@admin_required
def admin_upload_review_media(rid: int):
    ensure_review_tables()

    files = request.files.getlist("media") or []
    if not files:
        flash("沒有選擇檔案", "warning")
        return redirect(url_for("admin_review_edit", rid=rid))

    inserted = 0
    with get_db_connection() as conn, conn.cursor() as cur:
        for f in files:
            if not f or not f.filename:
                continue
            if not allowed_ext(f.filename, ALLOWED_MEDIA_EXTS):
                continue

            # 大小限制
            f.stream.seek(0, os.SEEK_END)
            size_bytes = f.stream.tell()
            f.stream.seek(0)
            if size_bytes > MAX_FILE_MB * 1024 * 1024:
                continue

            # 存原檔
            saved = safe_uuid_filename(f.filename)
            orig_path = (Path(UPLOAD_FOLDER_REVIEWS) / saved).resolve()
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            f.save(orig_path)

            file_rel = f"reviews/{orig_path.name}"
            mime = guess_mime(orig_path)
            width = height = None
            rel480 = rel960 = relwebp = None

            # 圖片才做縮圖 / WEBP
            if mime.startswith("image/"):
                try:
                    from PIL import Image
                    with Image.open(orig_path) as img:
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")
                        width, height = img.size

                        # 480 / 960 縮圖（JPG）
                        for w in THUMB_SIZES:
                            thumb = resize_fit_width(img, w)
                            tpath = orig_path.with_name(f"{orig_path.stem}.{w}w.jpg")
                            thumb.save(tpath, "JPEG", quality=JPEG_QUALITY, optimize=True)
                            rel = f"reviews/{tpath.name}"
                            if w == 480: rel480 = rel
                            if w == 960: rel960 = rel

                        # 原尺寸 WEBP
                        webp_path = orig_path.with_suffix(".webp")
                        img.save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
                        relwebp = f"reviews/{webp_path.name}"
                except Exception:
                    # 影像處理失敗就把原檔刪掉，換下一個
                    try:
                        if orig_path.exists(): orig_path.unlink()
                    except:
                        pass
                    continue

            # 寫入 DB（sort_order = 同篇最大+1）
            cur.execute("""
                INSERT INTO review_media
                  (review_id, file_path, file_name, mime, size_bytes,
                   sort_order, created_at, width, height,
                   file_path_480, file_path_960, file_path_webp)
                VALUES
                  (%s, %s, %s, %s, %s,
                   COALESCE((SELECT COALESCE(MAX(sort_order), -1) + 1 FROM review_media WHERE review_id=%s), 0),
                   NOW(), %s, %s, %s, %s, %s)
            """, (
                rid, file_rel, secure_filename(f.filename), mime, size_bytes,
                rid, width, height, rel480, rel960, relwebp
            ))
            inserted += 1

    flash(f"✅ 已上傳 {inserted} 個檔案", "success")
    return redirect(url_for("admin_review_edit", rid=rid))

# 刪除單一媒體（含縮圖/WEBP 檔）
@app.route("/admin/reviews/<int:rid>/media/<int:mid>/delete", methods=["POST"])
@admin_required
def admin_delete_review_media(rid: int, mid: int):
    ensure_review_tables()

    row = None
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, review_id, file_path, file_path_480, file_path_960, file_path_webp
            FROM review_media
            WHERE id=%s AND review_id=%s
        """, (mid, rid))
        row = cur.fetchone()
        if not row:
            flash("找不到檔案", "danger")
            return redirect(url_for("admin_review_edit", rid=rid))

        cur.execute("DELETE FROM review_media WHERE id=%s", (mid,))

    # 刪實體檔（原檔/縮圖/WEBP）
    uploads_root = (Path(BASE_DIR) / "uploads").resolve()
    for key in ("file_path", "file_path_480", "file_path_960", "file_path_webp"):
        rel = row.get(key)
        if not rel:
            continue
        p = (uploads_root / rel).resolve()
        if str(p).startswith(str(uploads_root)) and p.exists():
            try:
                p.unlink()
            except:
                pass

    flash("🗑️ 已刪除媒體", "success")
    return redirect(url_for("admin_review_edit", rid=rid))

# 兼容舊路由（你原本的 /admin/reviews/<rid>/upload）
@app.route("/admin/reviews/<int:rid>/upload", methods=["POST"])
@admin_required
def admin_upload_review_photos(rid):
    # 轉給新的多檔上傳入口
    if not request.files.getlist("media"):
        request.files.setlist("media", request.files.getlist("photos"))
    return admin_upload_review_media(rid)

@app.route("/video")
def legacy_video_redirect():
    return redirect(url_for("reviews"), code=301)

@app.context_processor
def inject_cart_count():
    username = session.get("username")
    if not username: return dict(cart_count=0)

    total = 0
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COALESCE(SUM(quantity), 0) AS total FROM cart_items WHERE user_id = %s", (username,))
        row = cur.fetchone() or {}
        total = row.get("total", 0)
        print("✅ inject_cart_count → user_id =", username, "total =", total)
    except Exception as e:
        print("⚠️ inject_cart_count error:", e)
    finally:
        if conn: conn.close()
    return dict(cart_count=total)

@app.template_filter("filesize")
def filesize_filter(num):
    try:
        num = int(num or 0)
    except (TypeError, ValueError):
        num = 0
    for unit in ["B","KB","MB","GB","TB"]:
        if num < 1024:
            return f"{num:.0f} {unit}" if unit=="B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"



@app.after_request
def add_no_cache_headers(resp):
    ctype = resp.headers.get("Content-Type", "")
    if ctype.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["Vary"] = "Cookie"
    return resp

# ===== 使用者 =====
@app.route("/login", methods=["GET", "POST"])
@nocache
def login():
    if session.get("username"): return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username"); password = request.form.get("password")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone(); conn.close()

        if user and user["password"] == password:
            session["username"] = user["username"]; session["role"] = user["role"]; session.permanent = True
            flash("登入成功"); return redirect(url_for("index"))
        else:
            flash("帳號或密碼錯誤")

    return render_template("login.html")

@app.route("/logout")
@nocache
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
        action = request.form.get("action"); username = request.form.get("username")
        if action == "delete":
            cursor.execute("DELETE FROM users WHERE username = %s", (username,)); flash(f"已刪除帳號：{username}")
        elif action == "toggle_role":
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            current_role = cursor.fetchone()["role"]
            new_role = "admin" if current_role == "member" else "member"
            cursor.execute("UPDATE users SET role = %s WHERE username = %s", (new_role, username))
            flash(f"已將 {username} 的權限更改為 {new_role}")
        conn.commit()
    cursor.execute("SELECT username, role FROM users")
    users = cursor.fetchall(); conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/register", methods=["GET", "POST"])
@nocache
def register():
    if session.get("username"): return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        if not username or not password or not confirm:
            flash("所有欄位都必填"); return render_template("register.html")
        if not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', password):
            flash("密碼須同時包含英文與數字，且長度為 6～15 字"); return render_template("register.html")
        if password != confirm:
            flash("密碼與確認不一致"); return render_template("register.html")

        conn = get_db_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            exists = cur.fetchone()
            if exists:
                flash("帳號已存在"); return render_template("register.html")
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (username, password, "member"))
            conn.commit()
            session["username"] = username; session["role"] = "member"; session.permanent = True
            flash("註冊成功，歡迎加入！"); return redirect(url_for("index"))
        except Exception as e:
            conn.rollback(); flash(f"註冊失敗：{e}"); return render_template("register.html")
        finally:
            conn.close()

    return render_template("register.html")

@app.route("/change_password", methods=["GET", "POST"])
@nocache
def change_password():
    username = session.get("username")
    if not username:
        flash("請先登入"); return redirect(url_for("login"))

    if request.method == "POST":
        old     = request.form.get("old_password", "")
        new     = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if not old or not new or not confirm:
            flash("所有欄位都必填"); return render_template("change_password.html")
        if new != confirm:
            flash("新密碼與確認不一致"); return render_template("change_password.html")
        if not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', new):
            flash("新密碼須同時包含英文與數字，且長度為 6～15 字"); return render_template("change_password.html")

        conn = get_db_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT password FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if not user:
                flash("找不到使用者"); return render_template("change_password.html")
            if user["password"] != old:
                flash("舊密碼錯誤"); return render_template("change_password.html")

            cur.execute("UPDATE users SET password = %s WHERE username = %s", (new, username))
            conn.commit(); session.permanent = True
            flash("密碼已更新"); return redirect(url_for("index"))
        except Exception as e:
            conn.rollback(); flash(f"更新失敗：{e}"); return render_template("change_password.html")
        finally:
            conn.close()

    return render_template("change_password.html")

if __name__ == "__main__":
    app.run(debug=True)
