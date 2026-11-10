# -*- coding: utf-8 -*-
"""验收：引擎拒识判定是否与离线校准一致（修复 s_punk 方向后）。"""
import io
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\慧农AI智慧农业平台")
import os

os.chdir(r"D:\慧农AI智慧农业平台")
import species_engine

species_engine.available()
D = r"D:\_ai_dataset"


def reject_rate(X):
    r = [species_engine.predict_emb(X[i:i + 1]) for i in range(len(X))]
    return 100.0 * np.mean([not x.get("known", True) for x in r])


z = np.load(os.path.join(D, "emb_ft.npz"), allow_pickle=True)
X, y = z["X"], z["y"]
sys.path.insert(0, r"D://_ai_dataset"); import train_species as TS
tr, va, te = TS.split(y)

print("已收录 val  n=%4d 拒识 %.1f%%" % (len(va), reject_rate(X[va])))
print("已收录 test n=%4d 拒识 %.1f%%" % (len(te), reject_rate(X[te])))
zn = np.load(os.path.join(D, "emb_ft_neg.npz"), allow_pickle=True)
print("参与训练的未收录 n=%4d 拒识 %.1f%%" % (len(zn["X"]), reject_rate(zn["X"])))
zh = np.load(os.path.join(D, "emb_ft_holdout.npz"), allow_pickle=True)
print("完全未见的留出物种 n=%4d 拒识 %.1f%%" % (len(zh["X"]), reject_rate(zh["X"])))

# 样本级：香蕉图
bn = np.load(os.path.join(D, "emb_ft_neg.npz"), allow_pickle=True)
i = int(np.where(bn["labels"] == 0)[0][0])
r = species_engine.predict_emb(bn["X"][i:i + 1])
print("香蕉样例:", {k: r.get(k) for k in ("known", "cn", "conf", "fuse_score", "unk_prob", "nn_sim")})
