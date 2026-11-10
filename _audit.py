# -*- coding: utf-8 -*-
"""全站冒烟巡检：路由可达性 + 静态资源完整性 + 模板异常痕迹。

以 admin 登录后用 Flask test_client 跑全部 GET 路由与关键写操作，
测试前备份数据库、结束后恢复，不污染真实数据。
"""
import io
import os
import re
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "agri.db")
BAK = DB + ".auditbak"

shutil.copy2(DB, BAK)
try:
    import app as appmod
    import db as dbmod

    app = appmod.app
    app.config["TESTING"] = True
    c = app.test_client()

    problems = []
    warn = []

    # 1) 登录墙
    r = c.get("/")
    if r.status_code != 302:
        problems.append("未登录访问首页应 302 到登录页，实际 %s" % r.status_code)

    # 2) 登录
    r = c.post("/login", data={"username": "admin", "password": "admin123"},
               follow_redirects=False)
    if r.status_code != 302:
        problems.append("admin 登录失败，状态 %s" % r.status_code)

    # 路由清单（GET）
    crops = [x["slug"] for x in dbmod.query("SELECT slug FROM crops")]
    diseases = [x["slug"] for x in dbmod.query("SELECT slug FROM diseases")]
    products = [x["id"] for x in dbmod.query("SELECT id FROM products LIMIT 5")]

    routes = ["/", "/ai-lab", "/assistant", "/agent", "/crop-recognize",
              "/disease-recognize", "/knowledge", "/shop", "/cart", "/sell",
              "/profile", "/admin", "/register", "/login"]
    routes += ["/crop/%s" % s for s in crops]
    routes += ["/disease/%s" % s for s in diseases]
    routes += ["/product/%d" % i for i in products]

    pages = {}
    t0 = time.time()
    for path in routes:
        try:
            r = c.get(path, follow_redirects=True)
        except Exception as e:
            problems.append("路由异常 %s → %s: %s" % (path, e.__class__.__name__, e))
            continue
        pages[path] = r
        if r.status_code != 200:
            problems.append("%s → HTTP %s" % (path, r.status_code))
            continue
        html = r.get_data(as_text=True)
        for bad in ("Traceback (most recent call last)", "jinja2.exceptions",
                    "UndefinedError", "{{ ", "{% "):
            if bad in html:
                problems.append("%s 页面出现模板异常痕迹: %r" % (path, bad))
                break
        # 模板未渲染变量：{{ xxx }} 之外再查 None 字样
        if re.search(r">\s*None\s*<", html):
            warn.append("%s 页面疑似渲染出 None 文本" % path)

    print("== GET 路由 %d 条，耗时 %.1fs ==" % (len(routes), time.time() - t0))

    # 3) 静态资源引用完整性
    static_root = os.path.join(BASE, "static")
    missing = {}
    for path, r in pages.items():
        html = r.get_data(as_text=True)
        refs = re.findall(r'(?:src|href)="(/static/[^"?#]+)', html)
        refs += re.findall(r"url\('(/static/[^'?#]+)'\)", html)
        for ref in set(refs):
            fp = os.path.join(BASE, ref.lstrip("/").replace("/", os.sep))
            if not os.path.exists(fp):
                missing.setdefault(ref, []).append(path)
    if missing:
        for ref, srcs in sorted(missing.items()):
            problems.append("静态资源缺失 %s（被 %d 个页面引用，如 %s）"
                            % (ref, len(srcs), srcs[0]))
    else:
        print("== 静态资源引用：全部存在 ==")

    # 4) 数据库图片字段指向的文件（crops.image 为真实路径，其余表用 icon 字符）
    img_missing = []
    for row in dbmod.query("SELECT name, image FROM crops WHERE image != '' AND image IS NOT NULL"):
        img = row["image"].lstrip("/")
        fp = os.path.join(BASE, "static", img.replace("/", os.sep))
        if not os.path.exists(fp):
            img_missing.append(("作物", row["name"], row["image"]))
    if img_missing:
        for kind, name, img in img_missing:
            problems.append("数据库图片缺失 [%s] %s → %s" % (kind, name, img))
    else:
        print("== 数据库图片字段：全部指向存在的文件 ==")

    # 空图标/空名称等脏数据
    for t, label in (("crops", "作物"), ("diseases", "病害"), ("products", "商品")):
        bad = dbmod.query(
            "SELECT name FROM %s WHERE name IS NULL OR TRIM(name)='' OR icon IS NULL OR TRIM(icon)=''" % t)
        if bad:
            problems.append("%s表存在空名称或空图标: %s" % (label, [b["name"] for b in bad][:5]))


    # 5) 数据一致性
    n_crops = dbmod.query("SELECT COUNT(*) c FROM crops", one=True)["c"]
    n_dis = dbmod.query("SELECT COUNT(*) c FROM diseases", one=True)["c"]
    n_prod = dbmod.query("SELECT COUNT(*) c FROM products", one=True)["c"]
    print("== 知识库规模：作物 %d / 病害 %d / 商品 %d ==" % (n_crops, n_dis, n_prod))

    # 病害无归属作物
    orphan = dbmod.query(
        "SELECT d.name FROM diseases d LEFT JOIN crops c ON c.id=d.crop_id WHERE c.id IS NULL")
    if orphan:
        problems.append("病害未关联作物: %s" % [o["name"] for o in orphan])

    # 6) 关键写操作
    r = c.post("/cart/add", data={"pid": str(products[0]), "qty": "1"},
               follow_redirects=True)
    if r.status_code != 200:
        problems.append("加入购物车失败 HTTP %s" % r.status_code)
    cart = dbmod.query("SELECT COUNT(*) c FROM cart_items", one=True)["c"]
    print("== 购物车写入后条目数：%d ==" % cart)

    r = c.post("/message", data={"pid": str(products[0]), "content": "巡检测试留言"},
               follow_redirects=True)
    if r.status_code != 200:
        problems.append("留言失败 HTTP %s" % r.status_code)

    # 7) 404 页面与 API 边界
    r = c.get("/no-such-page")
    if r.status_code != 404:
        problems.append("未知路径应 404，实际 %s" % r.status_code)
    r = c.post("/api/agent", json={})
    if r.status_code not in (200, 400):
        problems.append("/api/agent 空请求应 200/400，实际 %s" % r.status_code)

    # 8) 未登录时 API 应 401
    c2 = app.test_client()
    r2 = c2.post("/api/agent", json={"question": "test"})
    if r2.status_code != 401:
        problems.append("未登录 /api/agent 应 401，实际 %s" % r2.status_code)

    print()
    if problems:
        print("!! 发现 %d 个问题:" % len(problems))
        for p in problems:
            print("  -", p)
    else:
        print(">> 未发现问题")
    if warn:
        print("?? 提示 %d 条:" % len(warn))
        for w in warn[:10]:
            print("  -", w)
finally:
    if os.path.exists(BAK):
        shutil.move(BAK, DB)
    # 清 WAL 残留
    for suf in ("-wal", "-shm"):
        if os.path.exists(DB + suf):
            try:
                os.remove(DB + suf)
            except OSError:
                pass
    print("\n数据库已恢复")
