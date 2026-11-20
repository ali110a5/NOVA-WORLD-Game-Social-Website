
import os
import uuid
import sqlite3
import threading
from datetime import date
from functools import wraps

from flask import (
    Flask, request, redirect, session, flash,
    render_template_string, abort, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.serving import make_server
from PIL import Image
from IPython.display import display, HTML

# ==================================================
# 1. تنظیمات اصلی
# ==================================================

app = Flask("NOVA_WORLD_V3")
app.secret_key = os.environ.get(
    "NOVA_SECRET_KEY", "change-this-secret-before-publication"
)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

DB_NAME = "nova_world_v3.db"
UPLOAD_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def db():
    con = sqlite3.connect(DB_NAME, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


# ==================================================
# 2. ساخت دیتابیس
# ==================================================

def init_db():
    con = db()

    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 100,
        level INTEGER NOT NULL DEFAULT 1,
        is_admin INTEGER NOT NULL DEFAULT 0,
        joined TEXT,
        display_name TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        avatar TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        price INTEGER NOT NULL,
        emoji TEXT DEFAULT '🎁'
    );

    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        equipped INTEGER DEFAULT 0,
        UNIQUE(username, product_id)
    );

    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        product_name TEXT,
        price INTEGER,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        message TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        message TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS quests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        quest_date TEXT,
        quest_name TEXT,
        UNIQUE(username, quest_date, quest_name)
    );

    CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        receiver TEXT,
        status TEXT DEFAULT 'pending',
        UNIQUE(sender, receiver)
    );

    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        content TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER,
        username TEXT,
        UNIQUE(post_id, username)
    );
    """)

    con.executescript("""
    CREATE TABLE IF NOT EXISTS packs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL, description TEXT DEFAULT '',
        price INTEGER NOT NULL, emoji TEXT DEFAULT '🎁'
    );
    CREATE TABLE IF NOT EXISTS pack_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL, pack_id INTEGER NOT NULL,
        UNIQUE(username, pack_id)
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL, username TEXT NOT NULL,
        content TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    post_columns = [r["name"] for r in con.execute("PRAGMA table_info(posts)").fetchall()]
    if "image" not in post_columns:
        con.execute("ALTER TABLE posts ADD COLUMN image TEXT DEFAULT ''")

    products = [
        ("قاب RGB افسانه‌ای", "قاب رنگین‌کمانی ویژه پروفایل", 1800, "🌈"),
        ("قاب آتشین اژدها", "قاب آتشین کمیاب", 2500, "🔥"),
        ("قاب کهکشانی", "قاب فضایی فوق‌العاده کمیاب", 3200, "🌌"),
        ("نشان ستاره طلایی", "نشان ویژه ستاره‌ای", 1400, "⭐"),
        ("نشان الماس", "نشان الماس کمیاب", 2800, "💎"),
        ("نشان افسانه‌ای", "نشان مخصوص افسانه‌ها", 5000, "👑"),
        ("نام نئونی", "نام کاربری نئونی", 1600, "💡"),
        ("نام RGB", "نام رنگین‌کمانی", 3500, "🌈"),
        ("VIP برنزی", "عضویت برنزی", 4200, "🥉"),
        ("VIP طلایی", "عضویت طلایی", 7500, "🥇"),
        ("کوله فضایی", "کوله‌پشتی فضایی", 2200, "🎒"),
        ("بال اژدها", "بال‌های اژدهایی کمیاب", 9000, "🐉")
    ]

    for p in products:
        con.execute("""
            INSERT OR IGNORE INTO products(name,description,price,emoji)
            VALUES(?,?,?,?)
        """, p)

    for p in products:
        con.execute(
            "UPDATE products SET description=?,price=?,emoji=? WHERE name=?",
            (p[1], p[2], p[3], p[0])
        )
    legacy_prices = {
        "قاب RGB": 1800, "قاب آتشین": 2500, "قاب کهکشانی": 3200,
        "نشان ستاره": 1400, "نشان الماس": 2800, "نشان افسانه‌ای": 5000,
        "نام نئونی": 1600, "نام RGB": 3500, "VIP برنزی": 4200,
        "VIP طلایی": 7500, "کوله فضایی": 2200, "بال اژدها": 9000
    }
    for old_name, new_price in legacy_prices.items():
        con.execute("UPDATE products SET price=? WHERE name=?", (new_price, old_name))

    for pack in [
        ("پک نئون", "قاب و نشان نئونی", 1000, "🌈"),
        ("پک جنگجو", "مجموعه ویژه جنگجویان", 2500, "⚔️"),
        ("پک کهکشانی", "آیتم‌های فضایی", 4500, "🌌"),
        ("پک اژدهای افسانه‌ای", "پک بسیار کمیاب اژدها", 7000, "🐉"),
        ("پک پادشاهی NOVA", "بالاترین پک ویژه", 10000, "👑")
    ]:
        con.execute(
            "INSERT OR IGNORE INTO packs(name,description,price,emoji) VALUES(?,?,?,?)",
            pack
        )

    # حساب مدیر
    con.execute("""
        INSERT INTO users
        (username,password,points,level,is_admin,joined)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(username) DO UPDATE SET
        password=excluded.password,
        is_admin=1,
        points=excluded.points,
        level=excluded.level
    """, (
        "ali110a5",
        generate_password_hash("12345678910"),
        999999999999,
        999999999,
        1,
        str(date.today())
    ))

    con.commit()
    con.close()


init_db()


# ==================================================
# 3. توابع کمکی
# ==================================================

def current_user():
    username = session.get("username")
    if not username:
        return None

    con = db()
    user = con.execute(
        "SELECT * FROM users WHERE username=?",
        (username,)
    ).fetchone()
    con.close()
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("ابتدا وارد حساب خودت شو.")
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def notify(username, message, con=None):
    own_connection = con is None
    if own_connection:
        con = db()
    con.execute(
        "INSERT INTO notifications(username,message) VALUES(?,?)",
        (username, message)
    )
    if own_connection:
        con.commit()
        con.close()


def update_level(con, username):
    con.execute("""
        UPDATE users
        SET level=MAX(level, 1 + CAST(points/250 AS INTEGER))
        WHERE username=?
    """, (username,))


# ==================================================
# 4. قالب سایت و ظاهر RGB
# ==================================================

BASE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOVA WORLD</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;background:#080914;color:white;
    font-family:Tahoma,Arial,sans-serif;
}
header{
    padding:25px;text-align:center;
    background:linear-gradient(120deg,#111126,#251044,#101020);
    border-bottom:2px solid #a020f0;
    box-shadow:0 0 20px #8b20ff;
}
header h1{
    margin:0;font-size:35px;
    background:linear-gradient(90deg,red,orange,yellow,lime,cyan,blue,violet);
    color:transparent;background-clip:text;
}
nav{
    display:flex;flex-wrap:wrap;justify-content:center;
    gap:8px;padding:15px;background:#101020;
}
nav a,.btn{
    color:white;text-decoration:none;
    background:#19192e;border:1px solid #8b36ff;
    padding:10px 14px;border-radius:11px;
}
nav a:hover,.btn:hover{
    background:#7020b8;box-shadow:0 0 13px #b000ff;
}
main{max-width:1050px;margin:25px auto;padding:15px}
.card{
    background:#121426;border:1px solid #6031a0;
    padding:20px;border-radius:16px;margin-bottom:16px;
    box-shadow:0 0 12px #37105b;
}
.grid{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
    gap:15px;
}
input,textarea{
    display:block;width:100%;padding:12px;margin:10px 0;
    border-radius:9px;border:1px solid #8c43d9;
    background:#080914;color:white;
}
textarea{min-height:90px}
button{
    background:#7020b8;color:white;border:0;
    border-radius:9px;padding:11px 17px;margin:5px;
    cursor:pointer;
}
button:hover{background:#a020f0}
.price{color:#55ffcb;font-weight:bold}
small{color:#b9a5d8}
footer{text-align:center;padding:30px;color:#aaa}
hr{border-color:#39304c}
.avatar{
    width:140px;height:140px;object-fit:cover;
    border-radius:50%;border:3px solid #c45aff;
    box-shadow:0 0 20px #a020f0;
}
</style>
</head>
<body>
<header>
<h1>🌈 NOVA WORLD 🌈</h1>
<p>دنیای بازی، دوستی و ماجراجویی</p>
</header>
<nav>
<a href="/">خانه</a>
<a href="/profile">پروفایل</a>
<a href="/chat">چت</a>
<a href="/shop">فروشگاه</a>
<a href="/packs">پک‌ها</a>
<a href="/games">بازی‌ها</a>
<a href="/quests">مأموریت‌ها</a>
<a href="/friends">دوستان</a>
<a href="/social">شبکه اجتماعی</a>
<a href="/ranking">رتبه‌بندی</a>
<a href="/notifications">اعلان‌ها</a>
<a href="/settings">تنظیمات</a>
<a href="/admin">مدیریت</a>
<a href="/logout">خروج</a>
</nav>
<main>
{% with msgs=get_flashed_messages() %}
{% for msg in msgs %}
<div class="card">📢 {{msg}}</div>
{% endfor %}
{% endwith %}
{{content|safe}}
</main>
<footer>NOVA WORLD © 2026</footer>
</body>
</html>
"""


def page(content, **data):
    inner = render_template_string(content, **data)
    return render_template_string(BASE, content=inner)


# ==================================================
# 5. صفحه اصلی
# ==================================================

@app.route("/")
def home():
    user = current_user()

    if user:
        welcome = f"""
        <div class="card">
        <h2>خوش آمدی {user['username']}! 🚀</h2>
        <p>امتیاز: {user['points']} | سطح: {user['level']}</p>
        </div>
        """
    else:
        welcome = """
        <div class="card">
        <h2>به NOVA WORLD خوش آمدی!</h2>
        <a class="btn" href="/register">ساخت حساب</a>
        <a class="btn" href="/login">ورود</a>
        </div>
        """

    return page("""
    {{welcome|safe}}
    <div class="grid">
      <div class="card"><h3>🛍 فروشگاه</h3><p>خرید آیتم‌های ویژه</p><a class="btn" href="/shop">ورود</a></div>
      <div class="card"><h3>🎮 بازی‌ها</h3><p>بازی کن و سکه بگیر</p><a class="btn" href="/games">ورود</a></div>
      <div class="card"><h3>💬 چت</h3><p>با کاربران گفتگو کن</p><a class="btn" href="/chat">ورود</a></div>
      <div class="card"><h3>🏆 مأموریت‌ها</h3><p>جایزه روزانه بگیر</p><a class="btn" href="/quests">ورود</a></div>
    </div>
    """, welcome=welcome)


# ==================================================
# 6. ثبت نام و ورود
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not (3 <= len(username) <= 20):
            flash("نام کاربری باید بین ۳ تا ۲۰ حرف باشد.")
        elif not username.replace("_", "").isalnum():
            flash("نام کاربری فقط می‌تواند شامل حروف، عدد و _ باشد.")
        elif len(password) < 6:
            flash("رمز عبور حداقل باید ۶ حرف باشد.")
        else:
            con = db()
            try:
                con.execute("""
                    INSERT INTO users(username,password,joined)
                    VALUES(?,?,?)
                """, (
                    username,
                    generate_password_hash(password),
                    str(date.today())
                ))
                con.commit()
                session["username"] = username
                notify(username, "به NOVA WORLD خوش آمدی!", con)
                con.close()
                return redirect("/")
            except sqlite3.IntegrityError:
                con.close()
                flash("این نام کاربری قبلاً ثبت شده است.")

    return page("""
    <div class="card">
    <h2>📝 ساخت حساب</h2>
    <form method="post">
    <input name="username" placeholder="نام کاربری" required>
    <input name="password" type="password" placeholder="رمز عبور" required>
    <button>ثبت نام</button>
    </form>
    </div>
    """)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        con.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["username"] = username
            return redirect("/")

        flash("نام کاربری یا رمز عبور اشتباه است.")

    return page("""
    <div class="card">
    <h2>🔐 ورود</h2>
    <form method="post">
    <input name="username" placeholder="نام کاربری" required>
    <input name="password" type="password" placeholder="رمز عبور" required>
    <button>ورود</button>
    </form>
    </div>
    """)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ==================================================
# 7. پروفایل و ویرایش عکس
# ==================================================

@app.route("/profile")
@login_required
def profile():
    username = session["username"]
    con = db()

    user = con.execute(
        "SELECT * FROM users WHERE username=?",
        (username,)
    ).fetchone()

    items = con.execute("""
        SELECT p.id,p.name,p.emoji,i.equipped
        FROM inventory i
        JOIN products p ON p.id=i.product_id
        WHERE i.username=?
    """, (username,)).fetchall()

    con.close()

    return page("""
    <div class="card" style="text-align:center">
    {% if user['avatar'] %}
      <img class="avatar" src="/static/uploads/{{user['avatar']}}">
    {% else %}
      <div style="font-size:90px">👤</div>
    {% endif %}
    <h2>{{user['display_name'] or user['username']}}</h2>
    <p>@{{user['username']}}</p>
    <p>{{user['bio'] or 'هنوز توضیحی نوشته نشده است.'}}</p>
    <h3>💰 {% if user['is_admin'] %}∞{% else %}{{user['points']}}{% endif %} سکه</h3>
    <h3>⭐ سطح {% if user['is_admin'] %}∞{% else %}{{user['level']}}{% endif %}</h3>
    </div>

    <div class="card">
    <h2>🖼 تغییر عکس پروفایل</h2>
    <form method="post" action="/profile/avatar" enctype="multipart/form-data">
    <input type="file" name="avatar" accept="image/*" required>
    <button>انتخاب و ذخیره عکس</button>
    </form>
    <small>عکس باید حداکثر ۴ مگابایت باشد.</small>
    </div>

    <div class="card">
    <h2>✏️ ویرایش پروفایل</h2>
    <form method="post" action="/profile/update">
    <input name="display_name" maxlength="30"
    value="{{user['display_name'] or ''}}" placeholder="نام نمایشی">
    <textarea name="bio" maxlength="250"
    placeholder="درباره من">{{user['bio'] or ''}}</textarea>
    <button>ذخیره تغییرات</button>
    </form>
    </div>

    <div class="card">
    <h2>🎒 آیتم‌های من</h2>
    {% for item in items %}
    <p>{{item['emoji']}} {{item['name']}}
    {% if item['equipped'] %}
    <b>فعال است</b>
    {% else %}
    <form method="post" action="/equip/{{item['id']}}">
    <button>استفاده از آیتم</button>
    </form>
    {% endif %}
    </p>
    {% else %}
    <p>هنوز آیتمی نخریده‌ای.</p>
    {% endfor %}
    </div>
    """, user=user, items=items)


@app.route("/profile/avatar", methods=["POST"])
@login_required
def upload_avatar():
    file = request.files.get("avatar")

    if not file or not file.filename:
        flash("یک عکس انتخاب کن.")
        return redirect("/profile")

    try:
        file.stream.seek(0, 2)
        size = file.stream.tell()
        file.stream.seek(0)

        if size > 4 * 1024 * 1024:
            flash("حجم عکس بیشتر از ۴ مگابایت است.")
            return redirect("/profile")

        image = Image.open(file.stream)
        image.verify()

        file.stream.seek(0)
        image = Image.open(file.stream).convert("RGB")
        image.thumbnail((600, 600))

        filename = uuid.uuid4().hex + ".webp"
        filepath = os.path.join(UPLOAD_DIR, filename)
        image.save(filepath, "WEBP", quality=85)

        con = db()
        old = con.execute(
            "SELECT avatar FROM users WHERE username=?",
            (session["username"],)
        ).fetchone()

        con.execute(
            "UPDATE users SET avatar=? WHERE username=?",
            (filename, session["username"])
        )
        con.commit()
        con.close()

        if old and old["avatar"]:
            old_path = os.path.join(UPLOAD_DIR, old["avatar"])
            if os.path.isfile(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        flash("عکس پروفایل تغییر کرد! 🌈")

    except Exception:
        flash("فایل انتخاب‌شده عکس معتبر نیست.")

    return redirect("/profile")


@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    display_name = request.form.get("display_name", "").strip()[:30]
    bio = request.form.get("bio", "").strip()[:250]

    con = db()
    con.execute("""
        UPDATE users SET display_name=?,bio=? WHERE username=?
    """, (display_name, bio, session["username"]))
    con.commit()
    con.close()

    flash("پروفایل ذخیره شد.")
    return redirect("/profile")


# ==================================================
# 8. فروشگاه و خرید
# ==================================================

@app.route("/shop")
@login_required
def shop():
    con = db()
    products = con.execute(
        "SELECT * FROM products ORDER BY price"
    ).fetchall()
    con.close()

    user = current_user()

    return page("""
    <div class="card">
    <h2>🛍 فروشگاه NOVA</h2>
    <h3>موجودی: <span class="price">{% if user['is_admin'] %}∞ سکه{% else %}{{user['points']}} سکه{% endif %}</span></h3>
    </div>

    <div class="grid">
    {% for p in products %}
    <div class="card">
    <h1>{{p['emoji']}}</h1>
    <h3>{{p['name']}}</h3>
    <p>{{p['description']}}</p>
    <p class="price">{{p['price']}} سکه</p>
    <form method="post" action="/buy/{{p['id']}}">
    <button>خرید</button>
    </form>
    </div>
    {% endfor %}
    </div>
    """, products=products, user=user)


@app.route("/buy/<int:product_id>", methods=["POST"])
@login_required
def buy(product_id):
    username = session["username"]
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        product = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not product or not user:
            con.rollback()
            abort(404)
        owned = con.execute("SELECT id FROM inventory WHERE username=? AND product_id=?",
                            (username, product_id)).fetchone()
        if owned:
            flash("این آیتم را قبلاً خریده‌ای.")
            con.rollback()
        elif not user["is_admin"] and user["points"] < product["price"]:
            flash("سکه کافی نداری.")
            con.rollback()
        else:
            if not user["is_admin"]:
                cur = con.execute(
                    "UPDATE users SET points=points-? WHERE username=? AND points>=?",
                    (product["price"], username, product["price"])
                )
                if cur.rowcount != 1:
                    con.rollback()
                    flash("موجودی کافی نیست؛ صفحه را تازه‌سازی کن.")
                    return redirect("/shop")
            con.execute("INSERT INTO inventory(username,product_id) VALUES(?,?)",
                        (username, product_id))
            con.execute("INSERT INTO sales(username,product_name,price) VALUES(?,?,?)",
                        (username, product["name"], product["price"]))
            update_level(con, username)
            notify(username, "خرید موفق: " + product["name"], con)
            con.commit()
            flash("خرید با موفقیت انجام شد! 🎉")
    except sqlite3.IntegrityError:
        con.rollback()
        flash("این آیتم قبلاً به حساب تو اضافه شده است.")
    except Exception:
        con.rollback()
        app.logger.exception("Purchase failed")
        flash("خرید انجام نشد؛ لطفاً دوباره تلاش کن.")
    finally:
        con.close()
    return redirect("/shop")


@app.route("/equip/<int:product_id>", methods=["POST"])
@login_required
def equip(product_id):
    username = session["username"]
    con = db()

    owned = con.execute("""
        SELECT id FROM inventory
        WHERE username=? AND product_id=?
    """, (username, product_id)).fetchone()

    if owned:
        con.execute(
            "UPDATE inventory SET equipped=0 WHERE username=?",
            (username,)
        )
        con.execute("""
            UPDATE inventory SET equipped=1
            WHERE username=? AND product_id=?
        """, (username, product_id))
        flash("آیتم فعال شد!")
    else:
        flash("این آیتم را نخریده‌ای.")

    con.commit()
    con.close()
    return redirect("/profile")

@app.route("/packs")
@login_required
def packs_shop():
    con = db()
    packs = con.execute("SELECT * FROM packs ORDER BY price").fetchall()
    owned = {r["pack_id"] for r in con.execute(
        "SELECT pack_id FROM pack_inventory WHERE username=?", (session["username"],)
    ).fetchall()}
    con.close()
    user = current_user()
    return page("""
    <div class="card"><h2>🎁 فروشگاه پک‌های ویژه</h2>
    <h3>موجودی: {% if user['is_admin'] %}∞{% else %}{{user['points']}}{% endif %} سکه</h3></div>
    <div class="grid">{% for p in packs %}<div class="card">
      <h1>{{p['emoji']}}</h1><h3>{{p['name']}}</h3><p>{{p['description']}}</p>
      <h3 class="price">{{p['price']}} سکه</h3>
      {% if p['id'] in owned %}<b>✅ خریداری شده</b>
      {% else %}<form method="post" action="/pack/buy/{{p['id']}}"><button>خرید پک</button></form>{% endif %}
    </div>{% endfor %}</div>
    """, packs=packs, owned=owned, user=user)


@app.route("/pack/buy/<int:pack_id>", methods=["POST"])
@login_required
def buy_pack(pack_id):
    username = session["username"]
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        pack = con.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not pack or not user:
            con.rollback()
            abort(404)
        owned = con.execute("SELECT id FROM pack_inventory WHERE username=? AND pack_id=?",
                             (username, pack_id)).fetchone()
        if owned:
            flash("این پک را قبلاً خریده‌ای.")
            con.rollback()
        elif not user["is_admin"] and user["points"] < pack["price"]:
            flash("برای خرید این پک سکه کافی نداری.")
            con.rollback()
        else:
            if not user["is_admin"]:
                cur = con.execute("UPDATE users SET points=points-? WHERE username=? AND points>=?",
                                  (pack["price"], username, pack["price"]))
                if cur.rowcount != 1:
                    con.rollback()
                    flash("موجودی کافی نیست.")
                    return redirect("/packs")
            con.execute("INSERT INTO pack_inventory(username,pack_id) VALUES(?,?)",
                        (username, pack_id))
            con.execute("INSERT INTO sales(username,product_name,price) VALUES(?,?,?)",
                        (username, "پک: " + pack["name"], pack["price"]))
            notify(username, "پک " + pack["name"] + " خریداری شد.", con)
            con.commit()
            flash("پک با موفقیت خریداری شد! 🎉")
    except Exception:
        con.rollback()
        app.logger.exception("Pack purchase failed")
        flash("خرید پک انجام نشد.")
    finally:
        con.close()
    return redirect("/packs")


# ==================================================
# 9. مأموریت روزانه و بازی‌ها
# ==================================================

@app.route("/quests")
@login_required
def quests():
    return page("""
    <div class="card">
    <h2>🏆 مأموریت‌های روزانه</h2>
    <p>🎁 جایزه ورود روزانه: ۲۵ سکه</p>
    <form method="post" action="/reward">
    <button>دریافت جایزه روزانه</button>
    </form>
    <hr>
    <p>🎮 بازی کن و از هر بازی روزانه ۵ سکه بگیر.</p>
    <a class="btn" href="/games">رفتن به بازی‌ها</a>
    </div>
    """)


@app.route("/reward", methods=["POST"])
@login_required
def reward():
    username = session["username"]
    today = str(date.today())

    con = db()
    claimed = con.execute("""
        SELECT id FROM quests
        WHERE username=? AND quest_date=? AND quest_name='daily'
    """, (username, today)).fetchone()

    if claimed:
        flash("جایزه امروز را قبلاً گرفته‌ای.")
    else:
        con.execute("""
            INSERT INTO quests(username,quest_date,quest_name)
            VALUES(?,?,?)
        """, (username, today, "daily"))

        con.execute(
            "UPDATE users SET points=points+25 WHERE username=?",
            (username,)
        )
        update_level(con, username)
        con.commit()
        notify(username, "۲۵ سکه جایزه روزانه گرفتی!", con)
        flash("۲۵ سکه دریافت کردی! 🎁")

    con.close()
    return redirect("/quests")


@app.route("/games")
@login_required
def games():
    return page("""
    <h2>🎮 مرکز بازی‌ها</h2>
    <div class="grid">
    <div class="card"><h3>🎯 حدس عدد</h3><a class="btn" href="/game/guess">بازی کن</a></div>
    <div class="card"><h3>⚡ چالش NOVA</h3><a class="btn" href="/game/speed">بازی کن</a></div>
    <div class="card"><h3>🧠 معمای سیاره</h3><a class="btn" href="/game/quiz">بازی کن</a></div>
    <div class="card"><h3>➕ چالش ریاضی</h3><a class="btn" href="/game/math">بازی کن</a></div>
    <div class="card"><h3>🧩 معمای هوش</h3><a class="btn" href="/game/riddle">بازی کن</a></div>
    </div>
    """)


@app.route("/game/<kind>", methods=["GET", "POST"])
@login_required
def game(kind):
    games_data = {
        "guess": ("حدس عدد", "عدد ۲ را حدس بزن.", "2"),
        "speed": ("چالش NOVA", "کلمه NOVA را وارد کن.", "NOVA"),
        "quiz": ("معمای سیاره", "کدام سیاره به سیاره سرخ معروف است؟", "مریخ"),
        "math": ("چالش ریاضی", "حاصل 17 + 25 چند می‌شود؟", "42"),
        "riddle": ("معمای هوش", "آن چیست که دندان دارد اما غذا نمی‌خورد؟", "شانه")
    }

    if kind not in games_data:
        abort(404)

    title, question, answer = games_data[kind]
    result = ""

    if request.method == "POST":
        today = str(date.today())
        quest_name = "game_" + kind
        guess = request.form.get("answer", "").strip()

        con = db()
        claimed = con.execute("""
            SELECT id FROM quests
            WHERE username=? AND quest_date=? AND quest_name=?
        """, (session["username"], today, quest_name)).fetchone()

        if claimed:
            result = "جایزه این بازی را امروز گرفته‌ای."
        elif guess.lower() == answer.lower():
            con.execute("""
                INSERT INTO quests(username,quest_date,quest_name)
                VALUES(?,?,?)
            """, (session["username"], today, quest_name))

            con.execute("""
                UPDATE users SET points=points+5
                WHERE username=?
            """, (session["username"],))

            update_level(con, session["username"])
            con.commit()
            notify(session["username"], "۵ سکه از بازی گرفتی!", con)
            result = "آفرین! ۵ سکه گرفتی! 🎉"
        else:
            result = "جواب اشتباه است. دوباره تلاش کن."

        con.close()

    return page("""
    <div class="card">
    <h2>🎮 {{title}}</h2>
    <p>{{question}}</p>
    <form method="post">
    <input name="answer" placeholder="پاسخ تو" required>
    <button>ثبت پاسخ</button>
    </form>
    <h3>{{result}}</h3>
    <small>جایزه هر بازی: ۵ سکه، روزی یک بار</small>
    </div>
    """, title=title, question=question, result=result)


# ==================================================
# 10. چت عمومی
# ==================================================

@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    username = session["username"]
    con = db()

    if request.method == "POST":
        message = request.form.get("message", "").strip()[:500]
        if message:
            con.execute(
                "INSERT INTO messages(username,message) VALUES(?,?)",
                (username, message)
            )
            con.commit()

    messages = con.execute("""
        SELECT * FROM messages ORDER BY id DESC LIMIT 60
    """).fetchall()

    con.close()

    return page("""
    <div class="card">
    <h2>💬 چت عمومی</h2>
    <form method="post">
    <input name="message" maxlength="500"
    placeholder="پیامت را بنویس..." required>
    <button>ارسال پیام</button>
    </form>
    </div>
    {% for m in messages %}
    <div class="card">
    <b>{{m['username']}}</b>
    <p>{{m['message']}}</p>
    <small>{{m['created']}}</small>
    </div>
    {% endfor %}
    """, messages=messages)


# ==================================================
# 11. دوستان
# ==================================================

@app.route("/friends", methods=["GET", "POST"])
@login_required
def friends():
    username = session["username"]
    con = db()

    if request.method == "POST":
        target = request.form.get("target", "").strip()

        exists = con.execute(
            "SELECT id FROM users WHERE username=?",
            (target,)
        ).fetchone()

        if target == username:
            flash("نمی‌توانی خودت را اضافه کنی.")
        elif not exists:
            flash("کاربر پیدا نشد.")
        else:
            try:
                con.execute(
                    "INSERT INTO friends(sender,receiver) VALUES(?,?)",
                    (username, target)
                )
                con.commit()
                notify(target, username + " درخواست دوستی فرستاد.", con)
                flash("درخواست ارسال شد.")
            except sqlite3.IntegrityError:
                flash("درخواست قبلاً ثبت شده است.")

    incoming = con.execute("""
        SELECT * FROM friends
        WHERE receiver=? AND status='pending'
    """, (username,)).fetchall()

    accepted = con.execute("""
        SELECT sender AS friend FROM friends
        WHERE receiver=? AND status='accepted'
        UNION
        SELECT receiver AS friend FROM friends
        WHERE sender=? AND status='accepted'
    """, (username, username)).fetchall()

    con.close()

    return page("""
    <div class="card">
    <h2>👥 دوستان</h2>
    <form method="post">
    <input name="target" placeholder="نام کاربری دوست" required>
    <button>ارسال درخواست</button>
    </form>
    </div>

    <div class="card">
    <h3>درخواست‌های دریافتی</h3>
    {% for f in incoming %}
    <p>{{f['sender']}}
    <form method="post" action="/friend/accept/{{f['id']}}">
    <button>قبول درخواست</button>
    </form></p>
    {% else %}<p>درخواستی نداری.</p>{% endfor %}
    </div>

    <div class="card">
    <h3>دوستان من</h3>
    {% for f in accepted %}
    <p>👤 {{f['friend']}}</p>
    {% else %}<p>هنوز دوستی نداری.</p>{% endfor %}
    </div>
    """, incoming=incoming, accepted=accepted)


@app.route("/friend/accept/<int:friend_id>", methods=["POST"])
@login_required
def accept_friend(friend_id):
    con = db()
    con.execute("""
        UPDATE friends SET status='accepted'
        WHERE id=? AND receiver=? AND status='pending'
    """, (friend_id, session["username"]))
    con.commit()
    con.close()

    flash("درخواست پذیرفته شد.")
    return redirect("/friends")


# ==================================================
# 12. شبکه اجتماعی و لایک
# ==================================================

@app.route("/social", methods=["GET", "POST"])
@login_required
def social():
    username = session["username"]
    con = db()
    if request.method == "POST":
        content = request.form.get("content", "").strip()[:500]
        photo = request.files.get("photo")
        image_name = ""
        if photo and photo.filename:
            try:
                photo.stream.seek(0, 2)
                size = photo.stream.tell()
                photo.stream.seek(0)
                if size > 4 * 1024 * 1024:
                    flash("حجم عکس باید کمتر از ۴ مگابایت باشد.")
                    return redirect("/social")
                image = Image.open(photo.stream)
                image.verify()
                photo.stream.seek(0)
                image = Image.open(photo.stream).convert("RGB")
                image.thumbnail((1200, 1200))
                image_name = uuid.uuid4().hex + ".webp"
                image.save(os.path.join(UPLOAD_DIR, image_name), "WEBP", quality=85)
            except Exception:
                flash("فایل انتخاب‌شده عکس معتبر نیست.")
                return redirect("/social")
        if content or image_name:
            con.execute("INSERT INTO posts(username,content,image) VALUES(?,?,?)",
                        (username, content, image_name))
            con.commit()
            flash("خبر/پست منتشر شد! 🌟")
        else:
            flash("متن یا عکس برای انتشار وارد کن.")
    posts = con.execute("""
        SELECT posts.*,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id=posts.id) AS likes,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id=posts.id AND likes.username=?) AS liked
        FROM posts ORDER BY id DESC LIMIT 50
    """, (username,)).fetchall()
    comments_by_post = {
        p["id"]: con.execute("SELECT * FROM comments WHERE post_id=? ORDER BY id",
                             (p["id"],)).fetchall()
        for p in posts
    }
    con.close()
    return page("""
    <div class="card"><h2>📰 اخبار و شبکه اجتماعی NOVA</h2>
      <form method="post" enctype="multipart/form-data">
        <textarea name="content" maxlength="500" placeholder="خبر یا پست خودت را بنویس..."></textarea>
        <label>📷 افزودن عکس</label><input type="file" name="photo" accept="image/*">
        <button>🚀 انتشار خبر</button>
      </form>
    </div>
    {% for p in posts %}
    <div class="card">
      <b>👤 {{p['username']}}</b> <small>{{p['created']}}</small>
      {% if p['content'] %}<p>{{p['content']}}</p>{% endif %}
      {% if p['image'] %}<img src="/static/uploads/{{p['image']}}" style="max-width:100%;max-height:420px;border-radius:14px">{% endif %}
      <p>❤️ {{p['likes']}} لایک</p>
      <form method="post" action="/like/{{p['id']}}"><button>{% if p['liked'] %}برداشتن لایک{% else %}❤️ لایک{% endif %}</button></form>
      {% if p['username']==session.get('username') or is_admin %}
      <form method="post" action="/post/delete/{{p['id']}}"><button style="background:#a52a52">🗑 حذف پست</button></form>
      {% endif %}
      <hr><h4>💬 نظرات</h4>
      {% for c in comments_by_post[p['id']] %}
        <p><b>{{c['username']}}</b>: {{c['content']}}</p>
        {% if c['username']==session.get('username') or is_admin %}
        <form method="post" action="/comment/delete/{{c['id']}}"><button>حذف نظر</button></form>
        {% endif %}
      {% else %}<small>هنوز نظری ثبت نشده.</small>{% endfor %}
      <form method="post" action="/comment/{{p['id']}}">
        <input name="content" maxlength="300" placeholder="نظر خودت را بنویس..." required>
        <button>ارسال نظر</button>
      </form>
    </div>
    {% endfor %}
    """, posts=posts, comments_by_post=comments_by_post,
         is_admin=bool(current_user()["is_admin"]))


@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like(post_id):
    con = db()
    post = con.execute(
        "SELECT id FROM posts WHERE id=?",
        (post_id,)
    ).fetchone()

    if post:
        old = con.execute("""
            SELECT id FROM likes WHERE post_id=? AND username=?
        """, (post_id, session["username"])).fetchone()

        if old:
            con.execute("""
                DELETE FROM likes WHERE post_id=? AND username=?
            """, (post_id, session["username"]))
        else:
            con.execute("""
                INSERT INTO likes(post_id,username) VALUES(?,?)
            """, (post_id, session["username"]))

    con.commit()
    con.close()
    return redirect("/social")

@app.route("/post/delete/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    user = current_user()
    con = db()
    post = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if post and (post["username"] == session["username"] or user["is_admin"]):
        con.execute("DELETE FROM likes WHERE post_id=?", (post_id,))
        con.execute("DELETE FROM comments WHERE post_id=?", (post_id,))
        con.execute("DELETE FROM posts WHERE id=?", (post_id,))
        con.commit()
        if post["image"]:
            try: os.remove(os.path.join(UPLOAD_DIR, post["image"]))
            except OSError: pass
        flash("پست حذف شد.")
    else:
        flash("اجازه حذف این پست را نداری.")
    con.close()
    return redirect("/social")


@app.route("/comment/<int:post_id>", methods=["POST"])
@login_required
def add_comment(post_id):
    content = request.form.get("content", "").strip()[:300]
    con = db()
    if content and con.execute("SELECT id FROM posts WHERE id=?", (post_id,)).fetchone():
        con.execute("INSERT INTO comments(post_id,username,content) VALUES(?,?,?)",
                    (post_id, session["username"], content))
        con.commit()
        flash("نظر ثبت شد.")
    con.close()
    return redirect("/social")


@app.route("/comment/delete/<int:comment_id>", methods=["POST"])
@login_required
def delete_comment(comment_id):
    user = current_user()
    con = db()
    comment = con.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if comment and (comment["username"] == session["username"] or user["is_admin"]):
        con.execute("DELETE FROM comments WHERE id=?", (comment_id,))
        con.commit()
        flash("نظر حذف شد.")
    else:
        flash("اجازه حذف این نظر را نداری.")
    con.close()
    return redirect("/social")


# ==================================================
# 13. رتبه‌بندی
# ==================================================

@app.route("/ranking")
def ranking():
    con = db()
    users = con.execute("""
        SELECT username,points,level
        FROM users ORDER BY points DESC LIMIT 50
    """).fetchall()
    con.close()

    return page("""
    <div class="card">
    <h2>🏆 برترین بازیکنان</h2>
    {% for u in users %}
    <p>{{loop.index}}. <b>{{u['username']}}</b>
    — {{u['points']}} سکه — سطح {{u['level']}}</p>
    {% endfor %}
    </div>
    """, users=users)


# ==================================================
# 14. اعلان‌ها
# ==================================================

@app.route("/notifications")
@login_required
def notifications():
    con = db()
    items = con.execute("""
        SELECT * FROM notifications
        WHERE username=? ORDER BY id DESC LIMIT 50
    """, (session["username"],)).fetchall()
    con.close()

    return page("""
    <div class="card">
    <h2>🔔 اعلان‌های من</h2>
    {% for n in items %}
    <p>📢 {{n['message']}} <small>{{n['created']}}</small></p><hr>
    {% else %}<p>اعلانی نداری.</p>{% endfor %}
    </div>
    """, items=items)


# ==================================================
# 15. تنظیمات و تغییر رمز
# ==================================================

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        old = request.form.get("old", "")
        new = request.form.get("new", "")

        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE username=?",
            (session["username"],)
        ).fetchone()

        if not check_password_hash(user["password"], old):
            flash("رمز فعلی اشتباه است.")
        elif len(new) < 6:
            flash("رمز جدید باید حداقل ۶ حرف باشد.")
        else:
            con.execute(
                "UPDATE users SET password=? WHERE username=?",
                (generate_password_hash(new), session["username"])
            )
            con.commit()
            flash("رمز عبور تغییر کرد.")

        con.close()

    return page("""
    <div class="card">
    <h2>⚙️ تنظیمات حساب</h2>
    <form method="post">
    <input type="password" name="old" placeholder="رمز فعلی" required>
    <input type="password" name="new" placeholder="رمز جدید" required>
    <button>ذخیره رمز</button>
    </form>
    </div>
    """)


# ==================================================
# 16. پنل مدیریت و اقتصاد
# ==================================================

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    con = db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "product":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            emoji = request.form.get("emoji", "🎁")[:10]

            try:
                price = int(request.form.get("price", "0"))

                if not name or price < 0:
                    flash("نام محصول یا قیمت نامعتبر است.")
                else:
                    con.execute("""
                        INSERT INTO products(name,description,price,emoji)
                        VALUES(?,?,?,?)
                    """, (name, description, price, emoji))
                    flash("محصول اضافه شد.")

            except ValueError:
                flash("قیمت باید عدد باشد.")
            except sqlite3.IntegrityError:
                flash("نام این محصول قبلاً وجود دارد.")

        elif action == "pack":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            emoji = request.form.get("emoji", "🎁")[:10]
            try:
                price = int(request.form.get("price", "0"))
                if not name or not 1000 <= price <= 10000:
                    flash("قیمت پک باید بین ۱۰۰۰ تا ۱۰۰۰۰ سکه باشد.")
                else:
                    con.execute("INSERT INTO packs(name,description,price,emoji) VALUES(?,?,?,?)",
                                (name, description, price, emoji))
                    flash("پک جدید اضافه شد.")
            except ValueError:
                flash("قیمت پک باید عدد باشد.")
            except sqlite3.IntegrityError:
                flash("نام این پک قبلاً وجود دارد.")

        elif action == "points":
            target = request.form.get("username", "").strip()

            try:
                amount = int(request.form.get("amount", "0"))
                con.execute("""
                    UPDATE users
                    SET points=MAX(0,points+?)
                    WHERE username=?
                """, (amount, target))
                update_level(con, target)
                flash("امتیاز کاربر تغییر کرد.")
                notify(target, "امتیاز حسابت توسط مدیر تغییر کرد.", con)

            except ValueError:
                flash("مقدار امتیاز نامعتبر است.")

        elif action == "delete_message":
            try:
                message_id = int(request.form.get("message_id", "0"))
                con.execute(
                    "DELETE FROM messages WHERE id=?",
                    (message_id,)
                )
                flash("پیام حذف شد.")
            except ValueError:
                flash("شناسه پیام نامعتبر است.")

        con.commit()

    users = con.execute("""
        SELECT username,points,level,is_admin
        FROM users ORDER BY id DESC LIMIT 100
    """).fetchall()

    products = con.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    messages = con.execute("""
        SELECT * FROM messages ORDER BY id DESC LIMIT 30
    """).fetchall()

    con.close()

    return page("""
    <div class="card">
    <h2>👑 پنل مدیریت NOVA</h2>
    <p>مدیر: ali110a5</p>
    <a class="btn" href="/admin/economy">گزارش اقتصاد</a>
    </div>

    <div class="card">
    <h3>➕ افزودن محصول</h3>
    <form method="post">
    <input type="hidden" name="action" value="product">
    <input name="name" placeholder="نام محصول" required>
    <input name="description" placeholder="توضیحات">
    <input name="emoji" placeholder="ایموجی" value="🎁">
    <input name="price" type="number" min="0" placeholder="قیمت" required>
    <button>افزودن محصول</button>
    </form>
    </div>

    <div class="card">
    <h3>🎁 ساخت پک ویژه (۱۰۰۰ تا ۱۰۰۰۰ سکه)</h3>
    <form method="post">
    <input type="hidden" name="action" value="pack">
    <input name="name" placeholder="نام پک" required>
    <input name="description" placeholder="توضیحات پک">
    <input name="emoji" placeholder="ایموجی" value="🎁">
    <input name="price" type="number" min="1000" max="10000" required>
    <button>ساخت پک</button></form>
    <a class="btn" href="/packs">فروشگاه پک‌ها</a>
    </div>
    <div class="card">
    <h3>💰 تغییر امتیاز کاربر</h3>
    <form method="post">
    <input type="hidden" name="action" value="points">
    <input name="username" placeholder="نام کاربری" required>
    <input name="amount" type="number" placeholder="مثلاً 100 یا -50" required>
    <button>اعمال تغییر</button>
    </form>
    </div>

    <div class="card">
    <h3>👥 کاربران</h3>
    {% for u in users %}
    <p>{{u['username']}} | {{u['points']}} سکه | سطح {{u['level']}}
    {% if u['is_admin'] %} 👑 مدیر{% endif %}</p>
    {% endfor %}
    </div>

    <div class="card">
    <h3>🛍 محصولات</h3>
    {% for p in products %}
    <p>{{p['emoji']}} {{p['name']}} — {{p['price']}} سکه</p>
    {% endfor %}
    </div>

    <div class="card">
    <h3>🧹 مدیریت پیام‌ها</h3>
    {% for m in messages %}
    <p>#{{m['id']}} {{m['username']}}: {{m['message']}}</p>
    <form method="post">
    <input type="hidden" name="action" value="delete_message">
    <input type="hidden" name="message_id" value="{{m['id']}}">
    <button>حذف پیام</button>
    </form><hr>
    {% endfor %}
    </div>
    """, users=users, products=products, messages=messages)


@app.route("/admin/economy")
@admin_required
def economy():
    con = db()

    totals = con.execute("""
        SELECT COUNT(*) AS count,
        COALESCE(SUM(price),0) AS revenue
        FROM sales
    """).fetchone()

    popular = con.execute("""
        SELECT product_name,COUNT(*) AS sales,
        COALESCE(SUM(price),0) AS income
        FROM sales
        GROUP BY product_name ORDER BY sales DESC
    """).fetchall()

    con.close()

    return page("""
    <div class="card">
    <h2>📊 گزارش اقتصاد NOVA</h2>
    <h3>💰 مجموع سکه خرج‌شده: {{totals['revenue']}}</h3>
    <h3>🛒 تعداد خریدها: {{totals['count']}}</h3>
    <small>این‌ها آمار اقتصاد مجازی سایت هستند، نه درآمد پول واقعی.</small>
    </div>

    <div class="card">
    <h3>محصولات پرفروش</h3>
    {% for p in popular %}
    <p>{{p['product_name']}} | {{p['sales']}} خرید | {{p['income']}} سکه</p>
    {% else %}
    <p>هنوز خریدی انجام نشده است.</p>
    {% endfor %}
    </div>
    <a class="btn" href="/admin">بازگشت به مدیریت</a>
    """, totals=totals, popular=popular)


# ==================================================
# 17. صفحه سلامت و مدیریت خطا
# ==================================================

@app.route("/health")
def health():
    return "NOVA WORLD OK", 200


@app.errorhandler(404)
def not_found(error):
    return page("""
    <div class="card">
    <h2>🔎 صفحه پیدا نشد</h2>
    <a class="btn" href="/">بازگشت به خانه</a>
    </div>
    """), 404


@app.errorhandler(403)
def forbidden(error):
    return page("""
    <div class="card">
    <h2>⛔ دسترسی غیرمجاز</h2>
    <a class="btn" href="/">بازگشت به خانه</a>
    </div>
    """), 403


@app.errorhandler(413)
def too_large(error):
    return page("""
    <div class="card">
    <h2>حجم فایل زیاد است.</h2>
    <a class="btn" href="/profile">بازگشت به پروفایل</a>
    </div>
    """), 413


# ==================================================
# 18. روشن کردن موتور بدون گیر کردن سلول
# ==================================================

# بستن سرور قبلی همین پروژه، اگر وجود داشته باشد
old_server = globals().get("nova_server")

if old_server is not None:
    try:
        old_server.shutdown()
        old_server.server_close()
    except Exception:
        pass

# پورت جدید برای جلوگیری از تداخل نسخه‌های قبلی
PORT = 5056

nova_server = make_server(
    "127.0.0.1",
    PORT,
    app,
    threaded=True
)

nova_thread = threading.Thread(
    target=nova_server.serve_forever,
    daemon=True
)

nova_thread.start()

print("NOVA WORLD is running!")

display(HTML("""
<div style="
background:#101020;
padding:24px;
border:2px solid #a020f0;
border-radius:18px;
text-align:center;
">
<h1 style="
background:linear-gradient(90deg,red,orange,yellow,lime,cyan,blue,violet);
color:transparent;
background-clip:text;
">🌈 NOVA WORLD ONLINE 🌈</h1>

<a href="http://127.0.0.1:5056"
target="_blank"
style="
display:inline-block;
padding:15px 30px;
border-radius:13px;
background:linear-gradient(90deg,#ff00cc,#3333ff,#00ddaa);
color:white;
text-decoration:none;
font-weight:bold;
">
🚀 ورود به سایت
</a>

<p style="color:#aaa">
موتور سایت در پس‌زمینه اجرا می‌شود.
</p>
</div>
"""))