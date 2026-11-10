# -*- coding: utf-8 -*-
"""启动一次性 Flask 实例，用 Edge 截取物种识别新效果演示图，退出即回收。"""
import os, sys, threading, time

PROJ = r"D:\慧农AI智慧农业平台"
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import app as appmod
from werkzeug.serving import make_server

PORT = 5017
srv = make_server("127.0.0.1", PORT, appmod.app, threaded=True)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()

import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=5)
        print("server up", flush=True)
        break
    except Exception as e:
        time.sleep(1)
else:
    print("server never came up", flush=True)
    sys.exit(1)

from playwright.sync_api import sync_playwright

DESK = r"C:\Users\异乡人\Desktop\图片1"
OUT = r"D:\慧农AI智慧农业平台-交付包\03_演示截图"
os.makedirs(OUT, exist_ok=True)

JOBS = [
    ("0d90c14453adb21fb727999382405fd2.jpg", "/crop-recognize", "043_实景物种识别_水稻稻穗.png"),
    ("567a86f27a8bc3bc92e92a953c7e7515.jpg", "/crop-recognize", "044_实景物种识别_小麦麦穗.png"),
    ("8a460e017d026e138b5b65259e8e8716.jpg", "/crop-recognize", "045_实景物种识别_柑橘果实.png"),
    ("d318258b6786e52298a9d3b799e616ab.jpg", "/crop-recognize", "046_实景物种识别_草莓果实.png"),
    ("e81a543207a5662f3778b4a23e084310.jpg", "/crop-recognize", "047_实景物种识别_葡萄果实.png"),
    ("5f51a642cc14b28fc0562198e526a29f.jpg", "/crop-recognize", "048_实景物种识别_黄瓜果实.png"),
    ("20fa8ee65c8d101491f0d95e498c4c72.jpg", "/crop-recognize", "049_实景物种识别_玉米果穗.png"),
    ("f5a05532f35afba7a1f4ac9bbc88940a.jpg", "/crop-recognize", "050_实景物种识别_油菜花田.png"),
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
    for img, path, outname in JOBS:
        pg.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded", timeout=90000)
        pg.set_input_files("input[type=file]", os.path.join(DESK, img))
        try:
            pg.wait_for_load_state("networkidle", timeout=90000)
        except Exception:
            pass
        pg.wait_for_timeout(2500)
        pg.screenshot(path=os.path.join(OUT, outname), full_page=True)
        print("saved", outname, flush=True)

    # AI 能力实验室（已更新为含实景物种识别的能力边界章节）
    pg.goto("http://127.0.0.1:%d/ai-lab" % PORT, wait_until="domcontentloaded", timeout=90000)
    try:
        pg.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, "PC端-09-AI能力实验室.png"), full_page=True)
    print("saved PC端-09-AI能力实验室.png", flush=True)

    b.close()

srv.shutdown()
print("done, server stopped", flush=True)
