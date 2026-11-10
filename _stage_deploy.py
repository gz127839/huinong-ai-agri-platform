# -*- coding: utf-8 -*-
"""把主项目打成一个干净的发布副本（去掉本地日志/临时脚本/备份），用于云端发布。"""
import os
import shutil
import sys

SRC = r"D:\慧农AI智慧农业平台"
DST = r"D:\_deploy_agri"

SKIP_DIRS = {"__pycache__", "_backup_20261025", "_ood_probe", ".git", "node_modules", "_gate_shots"}
SKIP_FILES = {
    "_e2e.log", "_sweep.log", "_diag.log", "_dl2.log", "_ft.log", "_ft2.log",
    "_emb.log", "_emb2.log", "_v6.log", "_v6b.log", "_v6c.log", "_dlh.log", "_dlf.log",
    "_shot_agent.py", "_shot_gate.py", "_shot_species.py", "_test_gate.py",
    "_gen_charts.py", "_fw_allow.py", "_sync_delivery.py", "_diff_copies.py",
    "图片核对表.html", "start_logged.bat", "sync_copies.bat", "手机访问放行.bat",
    "agri.db",  # 根目录下的空占位文件
}

if os.path.isdir(DST):
    shutil.rmtree(DST)

count = 0
size = 0
for root, dirs, files in os.walk(SRC):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    rel = os.path.relpath(root, SRC)
    out = DST if rel == "." else os.path.join(DST, rel)
    os.makedirs(out, exist_ok=True)
    for f in files:
        if f in SKIP_FILES or f.endswith(".log"):
            continue
        src = os.path.join(root, f)
        try:
            if os.path.getsize(src) > 60 * 1024 * 1024:
                print("跳过超大文件:", src)
                continue
        except OSError:
            continue
        shutil.copy2(src, os.path.join(out, f))
        count += 1
        size += os.path.getsize(src)

# 必要的运行时目录
os.makedirs(os.path.join(DST, "static", "uploads"), exist_ok=True)
os.makedirs(os.path.join(DST, "data"), exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("发布副本:", DST)
print("文件数 %d，体积 %.1f MB" % (count, size / 1048576))
for name in sorted(os.listdir(DST)):
    p = os.path.join(DST, name)
    if os.path.isdir(p):
        n = sum(len(fs) for _, _, fs in os.walk(p))
        print("  [dir] %-16s %d 个文件" % (name, n))
