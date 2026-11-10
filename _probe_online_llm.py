# -*- coding: utf-8 -*-
"""探测线上发布站点：登录后提问，判断问答/智能体是否真的走大模型。"""
import http.cookiejar
import io
import re
import sys
import time
import urllib.parse
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://agri-ai-platform-50936.app.workbuddy.host"
SHARE = "SBBOCRVH7J"

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "Mozilla/5.0")]


def get(path):
    return op.open(BASE + path, timeout=60).read().decode("utf-8", "replace")


def post(path, data, timeout=180):
    body = urllib.parse.urlencode(data).encode()
    return op.open(BASE + path, body, timeout=timeout).read().decode("utf-8", "replace")


def text(html):
    s = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s)


try:
    h = get("/?sharecode=" + SHARE)
    print("首页:", len(h), "字节")
except Exception as e:
    print("首页失败:", e)

try:
    print("登录页:", len(get("/login")), "字节")
except Exception as e:
    print("登录页失败:", e)

ok = False
for u, p in (("demo", "demo123"), ("admin", "admin123")):
    try:
        r = post("/login", {"username": u, "password": p})
        t = text(r)
        if "退出" in t or "工作台" in t or "首页" in t:
            print("登录成功:", u)
            ok = True
            break
    except Exception as e:
        print("登录异常", u, e)

if ok:
    t0 = time.time()
    try:
        r = post("/assistant", {"question": "水稻叶片发黄是什么原因，怎么处理"}, timeout=240)
        t = text(r)
        print("问答 %.1fs  仅检索=%s  含大模型字样=%s" % (time.time() - t0, "仅检索" in t,
                                                    "大模型" in t))
        i = t.find("回答")
        print("  片段:", t[max(0, i):i + 300])
    except Exception as e:
        print("问答失败:", e)
    t0 = time.time()
    try:
        r = post("/agent", {"question": "我家水稻叶子发黄，该查什么、买什么药"}, timeout=300)
        t = text(r)
        print("智能体 %.1fs  自主规划=%s  规则规划=%s" % (time.time() - t0,
                                                  "大模型自主规划" in t, "规则规划器" in t))
        i = t.find("最终建议")
        print("  结论:", t[i:i + 200] if i > 0 else t[:200])
    except Exception as e:
        print("智能体失败:", e)
