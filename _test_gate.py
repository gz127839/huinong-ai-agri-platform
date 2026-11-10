# -*- coding: utf-8 -*-
"""端到端验收 v5：把「拒识」和「判错」分开统计。"""
import io, json, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\慧农AI智慧农业平台")
os.chdir(r"D:\慧农AI智慧农业平台")

import ai_engine
import species_engine

NEG = r"D:\_ai_dataset\raw_neg"
POS = r"D:\_ai_dataset\raw"
CN = {"banana": "香蕉", "cabbage": "甘蓝", "chicabbage": "白菜", "cotton": "棉花",
      "eggplant": "茄子", "onion": "洋葱", "peach": "桃", "peanut": "花生",
      "pear": "梨", "sugarcane": "甘蔗", "sunflower": "向日葵", "watermelon": "西瓜"}
SP_CN = {"rice": "水稻", "wheat": "小麦", "maize": "玉米", "tomato": "番茄",
         "cucumber": "黄瓜", "potato": "马铃薯", "apple": "苹果", "citrus": "柑橘",
         "grape": "葡萄", "pepper": "辣椒", "tea": "茶树", "strawberry": "草莓",
         "soybean": "大豆", "rapeseed": "油菜"}

N_PER = int(os.environ.get("N", "12"))


def files_of(root, slug):
    d = os.path.join(root, slug)
    fs = sorted([os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jpg")])
    step = max(1, len(fs) // N_PER)
    return fs[::step][:N_PER]


print("engine ai=%s species=%s" % (ai_engine.available(), species_engine.available()))
st = species_engine.status()
print("delta=%.2f nn_thr=%.3f T=%.2f" % (st["unk_threshold"], st["nn_threshold"], st["temperature"]))
print("-" * 78)

print("【A】未收录作物 —— 期望拒识")
rej = tot = 0
for s, cn in CN.items():
    fs = files_of(NEG, s)
    hit = sum(1 for p in fs
              if not ((ai_engine.analyze(p) or {}).get("species") or {}).get("known", True))
    rej += hit; tot += len(fs)
    print("  %-11s %-4s %2d 张  拒识 %5.1f%%" % (s, cn, len(fs), hit / max(len(fs), 1) * 100))
print("  >> 未收录作物拒识率 %.1f%%（%d/%d）" % (rej / max(tot, 1) * 100, rej, tot))

print("\n【B】已收录作物 —— 三项分开统计")
n = acc = rj = wrong = 0
for s, cn in SP_CN.items():
    fs = files_of(POS, s)
    a = r = 0
    for p in fs:
        sp = (ai_engine.analyze(p) or {}).get("species") or {}
        n += 1
        if not sp.get("known", True):
            r += 1; rj += 1
        elif sp.get("slug") == s:
            a += 1; acc += 1
        else:
            wrong += 1
    print("  %-11s %-4s %2d 张  判对 %5.1f%%  被拒 %5.1f%%  判错 %5.1f%%"
          % (s, cn, len(fs), a / max(len(fs), 1) * 100, r / max(len(fs), 1) * 100,
             (len(fs) - a - r) / max(len(fs), 1) * 100))
print("  >> 判对 %.1f%% | 误拒 %.1f%% | 判错 %.1f%%（合计 %d 张）"
      % (acc / n * 100, rj / n * 100, wrong / n * 100, n))
print("  >> 放行样本准确率 %.1f%%（判对 / 未被拒）" % (acc / max(acc + wrong, 1) * 100))
