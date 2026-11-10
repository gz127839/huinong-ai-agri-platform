# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import app as A
c = A.app.test_client()
print("登录:", c.post("/login", data={"username": "demo", "password": "demo123"}).status_code)
h = c.get("/ai-lab").get_data(as_text=True)
print("AI实验室 200:", "/ai-lab" and len(h) > 1000)
for k in ("十二、MCP 工具服务", "mcp_server.py", "tools/list", "recognize_image", "零第三方依赖", "mcpServers"):
    print("  含[%s]: %s" % (k, k in h))
h2 = c.get("/agent").get_data(as_text=True)
print("智能体页 含标准MCP服务端:", "标准 MCP 服务端" in h2)
