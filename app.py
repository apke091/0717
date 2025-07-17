from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import re
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# 🔹 JSON 登入系統
def load_users():
    with open("users.json", "r") as f:
        return json.load(f)

def save_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)
# 🔹 JSON 購物車系統
def load_products():
    with open("products.json", "r", encoding="utf-8") as f:
        return json.load(f)

# 🔒 限管理員使用
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            flash("您沒有權限執行此操作")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# 🏠 首頁
@app.route("/")
def index():
    return render_template("index.html")

# 🧾 額外頁面
@app.route("/about")
def about():
    return render_template("about.html")
# @app.route("/test")
# def test():
#     return render_template("test.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/download")
def download():
    return render_template("download.html")

@app.route("/news")
def news():
    return render_template("news.html")

@app.route("/rent")
def rent():
    return render_template("rent.html")

@app.route("/shop")
def shop():
    products = load_products()
    return render_template("shop.html", products=products)

#加入購物車
@app.route("/add_to_cart/<pid>")
def add_to_cart(pid):
    products = load_products()
    if pid not in products:
        flash("商品不存在")
        return redirect(url_for("shop"))

    cart = session.get("cart", {})
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    flash("已加入購物車")
    return redirect(url_for("shop"))

#購物車
@app.route("/cart")
def cart():
    if not session.get("username"):
        flash("請先登入才能查看購物車")
        return redirect(url_for("login"))
    products = load_products()
    cart = session.get("cart", {})
    items = []
    total = 0
    for pid, qty in cart.items():
        product = products.get(pid)
        if product:
            subtotal = product["price"] * qty
            items.append({
                "id": pid,
                "name": product["name"],
                "price": product["price"],
                "qty": qty,
                "subtotal": subtotal
            })
            total += subtotal
    return render_template("cart.html", items=items, total=total)

#移除購物車內容
@app.route("/remove_from_cart/<pid>")
def remove_from_cart(pid):
    cart = session.get("cart", {})
    if pid in cart:
        del cart[pid]
        session["cart"] = cart
        flash("已從購物車移除")
    return redirect(url_for("cart"))

# 管理商品列表
@app.route("/manage_products", methods=["GET", "POST"])
@admin_required
def manage_products():
    products = load_products()

    if request.method == "POST":
        pid = request.form.get("pid")
        name = request.form.get("name")
        price = request.form.get("price")

        if not pid or not name or not price:
            flash("請填寫所有欄位")
        elif pid in products:
            flash("商品 ID 已存在")
        else:
            products[pid] = {"name": name, "price": int(price)}
            with open("products.json", "w", encoding="utf-8") as f:
                json.dump(products, f, indent=2, ensure_ascii=False)
            flash("✅ 商品新增成功")
            return redirect(url_for("manage_products"))

    return render_template("manage_products.html", products=products)

@app.route("/delete_product/<pid>", methods=["POST"])
@admin_required
def delete_product(pid):
    products = load_products()
    if pid in products:
        del products[pid]
        with open("products.json", "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
        flash("🗑️ 商品已刪除")
    return redirect(url_for("manage_products"))

#購物車數量
@app.context_processor
def inject_cart_count():
    cart = session.get("cart", {})
    count = sum(cart.values())
    return dict(cart_count=count)

# 🔐 登入
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        users = load_users()
        user = users.get(username)

        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            flash("登入成功")
            return redirect(url_for("index"))
        else:
            flash("帳號或密碼錯誤")
    return render_template("login.html")

# 🚪 登出
@app.route("/logout")
def logout():
    cart = session.get("cart")  # 先記住購物車
    session.clear()
    session["cart"] = cart      # 登出後再放回去
    flash("已登出")
    return redirect(url_for("login"))
#註冊
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm")

        users = load_users()

        if username in users:
            flash("帳號已存在")
        elif password != confirm:
            flash("密碼與確認不一致")
        elif not re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', password):
            flash("密碼須含英文與數字，且長度為 6～15 字")
        else:
            users[username] = {"password": password, "role": "member"}
            save_users(users)
            session["username"] = username
            session["role"] = "member"
            flash("註冊成功，歡迎加入！")
            return redirect(url_for("index"))

    return render_template("register.html")


# 🛠️ 修改密碼
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    username = session.get("username")
    if not username:
        flash("請先登入")
        return redirect(url_for("login"))

    users = load_users()

    if request.method == "POST":
        old = request.form.get("old_password")
        new = request.form.get("new_password")
        confirm = request.form.get("confirm_password")

        # 檢查舊密碼正確性
        if users[username]["password"] != old:
            flash("舊密碼錯誤")

        # 確認新密碼一致
        elif new != confirm:
            flash("新密碼與確認不一致")

        # ✅ 加入密碼格式限制
        elif not re.fullmatch(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,15}$', new):
            flash("新密碼須包含英文與數字，且長度為 6～15 字")

        else:
            users[username]["password"] = new
            save_users(users)
            flash("密碼已更新")
            return redirect(url_for("index"))

    return render_template("change_password.html")

# ⬆️ 上傳影片（限 admin）
@app.route("/upload", methods=["GET", "POST"])
@admin_required
def upload_video():
    video_folder = os.path.join(app.static_folder, "videos")
    os.makedirs(video_folder, exist_ok=True)

    if request.method == "POST":
        file = request.files.get("video")
        if file and file.filename.endswith(".mp4"):
            file.save(os.path.join(video_folder, file.filename))
            flash("影片上傳成功！")
            return redirect(url_for("upload_video"))
        else:
            flash("請選擇 mp4 檔案")
            return redirect(request.url)

    videos = [f for f in os.listdir(video_folder) if f.endswith(".mp4")]
    return render_template("upload.html", videos=videos)

# ❌ 刪除影片（限 admin）
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

# 🎬 公開影音專區
@app.route("/video")
def video_gallery():
    folder = os.path.join(app.static_folder, "videos")
    os.makedirs(folder, exist_ok=True)
    videos = [f for f in os.listdir(folder) if f.endswith(".mp4")]
    return render_template("video.html", videos=videos)

# ✅ 啟動
if __name__ == "__main__":
    app.run(debug=True)
