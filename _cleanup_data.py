# -*- coding: utf-8 -*-
"""清理数据库中的测试残留：商品 15/16（后台审核测试）、全部购物车条目。

执行前自动备份为 data/agri.db.bak_cleanup_<时间戳>。
"""
import io
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "agri.db")
BAK = DB + ".bak_cleanup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(DB, BAK)
print("备份:", os.path.basename(BAK))

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

print("\n清理前:")
for r in c.execute("SELECT id,name,farmer_name,status FROM products WHERE id>14"):
    print("  商品", r["id"], r["name"], "|", r["farmer_name"], "|", r["status"])

# 1) 删除 id>14 的测试商品（仅在 name 与 farmer_name 与 seed 数据无关时安全，这里按 id 即可）
c.execute("DELETE FROM products WHERE id > 14")

# 2) 清空购物车（全部为历史测试条目）
n_cart = c.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0]
c.execute("DELETE FROM cart_items")
print("\n清理购物车条目:", n_cart)

c.commit()

print("\n清理后:")
print("  商品数:", c.execute("SELECT COUNT(*) FROM products").fetchone()[0])
print("  购物车:", c.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0])
print("  作物/病害/用户:",
      c.execute("SELECT COUNT(*) FROM crops").fetchone()[0],
      c.execute("SELECT COUNT(*) FROM diseases").fetchone()[0],
      c.execute("SELECT COUNT(*) FROM users").fetchone()[0])
c.close()
