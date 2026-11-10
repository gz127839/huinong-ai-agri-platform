# -*- coding: utf-8 -*-
"""生成 AI 能力实验室所需的评测图表（纯 PIL，无 matplotlib 依赖）。"""
import os, json, sys
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFont

PROJ = r"D:\慧农AI智慧农业平台"
FONT = r"C:\Windows\Fonts\msyh.ttc"
OU = os.path.join(PROJ, "static", "img", "ai")
os.makedirs(OU, exist_ok=True)

BG = (255, 255, 255)
FG = (33, 43, 38)
SUB = (106, 122, 114)
GRID = (226, 233, 229)
GREEN = (34, 139, 87)
GREEN_L = (122, 189, 152)
BLUE = (56, 120, 190)
ORANGE = (217, 132, 48)
RED = (197, 74, 62)


def f(sz, bold=False):
    p = r"C:\Windows\Fonts\msyhbd.ttc" if bold else FONT
    return ImageFont.truetype(p, sz)


def text_w(dr, s, ft):
    return dr.textbbox((0, 0), s, font=ft)[2]


def new(w, h, title, subtitle=None):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.text((28, 22), title, font=f(24, True), fill=FG)
    y = 56
    if subtitle:
        d.text((28, y), subtitle, font=f(15), fill=SUB)
        y += 26
    return img, d, y


def hbar(d, x, y, w, h, pct, color, label=None, val=None, fontsize=15):
    """画一条横向条形"""
    d.rectangle([x, y, x + w, y + h], outline=GRID, fill=(248, 250, 249))
    fw = max(2, int(w * max(0.0, min(1.0, pct))))
    d.rectangle([x, y, x + fw, y + h], fill=color)
    if val:
        ft = f(fontsize)
        tx = x + fw + 8 if fw < w * 0.72 else x + fw - text_w(d, val, ft) - 8
        d.text((tx, y + (h - fontsize) // 2 - 1), val, font=ft,
               fill=(255, 255, 255) if fw >= w * 0.72 else FG)


bench = json.load(open(os.path.join(PROJ, "ai_model", "benchmark.json"), encoding="utf-8"))
stages = bench["stages"]

# ---------------- 1. ladder.png 准确率提升阶梯 ----------------
W, H = 1080, 560
img, d, top = new(W, H, "作物识别准确率提升阶梯（同一测试集 10,858 张）",
                  "每根柱子是一次改动的真实评测结果，数值为测试集 Top-1 准确率")
rows = [
    ("V0 项目原版 · 手写特征 + 人工签名", stages[0]["crop"], stages[0]["fine"], RED),
    ("V1 保留手工特征 · 换成 SVM 分类器", stages[1]["crop"], stages[1]["fine"], ORANGE),
    ("V2 MobileNetV2 迁移学习", stages[2]["crop"], stages[2]["fine"], BLUE),
    ("V3 + 增强训练 / TTA / 层次化决策", stages[3]["crop"], stages[3]["fine"], GREEN),
]
x0, bw, bh, gap = 28, 700, 34, 30
y = top + 16
for name, crop, fine, col in rows:
    d.text((x0, y), name, font=f(16), fill=FG)
    yy = y + 24
    # 作物识别
    d.text((x0 + 4, yy + 6), "作物", font=f(13), fill=SUB)
    hbar(d, x0 + 44, yy, bw, bh, crop, GREEN_L if col is not GREEN else GREEN,
         val="%.1f%%" % (crop * 100))
    d.text((x0 + 44, yy + bh + 3), "病害", font=f(13), fill=SUB)
    hbar(d, x0 + 44, yy + bh + 6, bw, bh, fine, col, val="%.1f%%" % (fine * 100))
    y = yy + bh * 2 + 6 + gap
d.line([(x0, y - gap + 4), (W - 28, y - gap + 4)], fill=GRID)
d.text((x0, y + 6), "作物识别 3.7% → 99.0%（+95.3 个百分点）；健康判定 +25.4 个百分点",
       font=f(16, True), fill=GREEN)
p = os.path.join(OU, "ladder.png")
img.save(p)
print("saved", p)

# ---------------- 2. robust.png 田间扰动集 ----------------
W, H = 1080, 470
img, d, top = new(W, H, "田间实拍扰动集对比（3,000 张万图）",
                  "标准图已经接近饱和，换模拟田间拍摄的图才看得出真实差距")
pert = bench["pert"]
groups = [("V2 迁移学习基线", pert["crop"]["v2"], pert["fine"]["v2"], RED),
          ("V2 + 五视角 TTA", pert["crop"]["v2_tta"], pert["fine"]["v2_tta"], ORANGE),
          ("V3 增强训练（最终）", pert["crop"]["v3"], pert["fine"]["v3"], GREEN)]
x0, bw, bh = 28, 620, 40
y = top + 20
for name, crop, fine, col in groups:
    d.text((x0, y), name, font=f(16), fill=FG)
    d.text((x0 + 4, y + 26), "作物", font=f(13), fill=SUB)
    hbar(d, x0 + 44, y + 24, bw, bh, crop, GREEN_L if col is not GREEN else GREEN,
         val="%.1f%%" % (crop * 100))
    d.text((x0 + 4, y + 26 + bh + 4), "病害", font=f(13), fill=SUB)
    hbar(d, x0 + 44, y + 26 + bh + 4, bw, bh, fine, col, val="%.1f%%" % (fine * 100))
    y += 26 + bh * 2 + 26
d.line([(x0, y - 6), (W - 28, y - 6)], fill=GRID)
d.text((x0, y + 8), "扰动集病害准确率 81.3% → 94.6%，提升 13.4 个百分点",
       font=f(16, True), fill=GREEN)
p = os.path.join(OU, "robust.png")
img.save(p)
print("saved", p)

# ---------------- 3. errors.png 主要错误模式 ----------------
errs = sorted(bench["errors"], key=lambda e: -e["n"])[:8]
W, H = 1080, 120 + len(errs) * 46
img, d, top = new(W, H, "主要错误模式（按错判张数排序）",
                  "全部来自测试集判错样本；看懂错在哪，才知道下一步改什么")
mx = max(e["n"] for e in errs)
y = top + 14
for e in errs:
    lbl = "%s → %s" % (e["true_cn"], e["pred_cn"])
    d.text((28, y + 8), lbl, font=f(15), fill=FG)
    hbar(d, 340, y + 4, 560, 26, e["n"] / mx, RED, val="%d 张" % e["n"])
    y += 46
p = os.path.join(OU, "errors.png")
img.save(p)
print("saved", p)

# ---------------- 4. cm.png 物种识别混淆矩阵 ----------------
sp = json.load(open(os.path.join(PROJ, "ai_model", "species_classes.json"), encoding="utf-8"))
cm = sp.get("cm")
slugs = sp.get("slugs")
CN = {"rice": "水稻", "maize": "玉米", "wheat": "小麦", "cucumber": "黄瓜",
      "tomato": "番茄", "potato": "马铃薯", "pepper": "辣椒", "citrus": "柑橘",
      "soybean": "大豆", "strawberry": "草莓", "grape": "葡萄", "tea": "茶树",
      "rapeseed": "油菜", "apple": "苹果"}
if cm and slugs:
    n = len(slugs)
    cell = 52
    pad_l, pad_t = 96, 110
    W = pad_l + cell * n + 150
    H = pad_t + cell * n + 90
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((28, 22), "实景物种识别混淆矩阵（14 类 / 留出集）", font=f(24, True), fill=FG)
    d.text((28, 58), "行=真实作物，列=模型输出；对角线越深说明判得越准", font=f(15), fill=SUB)
    # 列表头
    for j, s in enumerate(slugs):
        nm = CN.get(s, s)
        ft = f(14)
        w = text_w(d, nm, ft)
        d.text((pad_l + cell * j + (cell - w) / 2, pad_t - 26), nm, font=ft, fill=FG)
    for i, s in enumerate(slugs):
        nm = CN.get(s, s)
        ft = f(14)
        w = text_w(d, nm, ft)
        d.text((pad_l - w - 10, pad_t + cell * i + (cell - 16) / 2), nm, font=ft, fill=FG)
        row = cm[i]
        tot = sum(row) or 1
        for j in range(n):
            v = row[j] / tot
            col = tuple(int(o + (255 - o) * (1 - v)) for o in (34, 139, 87))
            if v < 0.06:
                col = (250, 250, 249)
            x = pad_l + cell * j
            y = pad_t + cell * i
            d.rectangle([x, y, x + cell - 2, y + cell - 2], fill=col,
                        outline=(240, 244, 242))
            if row[j] > 0 and v >= 0.06:
                t = "%d" % row[j]
                ft = f(13, v > 0.5)
                tw = text_w(d, t, ft)
                d.text((x + (cell - 2 - tw) / 2, y + cell / 2 - 10), t, font=ft,
                       fill=(255, 255, 255) if v > 0.4 else FG)
    d.text((28, pad_t + cell * n + 20),
           "总体准确率 %.1f%%（训练 %.1f%% / 验证 %.1f%%）"
           % (sp["acc"]["test"] * 100, sp["acc"]["train"] * 100, sp["acc"]["val"] * 100),
           font=f(16, True), fill=GREEN)
    d.text((28, pad_t + cell * n + 48),
           "主要混淆：草地/绿叶背景下的禾本科作物（水稻、小麦、玉米）与同为绿色小叶的茶、油菜互相干扰",
           font=f(14), fill=SUB)
    p = os.path.join(OU, "cm.png")
    img.save(p)
    print("saved", p)
else:
    print("no cm data in species_classes.json")

print("all done ->", OU)
for fn in sorted(os.listdir(OU)):
    if fn in ("ladder.png", "robust.png", "errors.png", "cm.png"):
        print(" ", fn, os.path.getsize(os.path.join(OU, fn)), "bytes")
