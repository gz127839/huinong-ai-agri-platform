# -*- coding: utf-8 -*-
"""截取线上问答/智能体的大模型输出（留作交付截图）。"""
import os
import sys

from playwright.sync_api import sync_playwright

B = "https://agri-ai-platform-50936.app.workbuddy.host"
LINK = B + "/?sharecode=SBBOCRVH7J"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_llm_shots")
os.makedirs(OUT, exist_ok=True)

with sync_playwright() as p:
    br = p.chromium.launch(channel="msedge", headless=True)
    pg = br.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    pg.goto(LINK, wait_until="domcontentloaded", timeout=60000)
    pg.fill("input[name=username]", "demo")
    pg.fill("input[name=password]", "demo123")
    pg.click("button[type=submit]")
    pg.wait_for_timeout(2500)

    pg.goto(B + "/assistant", wait_until="domcontentloaded")
    pg.fill("input[name=question]", "水稻叶片发黄是什么原因，怎么处理")
    pg.click("button[type=submit]")
    pg.wait_for_selector("text=AI 回答", timeout=90000)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, "qa.png"), full_page=True)
    print("问答截图 OK")

    pg.goto(B + "/agent", wait_until="domcontentloaded")
    pg.fill("input[name=question]", "我家水稻叶子发黄，该查什么、买什么药")
    pg.click("button[type=submit]")
    pg.wait_for_selector("text=最终建议", timeout=180000)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, "agent.png"), full_page=True)
    print("智能体截图 OK")
    br.close()
