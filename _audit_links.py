# -*- coding: utf-8 -*-
"""站内链接完整性巡检：抓取全部页面的 <a href> 内链，逐个请求验证可达性。"""
import io
import os
import re
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "agri.db")
BAK = DB + ".linkbak"
shutil.copy2(DB, BAK)

try:
    import app as appmod
    import db as dbmod

    app = appmod.app
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})

    seeds = ["/", "/ai-lab", "/assistant", "/agent", "/crop-recognize",
             "/disease-recognize", "/knowledge", "/shop", "/cart", "/sell",
             "/profile", "/admin"]
    seeds += ["/crop/%s" % r["slug"] for r in dbmod.query("SELECT slug FROM crops")]
    seeds += ["/disease/%s" % r["slug"] for r in dbmod.query("SELECT slug FROM diseases")]
    seeds += ["/product/%d" % r["id"] for r in dbmod.query("SELECT id FROM products LIMIT 4")]

    seen_pages = set()
    links = {}
    for p in seeds:
        r = c.get(p, follow_redirects=True)
        if r.status_code != 200:
            print("页面异常:", p, r.status_code)
            continue
        seen_pages.add(p)
        html = r.get_data(as_text=True)
        for href in re.findall(r'href="(/[^"#?]*)"', html):
            if href.startswith(("/static", "/uploads", "/logout")):
                continue
            links.setdefault(href, p)

    print("抓取页面 %d 个，内链 %d 条" % (len(seen_pages), len(links)))
    bad = []
    for href, src in sorted(links.items()):
        r = c.get(href, follow_redirects=True)
        if r.status_code >= 400:
            bad.append((href, src, r.status_code))

    if bad:
        print("\n!! 死链 %d 条:" % len(bad))
        for h, s, code in bad:
            print("  -", h, "→ HTTP", code, "（来自 %s）" % s)
    else:
        print("\n>> 全部内链可达")
finally:
    if os.path.exists(BAK):
        shutil.move(BAK, DB)
    for suf in ("-wal", "-shm"):
        p = DB + suf
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    print("\n数据库已恢复")
