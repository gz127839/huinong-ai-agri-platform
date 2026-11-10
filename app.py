# -*- coding: utf-8 -*-
"""智慧农业助农服务平台 —— Flask 主程序。

模块划分：
    db.py        数据库与初始化
    vision.py    图像特征引擎（降级兜底）
    ai_engine.py 深度模型识别引擎（MobileNetV2 迁移学习，主力）
    ai_labels.py 模型标签 -> 中文 / 知识库映射
    seed_data.py 知识库与商品初始数据
    app.py       路由与业务逻辑
"""
import json
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
import ai_engine
import ai_labels
import ai_assistant
import agri_agent
import species_engine
from vision import describe, extract_features, match_crop, match_disease

# AI 模型实际支持的作物（来自训练数据集）
AI_CROPS_CN = "、".join(sorted(set(ai_labels.CROP_CN.values())))


def kb_only_crops():
    """知识库已收录、但模型没有训练样本的作物（差异范围提示用）。

    平台科普库收录 15 种作物，而病害模型的训练数据（PlantVillage 5 万张叶片）
    只覆盖其中一部分，水稻、小麦、黄瓜等国内主要作物并没有公开可用的标注样本集，
    这部分作物只提供科普与病害知识，不做图像诊断——提示里必须说清楚，避免误导。
    """
    try:
        covered = set(ai_labels.CROP_TO_SLUG.values())
        rows = db.query("SELECT name, slug FROM crops ORDER BY id")
        return [r["name"] for r in rows if r["slug"] not in covered]
    except Exception:
        return []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED = {"jpg", "jpeg", "png", "bmp", "webp", "gif"}
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "smart-agri-2026-secret-key")
# 改完模板不必重启服务也能生效
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

CATEGORIES = ["时令果蔬", "粮油米面", "茶叶饮品", "调味干货", "禽蛋肉制品", "农资种苗"]


# ---------------- 通用工具 ---------------- #

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def cart_key():
    """登录用户按用户 ID 存购物车，游客按会话 ID 存，登录后自动合并。"""
    if "user_id" in session:
        return "u:%d" % session["user_id"]
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex[:16]
    return "s:" + session["sid"]


def current_user():
    if "user_id" not in session:
        return None
    return db.query("SELECT * FROM users WHERE id=?", [session["user_id"]], one=True)


def login_required(f):
    @wraps(f)
    def inner(*a, **kw):
        if "user_id" not in session:
            flash("请先登录后再操作", "warn")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return inner


def admin_required(f):
    @wraps(f)
    def inner(*a, **kw):
        u = current_user()
        if not u or u["role"] != "admin":
            flash("需要管理员权限", "warn")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return inner


# ---------------- 登录墙：进站先登录，登录后才能使用站内功能 ---------------- #
# 开场动画在 base.html 里播放；未登录访问任意页面都会被拦到登录页，
# 于是"动画播完 → 停在登录/注册界面"是自然结果，不需要额外的欢迎跳转页。
PUBLIC_ENDPOINTS = {"login", "register", "logout", "static"}


@app.before_request
def auth_gate():
    if "user_id" in session:
        return None
    if (request.endpoint or "") in PUBLIC_ENDPOINTS:
        return None
    # 兜底：端点名取不到（如 404）时按路径判断，别把登录页自己拦掉
    if request.path.startswith("/login") or request.path.startswith("/register"):
        return None
    target = request.full_path if request.args else request.path
    # 接口类请求返回 401，避免前端 fetch 收到一整张登录页 HTML
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "请先登录后再调用该接口"}), 401
    flash("请先登录后再使用平台功能", "warn")
    return redirect(url_for("login", next=target))


def save_upload(file):
    """保存上传图片，返回相对 URL；失败返回 None。"""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED:
        return None
    name = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:8] + "." + ext
    file.save(os.path.join(UPLOAD_DIR, name))
    return url_for("static", filename="uploads/" + name)


def cart_count():
    row = db.query("SELECT COALESCE(SUM(qty),0) c FROM cart_items WHERE user_key=?",
                   [cart_key()], one=True)
    return row["c"] if row else 0


def product_image(name, cur=None):
    """商品图：优先用库中 image，缺失时按商品名回退到内置实拍图。"""
    return cur or db.PRODUCT_IMAGES.get(name, "")


def asset(filename):
    """静态资源 URL，自动带上文件修改时间作为版本号（防浏览器缓存旧图）。"""
    path = os.path.join(BASE_DIR, "static", filename.replace("/", os.sep))
    try:
        ver = int(os.path.getmtime(path))
    except OSError:
        ver = 0
    return url_for("static", filename=filename) + "?v=%d" % ver


app.jinja_env.globals.update(
    cart_count=cart_count,
    current_user=current_user,
    current_year=datetime.now().year,
    product_image=product_image,
    asset=asset,
)


@app.after_request
def no_stale_cache(resp):
    """页面不缓存，静态资源需重新校验：保证改完图片立刻生效。"""
    if "text/html" in (resp.headers.get("Content-Type") or ""):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    else:
        resp.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return resp


# ---------------- AI 能力实验室（模型评测与对比） ---------------- #

BENCHMARK = os.path.join(BASE_DIR, "ai_model", "benchmark.json")


@app.route("/ai-lab")
def ai_lab():
    bench = {}
    if os.path.exists(BENCHMARK):
        try:
            with open(BENCHMARK, encoding="utf-8") as fh:
                bench = json.load(fh)
        except Exception:
            bench = {}
    sp = species_engine.status() if species_engine.available() else {}
    return render_template("ai_lab.html", bench=bench, status=ai_engine.status(),
                           species=sp,
                           ai_model_crops=AI_CROPS_CN, kb_only=kb_only_crops())


# ---------------- 农技问答助手（LLM + RAG，可选） ---------------- #

@app.route("/assistant", methods=["GET", "POST"])
def assistant():
    question = (request.form.get("question") or request.args.get("q") or "").strip()
    result = None
    if question:
        refs = ai_assistant.retrieve(db, question)
        if ai_assistant.enabled():
            try:
                result = {"ok": True, "answer": ai_assistant.answer(question, refs),
                          "refs": refs, "mode": "llm"}
            except Exception as e:
                result = {"ok": True, "answer": None, "refs": refs, "mode": "llm",
                          "error": "AI 接口暂时不可用（%s），以下为知识库检索结果。" % e.__class__.__name__}
        else:
            result = {"ok": True, "answer": None, "refs": refs, "mode": "kb",
                      "error": None}
    kb_count = (db.query("SELECT COUNT(*) c FROM crops", one=True)["c"]
                + db.query("SELECT COUNT(*) c FROM diseases", one=True)["c"])
    return render_template("assistant.html", question=question, result=result,
                           llm_enabled=ai_assistant.enabled(),
                           llm_model=ai_assistant.llm_model(),
                           llm_label=ai_assistant.llm_label(),
                           refs_count=kb_count)


# ---------------- 农业智能体（规划 → 调工具 → 观察 → 汇总） ---------------- #

@app.route("/agent", methods=["GET", "POST"])
def agent():
    question = (request.form.get("question") or request.args.get("q") or "").strip()
    result = None
    image_url = None
    if request.method == "POST" and (question or request.files.get("image")):
        path = None
        url = save_upload(request.files.get("image"))
        if url:
            image_url = url
            path = os.path.join(BASE_DIR, "static", "uploads", os.path.basename(url))
        # 多轮记忆：只保留最近 3 轮问答摘要，避免会话 cookie 膨胀
        history = session.get("agent_hist") or []
        result = agri_agent.run(db, question, image_path=path, history=history)
        if question and result.get("answer"):
            history.append({"q": question, "a": result["answer"][:300]})
            session["agent_hist"] = history[-3:]
            session.modified = True
    return render_template("agent.html", question=question, result=result,
                           image=image_url, llm_enabled=agri_agent.llm_enabled(),
                           llm_model=agri_agent.llm_model(),
                           llm_label=agri_agent.llm_label(),
                           tools=agri_agent.tool_catalog())


@app.route("/api/agent", methods=["POST"])
def api_agent():
    """智能体 JSON 接口（便于外部调用 / 演示自动化）。"""
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    path = data.get("image_path")
    if path and not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    res = agri_agent.run(db, question, image_path=path)
    return jsonify(res)


# ---------------- 首页 ---------------- #

@app.route("/")
def index():
    crops = db.query("SELECT * FROM crops ORDER BY id LIMIT 8")
    diseases = db.query("SELECT d.*, c.name crop_name FROM diseases d "
                        "LEFT JOIN crops c ON c.id=d.crop_id ORDER BY d.id LIMIT 6")
    products = db.query("SELECT * FROM products WHERE status='approved' ORDER BY id DESC LIMIT 4")
    stats = {
        "crops": db.query("SELECT COUNT(*) c FROM crops", one=True)["c"],
        "diseases": db.query("SELECT COUNT(*) c FROM diseases", one=True)["c"],
        "products": db.query("SELECT COUNT(*) c FROM products WHERE status='approved'", one=True)["c"],
        "scans": db.query("SELECT COUNT(*) c FROM history", one=True)["c"],
    }
    return render_template("index.html", crops=crops, diseases=diseases,
                           products=products, stats=stats)


# ---------------- 作物识别 ---------------- #

@app.route("/crop-recognize", methods=["GET", "POST"])
def crop_recognize():
    result = None
    if request.method == "POST":
        file = request.files.get("image")
        url = save_upload(file)
        if not url:
            flash("请上传 jpg / png 格式的图片（小于 8MB）", "warn")
            return redirect(url_for("crop_recognize"))
        crops = db.query("SELECT * FROM crops")
        path = os.path.join(BASE_DIR, "static", "uploads", os.path.basename(url))
        feat = extract_features(path)
        feat["_path"] = path
        ai = ai_engine.analyze(path, explain=True)
        crop = None
        conf = 0.0
        alts = []
        if ai.get("ok") and ai.get("crop"):
            slug = ai["crop"].get("slug")
            if slug:
                crop = db.query("SELECT * FROM crops WHERE slug=?", [slug], one=True)
            conf = ai["crop"]["conf"]
            for a in ai.get("crop_top", [])[1:]:
                if a.get("slug"):
                    row = db.query("SELECT name,slug FROM crops WHERE slug=?", [a["slug"]], one=True)
                    if row:
                        alts.append({"name": row["name"], "slug": row["slug"],
                                     "confidence": a["conf"]})
        # 只有真模型不可用时才回退旧引擎。
        # 注意：模型可用但判出的作物不在科普库里（如南瓜）时，绝不能让旧引擎接手——
        # 旧引擎是手工颜色特征匹配，会把图强行匹配成库里某个作物（实测把黄瓜判成小麦）。
        if crop is None and not ai.get("ok"):
            matched = match_crop(feat, crops)
            if matched:
                top, conf = matched[0]
                crop = top
                alts = [{"name": c["name"], "slug": c["slug"], "confidence": cf}
                        for c, cf in matched[1:]]
        # 叶片病害模型拒识时（田间实景照 / 果实照 / 未收录作物），
        # 改用作物物种识别通道的结论——它覆盖知识库全部 14 种作物。
        sp_used = None
        if crop is None and isinstance(ai, dict):
            sp = ai.get("species") or {}
            if sp.get("ok") and sp.get("known"):
                row = db.query("SELECT * FROM crops WHERE slug=?", [sp["slug"]], one=True)
                if row:
                    crop = row
                    conf = round(float(sp.get("conf_pct", 0)), 1)
                    alts = [{"name": t["cn"], "slug": t["slug"], "confidence": t["conf"]}
                            for t in sp.get("top", [])[1:]
                            if db.query("SELECT id FROM crops WHERE slug=?", [t["slug"]], one=True)]
                    sp_used = sp
        if crop:
            db.execute("INSERT INTO history(user_key,kind,image,result_name,confidence,created_at)"
                       " VALUES(?,?,?,?,?,?)",
                       [cart_key(), "crop", url, crop["name"], conf, now()])
            result = {"crop": crop, "confidence": conf, "image": url,
                      "alts": alts, "analysis": describe(feat), "ai": ai,
                      "species": sp_used}
        else:
            result = {"image": url, "analysis": describe(feat), "ai": ai,
                      "aux": (ai.get("aux") if isinstance(ai, dict) else None),
                      "species": (ai.get("species") if isinstance(ai, dict) else None)}
    crops = db.query("SELECT id,name,slug,category FROM crops ORDER BY id")
    return render_template("crop_recognize.html", crops=crops, result=result,
                           ai_crops=AI_CROPS_CN, kb_only=kb_only_crops())


# ---------------- 病虫害识别 ---------------- #

@app.route("/disease-recognize", methods=["GET", "POST"])
def disease_recognize():
    result = None
    if request.method == "POST":
        file = request.files.get("image")
        crop_id = request.form.get("crop_id", type=int)
        url = save_upload(file)
        if not url:
            flash("请上传 jpg / png 格式的图片（小于 8MB）", "warn")
            return redirect(url_for("disease_recognize"))
        diseases = db.query("SELECT * FROM diseases")
        path = os.path.join(BASE_DIR, "static", "uploads", os.path.basename(url))
        feat = extract_features(path)
        feat["_path"] = path
        ai = ai_engine.analyze(path, crop_hint=crop_id, explain=True)
        healthy, disease, crop, conf, alts = False, None, None, 0.0, []

        if ai.get("ok") and not ai.get("known", True):
            # 开放集检测拒绝：图片不属于已支持的作物，不给病害结论
            healthy = False
            conf = 0.0
        elif ai.get("ok"):
            healthy = bool(ai.get("healthy"))
            conf = ai.get("health_conf", 0.0) if healthy else ai["fine"]["conf"]
            if not healthy:
                slug = ai["fine"].get("slug")
                if slug:
                    disease = db.query("SELECT * FROM diseases WHERE slug=?", [slug], one=True)
                cslug = ai["fine"].get("crop_slug")
                if cslug:
                    crop = db.query("SELECT * FROM crops WHERE slug=?", [cslug], one=True)
                for a in ai.get("top", [])[1:]:
                    if a.get("slug"):
                        alts.append({"name": a["cn"], "slug": a["slug"], "confidence": a["conf"]})
        else:  # 模型不可用时回退旧引擎
            matched, healthy = match_disease(feat, diseases, crop_id)
            if matched:
                top, conf = matched[0]
                disease = top
                crop = db.query("SELECT * FROM crops WHERE id=?", [top["crop_id"]], one=True)
                alts = [{"name": d["name"], "slug": d["slug"], "confidence": cf}
                        for d, cf in matched[1:]]

        if crop is None and crop_id:
            crop = db.query("SELECT * FROM crops WHERE id=?", [crop_id], one=True)

        if healthy:
            db.execute("INSERT INTO history(user_key,kind,image,result_name,confidence,created_at)"
                       " VALUES(?,?,?,?,?,?)",
                       [cart_key(), "disease", url, "未见明显病斑", conf or 92.0, now()])
            result = {"healthy": True, "image": url, "crop": crop, "confidence": conf or 92.0,
                      "analysis": describe(feat), "ai": ai}
        else:
            fine = (ai.get("fine") or {}) if isinstance(ai, dict) else {}
            aux = (ai.get("aux") if isinstance(ai, dict) else None) or None
            sp = (ai.get("species") if isinstance(ai, dict) else None) or None
            name = disease["name"] if disease else fine.get("cn", "未知")
            if ai.get("ok") and not ai.get("known", True):
                name = aux["name"] if aux else "暂不支持该作物"
                # 物种识别通道命中：即便做不了病害诊断，也要说出"这是什么作物"
                if sp and sp.get("ok") and sp.get("known"):
                    name = sp["cn"]
                    row = db.query("SELECT * FROM crops WHERE slug=?", [sp["slug"]], one=True)
                    if row:
                        crop = row
                        crop_id = crop["id"]
                    conf = round(float(sp.get("conf_pct", 0)), 1)
            db.execute("INSERT INTO history(user_key,kind,image,result_name,confidence,created_at)"
                       " VALUES(?,?,?,?,?,?)",
                       [cart_key(), "disease", url, name, conf, now()])
            result = {"disease": disease, "crop": crop, "confidence": conf, "image": url,
                      "alts": alts, "analysis": describe(feat), "ai": ai, "aux": aux,
                      "species": sp}
            # 模型没有该作物训练样本（如水稻/小麦）但知识库有资料时，
            # 直接把该作物的科普与常见病害给出来，而不是只说"无法识别"
            if ai.get("ok") and not ai.get("known", True) and crop_id:
                kb_diseases = db.query(
                    "SELECT id,name,slug,dtype,symptoms FROM diseases WHERE crop_id=? "
                    "ORDER BY id", [crop_id])
                result["kb_fallback"] = {"crop": crop, "diseases": kb_diseases}
    crops = db.query("SELECT id,name,slug FROM crops ORDER BY id")
    diseases = db.query("SELECT d.id,d.name,d.slug,c.name crop_name FROM diseases d "
                        "LEFT JOIN crops c ON c.id=d.crop_id ORDER BY c.name, d.id")
    return render_template("disease_recognize.html", crops=crops, diseases=diseases, result=result,
                           ai_crops=AI_CROPS_CN, kb_only=kb_only_crops())


# ---------------- 农技知识库 ---------------- #

@app.route("/knowledge")
def knowledge():
    tab = request.args.get("tab", "crop")
    kw = request.args.get("kw", "").strip()
    crop_id = request.args.get("crop_id", type=int)
    if tab == "disease":
        sql = ("SELECT d.*, c.name crop_name FROM diseases d LEFT JOIN crops c ON c.id=d.crop_id "
               "WHERE 1=1")
        args = []
        if kw:
            sql += " AND (d.name LIKE ? OR d.symptoms LIKE ?)"
            args += ["%%%s%%" % kw, "%%%s%%" % kw]
        if crop_id:
            sql += " AND d.crop_id=?"
            args.append(crop_id)
        items = db.query(sql + " ORDER BY d.id", args)
    else:
        sql = "SELECT * FROM crops WHERE 1=1"
        args = []
        if kw:
            sql += " AND (name LIKE ? OR alias LIKE ? OR intro LIKE ?)"
            args += ["%%%s%%" % kw] * 3
        items = db.query(sql + " ORDER BY id", args)
    crops = db.query("SELECT id,name,slug FROM crops ORDER BY id")
    return render_template("knowledge.html", tab=tab, items=items, crops=crops, kw=kw,
                           crop_id=crop_id)


@app.route("/crop/<slug>")
def crop_detail(slug):
    crop = db.query("SELECT * FROM crops WHERE slug=?", [slug], one=True)
    if not crop:
        abort(404)
    diseases = db.query("SELECT id,name,slug,dtype,symptoms FROM diseases WHERE crop_id=? "
                        "ORDER BY id", [crop["id"]])
    return render_template("crop_detail.html", crop=crop, diseases=diseases)


@app.route("/disease/<slug>")
def disease_detail(slug):
    d = db.query("SELECT d.*, c.name crop_name, c.slug crop_slug FROM diseases d "
                 "LEFT JOIN crops c ON c.id=d.crop_id WHERE d.slug=?", [slug], one=True)
    if not d:
        abort(404)
    return render_template("disease_detail.html", d=d)


# ---------------- 农产品商城 ---------------- #

@app.route("/shop")
def shop():
    cat = request.args.get("cat", "")
    kw = request.args.get("kw", "").strip()
    sort = request.args.get("sort", "new")
    sql = "SELECT * FROM products WHERE status='approved'"
    args = []
    if cat:
        sql += " AND category=?"
        args.append(cat)
    if kw:
        sql += " AND (name LIKE ? OR origin LIKE ? OR description LIKE ?)"
        args += ["%%%s%%" % kw] * 3
    order = {"new": "id DESC", "price": "price ASC", "hot": "stock DESC"}.get(sort, "id DESC")
    products = db.query(sql + " ORDER BY " + order, args)
    return render_template("shop.html", products=products, cat=cat, kw=kw, sort=sort,
                           categories=CATEGORIES)


@app.route("/product/<int:pid>")
def product_detail(pid):
    p = db.query("SELECT * FROM products WHERE id=?", [pid], one=True)
    if not p:
        abort(404)
    related = db.query("SELECT * FROM products WHERE status='approved' AND category=? AND id!=? "
                       "LIMIT 4", [p["category"], pid])
    msgs = db.query("SELECT * FROM messages WHERE product_id=? AND reply!='' ORDER BY id DESC LIMIT 5",
                    [pid])
    return render_template("product_detail.html", p=p, related=related, msgs=msgs)


@app.route("/cart")
def cart():
    items = db.query(
        "SELECT c.id, c.qty, p.* FROM cart_items c JOIN products p ON p.id=c.product_id "
        "WHERE c.user_key=? ORDER BY c.id DESC", [cart_key()])
    total = sum(i["price"] * i["qty"] for i in items)
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/add", methods=["POST"])
def cart_add():
    pid = request.form.get("product_id", type=int)
    qty = max(1, request.form.get("qty", 1, type=int))
    p = db.query("SELECT * FROM products WHERE id=? AND status='approved'", [pid], one=True)
    if not p:
        flash("商品不存在或已下架", "warn")
        return redirect(url_for("shop"))
    row = db.query("SELECT * FROM cart_items WHERE user_key=? AND product_id=?",
                   [cart_key(), pid], one=True)
    if row:
        db.execute("UPDATE cart_items SET qty=qty+? WHERE id=?", [qty, row["id"]])
    else:
        db.execute("INSERT INTO cart_items(user_key,product_id,qty,created_at) VALUES(?,?,?,?)",
                   [cart_key(), pid, qty, now()])
    flash("已加入清单：%s" % p["name"], "ok")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    cid = request.form.get("id", type=int)
    qty = request.form.get("qty", 1, type=int)
    if qty <= 0:
        db.execute("DELETE FROM cart_items WHERE id=? AND user_key=?", [cid, cart_key()])
    else:
        db.execute("UPDATE cart_items SET qty=? WHERE id=? AND user_key=?", [qty, cid, cart_key()])
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:cid>")
def cart_remove(cid):
    db.execute("DELETE FROM cart_items WHERE id=? AND user_key=?", [cid, cart_key()])
    flash("已移出清单", "ok")
    return redirect(url_for("cart"))


@app.route("/cart/submit", methods=["POST"])
def cart_submit():
    """咨询型下单：不接入支付，仅提交需求，由农户电话联系确认。"""
    buyer = request.form.get("buyer", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    if not buyer or not phone:
        flash("请填写联系人姓名和手机号", "warn")
        return redirect(url_for("cart"))
    items = db.query("SELECT c.qty, p.id, p.name, p.price, p.unit, p.farmer_name FROM cart_items c "
                     "JOIN products p ON p.id=c.product_id WHERE c.user_key=?", [cart_key()])
    if not items:
        flash("清单是空的", "warn")
        return redirect(url_for("cart"))
    total = sum(i["price"] * i["qty"] for i in items)
    order_no = "NH" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
    detail = "；".join("%s × %d%s（¥%.2f，供货：%s）" % (i["name"], i["qty"], i["unit"],
                                                       i["price"], i["farmer_name"]) for i in items)
    db.execute("INSERT INTO orders(order_no,user_key,buyer,phone,address,total,items,status,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               [order_no, cart_key(), buyer, phone, address, total, detail, "待农户联系", now()])
    db.execute("DELETE FROM cart_items WHERE user_key=?", [cart_key()])
    flash("需求已提交，单号 %s，农户会在 24 小时内与您联系" % order_no, "ok")
    return redirect(url_for("profile", tab="orders"))


@app.route("/message", methods=["POST"])
def message():
    """商品咨询留言。"""
    name = request.form.get("name", "").strip()
    contact = request.form.get("contact", "").strip()
    content = request.form.get("content", "").strip()
    pid = request.form.get("product_id", type=int)
    if not name or not content:
        flash("请填写您的称呼和咨询内容", "warn")
        return redirect(request.referrer or url_for("shop"))
    pname = ""
    if pid:
        p = db.query("SELECT name FROM products WHERE id=?", [pid], one=True)
        pname = p["name"] if p else ""
    db.execute("INSERT INTO messages(product_id,product_name,name,contact,content,created_at)"
               " VALUES(?,?,?,?,?,?)", [pid, pname, name, contact, content, now()])
    flash("留言已提交，农户会尽快回复", "ok")
    return redirect(request.referrer or url_for("shop"))


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """农户简易上架商品。"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", 0, type=float)
        if not name or price <= 0:
            flash("请填写商品名称和正确的价格", "warn")
            return redirect(url_for("sell"))
        u = current_user()
        db.execute("INSERT INTO products(name,category,origin,price,unit,stock,description,icon,"
                   "farmer_id,farmer_name,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   [name, request.form.get("category", "时令果蔬"), request.form.get("origin", ""),
                    price, request.form.get("unit", "斤"), request.form.get("stock", 0, type=int),
                    request.form.get("description", ""), "basket", u["id"],
                    request.form.get("farmer_name", "") or u["username"], "pending", now()])
        flash("商品已提交，等待平台审核后展示", "ok")
        return redirect(url_for("profile", tab="products"))
    return render_template("sell.html", categories=CATEGORIES)


# ---------------- 用户中心 ---------------- #

def safe_next(url):
    """只允许站内相对路径作为回跳目标，避免开放重定向。"""
    if not url or not url.startswith("/") or url.startswith("//"):
        return ""
    return url


@app.route("/register", methods=["GET", "POST"])
def register():
    nxt = safe_next(request.args.get("next", ""))
    if "user_id" in session:          # 已登录就不用再看登录墙
        return redirect(nxt or url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pwd = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        if not username or not pwd:
            flash("请填写用户名和密码", "warn")
            return redirect(url_for("register"))
        if db.query("SELECT id FROM users WHERE username=?", [username], one=True):
            flash("用户名已被注册", "warn")
            return redirect(url_for("register"))
        uid = db.execute("INSERT INTO users(username,password_hash,phone,role,village,created_at)"
                         " VALUES(?,?,?,?,?,?)",
                         [username, generate_password_hash(pwd), phone, "user",
                          request.form.get("village", ""), now()])
        _merge_cart(uid)
        session["user_id"] = uid
        session["username"] = username
        flash("注册成功，欢迎使用助农平台", "ok")
        return redirect(safe_next(request.form.get("next", "")) or url_for("index"))
    return render_template("login.html", mode="register", next=nxt)


@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.args.get("next", ""))
    if "user_id" in session and request.method == "GET":
        return redirect(nxt or url_for("index"))
    if request.method == "POST":
        # 同时去掉首尾空格：避免复制粘贴时带进来的不可见空格导致登录失败
        username = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()
        # 用户名不区分大小写，避免 Admin / ADMIN 之类写法被判为错误
        u = db.query("SELECT * FROM users WHERE lower(username)=lower(?)", [username], one=True)
        back = safe_next(request.form.get("next", ""))
        if not u:
            flash("账号「%s」不存在，可先注册，或点下方演示账号一键填入" % username, "warn")
            return redirect(url_for("login", next=back))
        if not check_password_hash(u["password_hash"], pwd):
            flash("密码不正确，请检查是否多输入了空格或开了大写锁定", "warn")
            return redirect(url_for("login", next=back))
        _merge_cart(u["id"])
        session["user_id"] = u["id"]
        session["username"] = u["username"]
        flash("登录成功，欢迎回来", "ok")
        return redirect(back or url_for("index"))
    return render_template("login.html", mode="login", next=nxt)


def _merge_cart(uid):
    """登录后把游客购物车合并到账号下。"""
    sid = session.get("sid")
    if sid:
        db.execute("UPDATE OR IGNORE cart_items SET user_key=? WHERE user_key=?",
                   ["u:%d" % uid, "s:" + sid])
        db.execute("DELETE FROM cart_items WHERE user_key=?", ["s:" + sid])


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "ok")
    return redirect(url_for("login"))


@app.route("/profile")
@login_required
def profile():
    tab = request.args.get("tab", "home")
    u = current_user()
    key = cart_key()
    data = {
        "history": db.query("SELECT * FROM history WHERE user_key=? ORDER BY id DESC LIMIT 20", [key]),
        "orders": db.query("SELECT * FROM orders WHERE user_key=? ORDER BY id DESC", [key]),
        "products": db.query("SELECT * FROM products WHERE farmer_id=? ORDER BY id DESC", [u["id"]]),
        "messages": db.query("SELECT * FROM messages WHERE name=? ORDER BY id DESC LIMIT 20",
                             [u["username"]]),
    }
    return render_template("profile.html", user=u, tab=tab, **data)


# ---------------- 简易后台 ---------------- #

@app.route("/admin")
@admin_required
def admin():
    tab = request.args.get("tab", "overview")
    stats = {
        "users": db.query("SELECT COUNT(*) c FROM users", one=True)["c"],
        "products": db.query("SELECT COUNT(*) c FROM products", one=True)["c"],
        "pending": db.query("SELECT COUNT(*) c FROM products WHERE status='pending'", one=True)["c"],
        "orders": db.query("SELECT COUNT(*) c FROM orders", one=True)["c"],
        "messages": db.query("SELECT COUNT(*) c FROM messages", one=True)["c"],
        "scans": db.query("SELECT COUNT(*) c FROM history", one=True)["c"],
        "crop_scans": db.query("SELECT COUNT(*) c FROM history WHERE kind='crop'", one=True)["c"],
        "dis_scans": db.query("SELECT COUNT(*) c FROM history WHERE kind='disease'", one=True)["c"],
    }
    data = {
        "products": db.query("SELECT * FROM products ORDER BY id DESC"),
        "orders": db.query("SELECT * FROM orders ORDER BY id DESC LIMIT 50"),
        "messages": db.query("SELECT * FROM messages ORDER BY id DESC LIMIT 50"),
        "users": db.query("SELECT id,username,phone,role,village,created_at FROM users ORDER BY id"),
        "history": db.query("SELECT * FROM history ORDER BY id DESC LIMIT 30"),
        "top_crops": db.query("SELECT result_name, COUNT(*) c FROM history WHERE kind='crop' "
                              "GROUP BY result_name ORDER BY c DESC LIMIT 6"),
    }
    return render_template("admin.html", tab=tab, stats=stats, **data)


@app.route("/admin/product/<int:pid>/<action>")
@admin_required
def admin_product(pid, action):
    if action == "approve":
        db.execute("UPDATE products SET status='approved' WHERE id=?", [pid])
        flash("商品已通过审核并上架", "ok")
    elif action == "reject":
        db.execute("UPDATE products SET status='rejected' WHERE id=?", [pid])
        flash("商品已驳回", "ok")
    elif action == "delete":
        db.execute("DELETE FROM products WHERE id=?", [pid])
        flash("商品已删除", "ok")
    return redirect(url_for("admin", tab="products"))


@app.route("/admin/message/<int:mid>", methods=["POST"])
@admin_required
def admin_message(mid):
    reply = request.form.get("reply", "").strip()
    if reply:
        db.execute("UPDATE messages SET reply=? WHERE id=?", [reply, mid])
        flash("回复已保存", "ok")
    return redirect(url_for("admin", tab="messages"))


@app.route("/admin/order/<int:oid>/<status>")
@admin_required
def admin_order(oid, status):
    db.execute("UPDATE orders SET status=? WHERE id=?", [status, oid])
    flash("订单状态已更新", "ok")
    return redirect(url_for("admin", tab="orders"))


@app.route("/uploads/<name>")
def uploaded(name):
    return send_from_directory(UPLOAD_DIR, secure_filename(name))


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    flash("图片过大，请压缩到 8MB 以内再上传", "warn")
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 5000))

    # 单实例保护：如果已有服务占用该端口，本实例直接退出，
    # 避免多个副本并存导致浏览器有时拿到旧页面/旧图片。
    import socket as _socket
    _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        _s.bind(("0.0.0.0", port))
    except OSError:
        _s.close()
        print()
        print("  端口 %d 已有服务在运行，本次不重复启动。" % port)
        print("  已为你打开： http://127.0.0.1:%d/" % port)
        try:
            import webbrowser
            webbrowser.open("http://127.0.0.1:%d/" % port)
        except Exception:
            pass
        raise SystemExit(0)
    finally:
        try:
            _s.close()
        except Exception:
            pass

    # 双击启动时由 launcher.py 传入 FLASK_DEBUG=0，避免调试重载器重复派生进程。
    # 云端/容器部署会注入 PORT，此时默认关闭调试重载器（否则会派生第二个进程抢同一端口）。
    _dbg_default = "0" if os.environ.get("PORT") else "1"
    debug = os.environ.get("FLASK_DEBUG", _dbg_default) == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
