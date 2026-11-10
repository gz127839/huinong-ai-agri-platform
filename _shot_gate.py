# -*- coding: utf-8 -*-
"""登录墙视觉核验：起一次性 Flask，截登录界面 + 登录后的首页。"""
import os, sys, threading, time

PROJ = r"D:\慧农AI智慧农业平台"
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import app as appmod
from werkzeug.serving import make_server

PORT = 5033
srv = make_server("127.0.0.1", PORT, appmod.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/login" % PORT, timeout=5)
        print("server up", flush=True)
        break
    except Exception:
        time.sleep(1)

from playwright.sync_api import sync_playwright

OUT = os.path.join(PROJ, "_gate_shots")
os.makedirs(OUT, exist_ok=True)
BASE = "http://127.0.0.1:%d" % PORT


def skip_intro(page):
    try:
        page.wait_for_selector("#introOverlay:not([hidden])", timeout=3000)
        page.click("#introOverlay", position={"x": 30, "y": 200})
        page.wait_for_timeout(900)
    except Exception:
        pass


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")

    # 1) 未登录直接访问首页 → 应被拦到登录页
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/", wait_until="networkidle")
    print("url after gate:", pg.url, flush=True)
    skip_intro(pg)
    pg.screenshot(path=os.path.join(OUT, "gate_login.png"))
    pg.click(".auth-tabs a:has-text('注册')")
    pg.wait_for_load_state("networkidle")
    pg.screenshot(path=os.path.join(OUT, "gate_register.png"))

    # 2) 登录 → 回到首页
    pg.goto(BASE + "/login", wait_until="networkidle")
    pg.click("button:has-text('普通用户 demo')")
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")
    print("url after login:", pg.url, flush=True)
    pg.screenshot(path=os.path.join(OUT, "after_login_home.png"))
    pg.close()

    # 3) 手机端登录界面
    m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True,
                   has_touch=True, device_scale_factor=2)
    m.goto(BASE + "/crop-recognize", wait_until="networkidle")
    skip_intro(m)
    m.screenshot(path=os.path.join(OUT, "gate_mobile.png"))
    m.close()

    b.close()

print("shots ->", OUT)
