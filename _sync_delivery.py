# -*- coding: utf-8 -*-
"""把 D 盘主项目的最新内容全量同步到各交付副本（只覆盖，不删除目标独有文件）。"""
import os, sys, io, shutil, fnmatch, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SRC = r"D:\慧农AI智慧农业平台"

FULL = [
    ("A盘副本", r"A:\smart-agri-web", None),
    ("D交付-02项目源码", r"D:\慧农AI智慧农业平台-交付最终版\02_项目源码", None),
    ("桌面-作品源码", r"C:\Users\异乡人\Desktop\慧农AI智慧农业平台-交付最终版\作品源码", None),
]
FRONT = [
    ("D交付-01前端", r"D:\慧农AI智慧农业平台-交付最终版\01_全部前端源码"),
    ("桌面-04前端", r"C:\Users\异乡人\Desktop\慧农AI智慧农业平台-交付最终版\作品源码\04_前端源码"),
]

# --- 不进交付包的东西：缓存、运行时产物、临时脚本、数据库 ---
EXCLUDE_DIRS = {"__pycache__", ".git", "_backup_20261025", ".workbuddy", "node_modules"}
EXCLUDE_FILES = {
    "agri.db", "_diff_copies.py", "_sync_delivery.py", "_gate_test.py",
    "_shot_agent.py", "_shot_species.py", "_shot_gate.py", "_gen_charts.py",
    "_fw_allow.py", "start_logged.bat", "图片核对表.html",
    "_test_llm.py", "_bench_models.py", "_dbg_lab.py", "_val_gate.py",
    "_test_gate.py", "_smoke_deploy.py", "_stage_deploy.py",
}
EXCLUDE_PATTERNS = [
    "static/img/ai/cam_*.png",      # 运行时生成的识别热力图
    "static/uploads/*",             # 用户上传图
    "_ood_probe/*",
    "data/*.bak*", "data/*.bak2",
    "*.pyc", "*.tmp",
]


def excluded(rel):
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if parts[-1] in EXCLUDE_FILES:
        return True
    for pat in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def sync(dst, only=None):
    """only: 前缀元组，如 ('templates/', 'static/')"""
    copied = skipped = same = 0
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        rel_dir = os.path.relpath(root, SRC).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        if only and rel_dir and not rel_dir.startswith(only):
            continue
        if only and not rel_dir:
            continue
        for f in files:
            rel = (rel_dir + "/" + f) if rel_dir else f
            if excluded(rel):
                continue
            sp = os.path.join(root, f)
            tp = os.path.join(dst, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(tp), exist_ok=True)
            if os.path.exists(tp) and os.path.getsize(tp) == os.path.getsize(sp) \
               and abs(os.path.getmtime(tp) - os.path.getmtime(sp)) < 1:
                same += 1
                continue
            try:
                shutil.copy2(sp, tp)
                copied += 1
            except Exception as e:
                skipped += 1
                print("   [FAIL] %s -> %s" % (rel, e))
    return copied, skipped, same


t0 = time.time()
for name, dst, _ in FULL:
    if not os.path.isdir(dst):
        print("[跳过] %s 不存在" % name)
        continue
    c, s, m = sync(dst)
    print("[OK] %-14s 覆盖 %d 个，未变 %d 个，失败 %d 个" % (name, c, m, s))

for name, dst in FRONT:
    if not os.path.isdir(dst):
        print("[跳过] %s 不存在" % name)
        continue
    c, s, m = sync(dst, only=("templates", "static"))
    print("[OK] %-14s 覆盖 %d 个（仅前端），未变 %d 个，失败 %d 个" % (name, c, m, s))

print("elapsed %.1fs" % (time.time() - t0))
