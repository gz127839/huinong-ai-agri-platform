# -*- coding: utf-8 -*-
"""端到端验证：问答助手与智能体是否真的走大模型。"""
import io
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import app as A

c = A.app.test_client()
r = c.post("/login", data={"username": "demo", "password": "demo123"}, follow_redirects=True)
print("登录:", r.status_code)

t = time.time()
r = c.post("/assistant", data={"question": "水稻叶片发黄是什么原因，怎么处理"},
           follow_redirects=True)
html = r.get_data(as_text=True)
txt = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
txt = re.sub(r"<[^>]+>", " ", txt)
txt = re.sub(r"\s+", " ", txt)
mode_kb = "仅检索" in txt
mode_llm = "大模型" in txt and not mode_kb
print("问答: HTTP %s  %.1fs  仅检索模式=%s" % (r.status_code, time.time() - t, mode_kb))
i = txt.find("回答")
print("  片段:", txt[max(0, i):i + 260])

t = time.time()
r = c.post("/agent", data={"question": "我家水稻叶子发黄，该查什么、买什么药"},
           follow_redirects=True)
html = r.get_data(as_text=True)
txt = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
txt = re.sub(r"<[^>]+>", " ", txt)
txt = re.sub(r"\s+", " ", txt)
print("智能体: HTTP %s  %.1fs" % (r.status_code, time.time() - t))
for kw in ("大模型自主规划", "内置规则规划器", "执行轨迹", "最终建议"):
    print("  %s: %s" % (kw, kw in txt))
m = re.findall(r"(调用工具|工具)\s*[:：]?\s*([a-z_]+)", txt)
print("  工具序列:", [x[1] for x in m][:8])
i = txt.find("最终建议")
print("  结论:", txt[i:i + 240] if i > 0 else txt[:240])
