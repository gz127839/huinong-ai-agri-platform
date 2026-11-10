# -*- coding: utf-8 -*-
"""图像识别引擎。

设计说明：
1. 本地引擎：提取上传图片的色彩/病斑/纹理特征，与知识库中每条记录的"特征签名"做加权距离
   比对，输出候选结果与置信度，完全离线可用，适合比赛现场与无网环境演示。
2. 云端引擎（可选）：若配置了环境变量 AI_API_URL，则优先调用外部 AI 接口（如百度植物识别、
   自建大模型服务），并把返回的作物/病害名称映射到本地知识库；调用失败自动回退本地引擎。

替换云端接口只需设置两个环境变量：
    AI_API_URL    接口地址（POST multipart/form-data，字段名为 image）
    AI_API_KEY    可选，Bearer 鉴权
"""
import json
import math
import os
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageFilter

# 特征权重：不同特征在比对时的重要程度
WEIGHTS = {
    "green": 1.25, "yellow": 1.00, "brown": 1.05, "red": 1.00,
    "white": 0.90, "dark": 0.95, "purple": 0.80,
    "hue": 1.00, "sat": 0.60,
}
# 不同量纲的距离缩放
SCALE = {"hue": 0.30, "sat": 22.0}
DEFAULT_SCALE = 60.0


def _hsv_arrays(img):
    """返回 hue(0~360)、sat(0~1)、val(0~1) 三个浮点数组。"""
    hsv = img.convert("HSV")
    h, s, v = [np.asarray(ch, dtype=np.float32) for ch in hsv.split()]
    hue = h * 360.0 / 255.0
    return hue, s / 255.0, v / 255.0


def extract_features(path):
    """提取图像特征。"""
    img = Image.open(path).convert("RGB")
    img.thumbnail((320, 320))
    w, h = img.size
    hue, sat, val = _hsv_arrays(img)
    total = float(hue.size)

    def ratio(mask):
        return float(np.count_nonzero(mask)) / total

    green = ratio((hue >= 75) & (hue <= 170) & (sat > 0.15) & (val > 0.18))
    yellow = ratio((hue >= 38) & (hue < 75) & (sat > 0.20) & (val > 0.35))
    brown = ratio((hue >= 8) & (hue < 45) & (sat > 0.22) & (val <= 0.68))
    red = ratio(((hue < 12) | (hue >= 330)) & (sat > 0.25) & (val > 0.2))
    purple = ratio((hue >= 240) & (hue < 330) & (sat > 0.18))
    white = ratio((sat < 0.20) & (val > 0.72))
    dark = ratio(val < 0.28)

    # 边缘密度：反映病斑轮廓与组织坏死的复杂程度
    gray = np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    edge = float(np.count_nonzero(gray > 42)) / total

    # 病斑指数：褐色 + 坏死 + 半量黄化，用于判断是否感病
    lesion = min(1.0, brown + dark + 0.5 * yellow)
    healthy = max(0.0, green - brown - dark)

    return {
        "green": round(green, 4), "yellow": round(yellow, 4), "brown": round(brown, 4),
        "red": round(red, 4), "purple": round(purple, 4), "white": round(white, 4),
        "dark": round(dark, 4), "hue": round(float(np.median(hue)), 1),
        "sat": round(float(np.mean(sat)), 3), "edge": round(edge, 4),
        "lesion": round(lesion, 4), "healthy": round(healthy, 4),
        "width": w, "height": h,
    }


def _score(features, signature):
    """特征与签名的加权距离得分，越大越接近。"""
    try:
        sig = json.loads(signature) if isinstance(signature, str) else (signature or {})
    except (ValueError, TypeError):
        sig = {}
    dist = 0.0
    for key, target in sig.items():
        if key not in WEIGHTS or key not in features:
            continue
        scale = SCALE.get(key, DEFAULT_SCALE)
        dist += WEIGHTS[key] * abs(features[key] - float(target)) * scale
    return 100.0 - dist


def _to_confidence(scores):
    """把原始得分转换成更贴近真实识别的置信度（%）。"""
    ordered = sorted(scores, key=lambda x: x[1], reverse=True)
    if not ordered:
        return []
    top, second = ordered[0][1], (ordered[1][1] if len(ordered) > 1 else ordered[0][1] - 25)
    delta = max(0.0, min(45.0, top - second))
    base = 55.0 + 41.0 * math.pow(delta / 45.0, 0.62)
    out = []
    prev = base
    for idx, (item, _) in enumerate(ordered[:3]):
        if idx == 0:
            conf = base
        else:
            conf = prev - max(4.0, delta * 0.85)
        conf = float(max(35.0, min(96.0, conf)))
        prev = conf
        out.append((item, round(conf, 1)))
    return out


def match_crop(features, crops):
    """作物识别：返回 [(crop, 置信度), ...]，最多 3 条。"""
    cloud = _cloud_match(features.get("_path", ""), "crop", crops)
    if cloud:
        return cloud
    scored = [(c, _score(features, c["signature"])) for c in crops]
    return _to_confidence(scored)


def match_disease(features, diseases, crop_id=None):
    """病虫害识别：返回 (结果列表, 是否健康)。"""
    cloud = _cloud_match(features.get("_path", ""), "disease", diseases)
    if cloud:
        return cloud, False

    # 健康判定：绿色占比高且病斑指数低，判定为未见明显病斑
    is_healthy = features["green"] >= 0.42 and features["lesion"] <= 0.22
    pool = diseases
    if crop_id:
        same = [d for d in diseases if d["crop_id"] == crop_id]
        if same:
            pool = same
    scored = [(d, _score(features, d["signature"])) for d in pool]
    if is_healthy:
        # 健康图片整体下调病害得分，避免误报
        scored = [(d, s - 12) for d, s in scored]
    return _to_confidence(scored), is_healthy


# ---------------- 可选：云端 AI 接口 ---------------- #

def _cloud_match(path, kind, pool):
    """调用外部 AI 接口（若已配置），并把名称映射到本地知识库条目。"""
    url = os.environ.get("AI_API_URL")
    if not url or not path or not os.path.exists(path):
        return None
    try:  # 依赖 requests，未安装时自动回退本地引擎
        import requests
    except ImportError:
        return None
    try:
        headers = {}
        key = os.environ.get("AI_API_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
        with open(path, "rb") as f:
            resp = requests.post(url, files={"image": f}, headers=headers, timeout=15)
        data = resp.json()
    except Exception:
        return None

    names = []
    for item in data.get("results", []) or ([data] if data.get("name") else []):
        nm = str(item.get("name", "")).strip()
        if nm:
            names.append((nm, float(item.get("score", 0.8))))

    out = []
    for nm, sc in names[:5]:
        hit = None
        for p in pool:
            pname = p["name"]
            if nm == pname or nm in pname or pname in nm:
                hit = p
                break
        if hit:
            out.append((hit, round(min(96.0, max(60.0, sc * 100)), 1)))
    return out[:3] or None


def describe(features):
    """把特征翻译成人能看懂的图像分析说明，用于结果页展示。"""
    tips = []
    if features["green"] >= 0.55:
        tips.append("叶片绿色组织占比 %.0f%%，植株整体长势正常" % (features["green"] * 100))
    elif features["green"] >= 0.35:
        tips.append("叶片绿色组织占比 %.0f%%，叶色偏淡，建议关注水肥供应" % (features["green"] * 100))
    else:
        tips.append("绿色组织仅占 %.0f%%，植株可能已进入衰老期或拍摄部位非叶片" % (features["green"] * 100))

    if features["brown"] >= 0.15:
        tips.append("检出褐色坏死斑区约 %.0f%%，符合病斑特征" % (features["brown"] * 100))
    if features["dark"] >= 0.12:
        tips.append("检出深色焦枯区约 %.0f%%，存在组织坏死" % (features["dark"] * 100))
    if features["yellow"] >= 0.20:
        tips.append("黄化区域约 %.0f%%，需与缺素性黄化区分" % (features["yellow"] * 100))
    if features["white"] >= 0.10:
        tips.append("检出白色至灰白色覆盖物约 %.0f%%，疑似霉层或粉状物" % (features["white"] * 100))
    if features["red"] >= 0.20:
        tips.append("检出红色至橙红色区域约 %.0f%%，可能为果实或锈孢子堆" % (features["red"] * 100))
    if features["edge"] >= 0.22:
        tips.append("病斑边缘纹理较复杂，符合扩展型病斑特征")
    return OrderedDict([("summary", tips), ("features", features)])
