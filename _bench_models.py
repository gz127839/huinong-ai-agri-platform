# -*- coding: utf-8 -*-
"""对比云服务可用模型：正文质量、是否只吐思考、耗时。"""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import llm_client

MODELS = ["hunyuan-chat", "hunyuan-2.0-thinking", "glm-5.3-flash", "deepseek-v4-flash",
          "minimax-m3.1-flash", "auto", "hy4free"]

SYS = ("你是农业智能体。可用工具：recognize_image、crop_profile、query_disease、"
       "search_knowledge、list_products。\n"
       "严格按格式，每轮只输出两行：\n思考：<一句话>\n行动：工具名({\"参数\":\"值\"})\n"
       "信息足够时输出：行动：finish")
Q = "水稻叶子发黄怎么办？"

for m in MODELS:
    os.environ["WBCS_MODEL"] = m
    t = time.time()
    try:
        r = llm_client.chat([{"role": "system", "content": SYS},
                             {"role": "user", "content": Q}],
                            temperature=0.2, max_tokens=1200, timeout=90)
        dt = time.time() - t
        ok = ("行动" in r) and ("思考" in r)
        first = r.replace("\n", " / ")[:120]
        print("%-22s %5.1fs  长度%4d  ReAct=%s  | %s" % (m, dt, len(r), ok, first))
    except Exception as e:
        print("%-22s %5.1fs  失败: %s" % (m, time.time() - t, str(e)[:100]))
