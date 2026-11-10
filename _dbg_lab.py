# -*- coding: utf-8 -*-
"""本地复现 /ai-lab 的 500：用假 status 模拟云端（模型可用）的状态，拿完整 traceback。"""
import io
import json
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\慧农AI智慧农业平台")

import app as A
import species_engine

meta = json.load(open(r"D:\慧农AI智慧农业平台\ai_model\species_classes.json", encoding="utf-8"))
stub = {"loaded": True, "ok": True, "eval": meta.get("eval", {}),
        "gate": {}, "classes": [c["slug"] for c in meta.get("classes", [])]}

species_engine.available = lambda: True
species_engine.status = lambda: stub
species_engine.has_backbone = lambda: True

A.app.config["PROPAGATE_EXCEPTIONS"] = True
c = A.app.test_client()
with c.session_transaction() as s:
    s["user_id"] = 3
    s["username"] = "demo"

try:
    r = c.get("/ai-lab")
    print("status", r.status_code, "bytes", len(r.data))
except Exception:
    traceback.print_exc()
