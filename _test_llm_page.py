# -*- coding: utf-8 -*-
"""验证问答/智能体页面显示大模型信息。"""
import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import app as A

c = A.app.test_client()
r = c.post("/login", data={"username": "demo", "password": "demo123"})
print("登录:", r.status_code)

r = c.get("/assistant")
h = r.get_data(as_text=True)
print("问答页: 已接入大模型=%s" % ("已接入大模型" in h))
m = re.search(r"已接入大模型：([\w\-.]+)", h)
print("  模型:", m.group(1) if m else "?")
m = re.search(r"RAG 检索增强生成", h)
print("  RAG说明:", bool(m))

r = c.get("/agent")
h = r.get_data(as_text=True)
print("智能体页: 已接入大模型=%s  Function Calling说明=%s  规则降级提示=%s"
      % ("已接入大模型" in h, "Function Calling" in h, "规则规划器」模式" in h))

r = c.get("/ai-lab")
h = r.get_data(as_text=True)
print("AI实验室: 第十一节=%s  选型=%s  Prompt设计=%s" %
      ("十一、大模型集成" in h, "模型选型" in h, "Prompt 设计" in h))
