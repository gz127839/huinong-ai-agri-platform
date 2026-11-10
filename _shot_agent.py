# -*- coding: utf-8 -*-
"""启动一次性 Flask 实例，用 Edge 截取农业智能体演示图，退出即回收。"""
import os, sys, threading, time

PROJ = r"D:\慧农AI智慧农业平台"
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import app as appmod
from werkzeug.serving import make_server

PORT = 5021
srv = make_server("127.0.0.1", PORT, appmod.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=5)
        print("server up", flush=True)
        break
    except Exception:
        time.sleep(1)

from playwright.sync_api import sync_playwright

DESK = r"C:\Users\异乡人\Desktop\图片1"
OUT = r"D:\慧农AI智慧农业平台-交付包\03_演示截图"
os.makedirs(OUT, exist_ok=True)

JOBS = [
    # (图片, 问题, 输出文件名)
    ("0d90c14453adb21fb727999382405fd2.jpg",
     "这是什么作物？最近叶子发黄还有褐色病斑，该怎么办",
     "051_农业智能体_带图完整链路.png"),
    (None, "番茄早疫病打什么药，多少钱", "052_农业智能体_用药与采购.png"),
    (None, "马铃薯什么时候种合适，要注意什么", "053_农业智能体_种植咨询.png"),
]

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded", timeout=90000)
    try:
        pg.wait_for_timeout(1200)
        skip = pg.locator("text=跳过")
        if skip.count():
            skip.first.click(timeout=2000)
    except Exception:
        pass

    for img, q, outname in JOBS:
        pg.goto("http://127.0.0.1:%d/agent" % PORT,
                wait_until="domcontentloaded", timeout=90000)
        if img:
            pg.set_input_files("input[type=file]", os.path.join(DESK, img))
        pg.fill("input[name=question]", q)
        pg.click("button[type=submit]")
        try:
            pg.wait_for_load_state("networkidle", timeout=90000)
        except Exception:
            pass
        pg.wait_for_timeout(2000)
        pg.screenshot(path=os.path.join(OUT, outname), full_page=True)
        print("saved", outname, flush=True)

    b.close()

srv.shutdown()
print("done, server stopped", flush=True)
