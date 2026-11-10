# -*- coding: utf-8 -*-
"""数据库层：使用 SQLite 轻量数据库，存放用户、知识库、商品、购物车、咨询、识别记录。"""
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "agri.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    phone TEXT DEFAULT '',
    role TEXT DEFAULT 'user',
    village TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    alias TEXT DEFAULT '',
    category TEXT DEFAULT '粮食作物',
    image TEXT DEFAULT '',
    intro TEXT DEFAULT '',
    regions TEXT DEFAULT '',
    seasons TEXT DEFAULT '',
    habits TEXT DEFAULT '',
    management TEXT DEFAULT '',
    value TEXT DEFAULT '',
    icon TEXT DEFAULT 'leaf',
    signature TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS diseases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    crop_id INTEGER,
    name TEXT NOT NULL,
    dtype TEXT DEFAULT '真菌性病害',
    symptoms TEXT DEFAULT '',
    cause TEXT DEFAULT '',
    peak TEXT DEFAULT '',
    physical TEXT DEFAULT '',
    chemical TEXT DEFAULT '',
    field_mgmt TEXT DEFAULT '',
    prevention TEXT DEFAULT '',
    icon TEXT DEFAULT 'bug',
    signature TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT '时令果蔬',
    origin TEXT DEFAULT '',
    price REAL NOT NULL DEFAULT 0,
    unit TEXT DEFAULT '斤',
    stock INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    image TEXT DEFAULT '',
    icon TEXT DEFAULT 'basket',
    farmer_id INTEGER,
    farmer_name TEXT DEFAULT '',
    status TEXT DEFAULT 'approved',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    qty INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    product_name TEXT DEFAULT '',
    name TEXT NOT NULL,
    contact TEXT DEFAULT '',
    content TEXT NOT NULL,
    reply TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT UNIQUE NOT NULL,
    user_key TEXT NOT NULL,
    buyer TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT DEFAULT '',
    total REAL NOT NULL,
    items TEXT NOT NULL,
    status TEXT DEFAULT '待农户联系',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key TEXT DEFAULT '',
    kind TEXT NOT NULL,
    image TEXT DEFAULT '',
    result_name TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


PRODUCT_IMAGES = {
    "五常稻花香大米": "img/products/rice.jpg",
    "有机石磨全麦粉": "img/products/flour.jpg",
    "东北黑玉米（鲜食）": "img/products/maize.jpg",
    "普罗旺斯沙瓤番茄": "img/products/tomato.jpg",
    "旱地小黄瓜": "img/products/cucumber.jpg",
    "高原黄心马铃薯": "img/products/potato.jpg",
    "洛川红富士苹果": "img/products/apple.jpg",
    "赣南脐橙": "img/products/citrus.jpg",
    "阳光玫瑰葡萄": "img/products/grape.jpg",
    "丹东红颜草莓": "img/products/strawberry.jpg",
    "遵义朝天椒（干椒）": "img/products/pepper.jpg",
    "明前龙井绿茶": "img/products/tea.jpg",
    "非转基因黄豆": "img/products/soybean.jpg",
    "三峡农家土蜂蜜": "img/products/honey.jpg",
}


def _core_ready(conn):
    """核心表是否都已存在且有数据（存在则跳过整篇建表脚本，加快启动）。"""
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        have = {r[0] for r in rows}
        return {"crops", "diseases", "products", "users"}.issubset(have)
    except Exception:
        return False


def init_db():
    """建表并写入初始知识库数据（已就绪时只做增量自愈，避免每次重复建表）。"""
    conn = get_conn()
    if not _core_ready(conn):
        conn.executescript(SCHEMA)
        conn.commit()
    _fix_crop_images(conn)
    conn.commit()
    conn.close()
    _seed(conn=None)
    _ensure_product_images()
    _ensure_ai_diseases()


def _ensure_ai_diseases():
    """自愈：把 AI 模型新增的病害条目补进已有数据库（幂等，按 slug 去重）。

    老库升级时不会清空业务数据，只追加缺失的知识库条目，
    保证模型识别出来的病害都能查到对应的防治方案。
    """
    try:
        from seed_data_ai import AI_DISEASES
        conn = get_conn()
        have = {r[0] for r in conn.execute("SELECT slug FROM diseases")}
        added = 0
        keys = ["slug", "name", "dtype", "symptoms", "cause", "peak", "physical",
                "chemical", "field_mgmt", "prevention", "icon", "signature"]
        for d in AI_DISEASES:
            if d["slug"] in have:
                continue
            crop = conn.execute("SELECT id FROM crops WHERE slug=?", [d["crop"]]).fetchone()
            row = [d["slug"], crop["id"] if crop else None] + [d.get(k, "") for k in keys[1:]]
            conn.execute(
                "INSERT INTO diseases(slug,crop_id,name,dtype,symptoms,cause,peak,physical,"
                "chemical,field_mgmt,prevention,icon,signature) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row)
            added += 1
        conn.commit()
        conn.close()
        if added:
            print("[db] 已补充 AI 病害知识条目 %d 条" % added)
    except Exception as e:
        print("[db] 补充 AI 病害条目跳过：%s" % e)


def _fix_crop_images(conn):
    """自愈：番茄/黄瓜科普图历史文件名内容互换，统一指向正确图片（幂等）。
    写库失败（如库文件临时只读）时静默跳过，不阻塞服务启动。"""
    fixes = {"tomato": "img/crops/tomato2.jpg", "cucumber": "img/crops/cucumber2.jpg"}
    try:
        for slug, img in fixes.items():
            row = conn.execute("SELECT image FROM crops WHERE slug=?", (slug,)).fetchone()
            if row and row[0] == img:
                continue          # 已是正确值，跳过写入
            conn.execute("UPDATE crops SET image=? WHERE slug=?", (img, slug))
    except Exception:
        pass


def _ensure_product_images():
    """自愈：为商城商品补齐实拍图（幂等）。
    老库没有 image 列时自动加列，再按商品名写入对应图片路径。
    写库失败（库文件只读）时静默跳过，不阻塞服务启动。"""
    try:
        conn = get_conn()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
        if "image" not in cols:
            # 老库未升级：页面由 product_image() 按商品名兜底显示，不强制改表
            conn.close()
            return
        for name, img in PRODUCT_IMAGES.items():
            conn.execute("UPDATE products SET image=? WHERE name=? AND (image IS NULL OR image='')",
                         (img, name))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _seed(conn=None):
    from seed_data import CROPS, DISEASES, PRODUCTS, USERS
    own = conn is None
    if own:
        conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if conn.execute("SELECT COUNT(*) c FROM crops").fetchone()["c"] == 0:
        for c in CROPS:
            conn.execute(
                """INSERT INTO crops(slug,name,image,alias,category,intro,regions,seasons,habits,
                   management,value,icon,signature) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [c["slug"], c["name"], c.get("image", ""), c["alias"], c["category"], c["intro"], c["regions"],
                 c["seasons"], c["habits"], c["management"], c["value"], c.get("icon", "leaf"),
                 c.get("signature", "{}")],
            )
    if conn.execute("SELECT COUNT(*) c FROM diseases").fetchone()["c"] == 0:
        for d in DISEASES:
            crop = conn.execute("SELECT id FROM crops WHERE slug=?", [d["crop"]]).fetchone()
            conn.execute(
                """INSERT INTO diseases(slug,crop_id,name,dtype,symptoms,cause,peak,physical,
                   chemical,field_mgmt,prevention,icon,signature)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [d["slug"], crop["id"] if crop else None, d["name"], d["dtype"], d["symptoms"],
                 d["cause"], d["peak"], d["physical"], d["chemical"], d["field_mgmt"],
                 d["prevention"], d.get("icon", "bug"), d.get("signature", "{}")],
            )
    if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
        for p in PRODUCTS:
            conn.execute(
                """INSERT INTO products(name,category,origin,price,unit,stock,description,image,icon,
                   farmer_name,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                [p["name"], p["category"], p["origin"], p["price"], p["unit"], p["stock"],
                 p["description"], p.get("image") or PRODUCT_IMAGES.get(p["name"], ""),
                 p.get("icon", "basket"),
                 p.get("farmer_name", "平台直供"),
                 "approved", now],
            )
    if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        from werkzeug.security import generate_password_hash
        for u in USERS:
            conn.execute(
                "INSERT OR IGNORE INTO users(username,password_hash,phone,role,village,created_at)"
                " VALUES(?,?,?,?,?,?)",
                [u["username"], generate_password_hash(u["password"]), u.get("phone", ""),
                 u.get("role", "user"), u.get("village", ""), now],
            )
    conn.commit()
    if own:
        conn.close()


def query(sql, args=(), one=False):
    conn = get_conn()
    try:
        cur = conn.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
        conn.commit()
        return rows[0] if (one and rows) else rows
    finally:
        conn.close()


def execute(sql, args=()):
    conn = get_conn()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成：", DB_PATH)
