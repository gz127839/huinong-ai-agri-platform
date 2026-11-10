# -*- coding: utf-8 -*-
"""通用视觉兜底通道（ImageNet MobileNetV2 原版模型）。

主力模型（MobileNetV2 迁移学习 + 开放集拒识）只在"叶片病害照片"这一域内可靠：
它认识的是 14 种作物的叶片，不认识果实、籽粒。当主模型把一张照片判为
"非已知作物"（开放集拒绝）时，用户很可能上传的是果实/作物整体照片，
此时用 ImageNet 预训练的通用分类模型做一次兜底识别——
ImageNet 1000 类里包含黄瓜、柑橘、苹果、玉米、南瓜、草莓等常见果蔬，
这里只取与农作物相关的类别做映射，识别不到就仍维持拒识结论。
"""

import os

import numpy as np

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "ai_model", "mobilenetv2-12-imagenet.onnx")
LABELS_PATH = os.path.join(BASE_DIR, "ai_model", "imagenet_classes.txt")

# ImageNet 类别索引 -> (中文名, 平台知识库 slug；平台未收录为 None)
# 只收录与农作物/果蔬相关的类，避免把"拉布拉多犬"之类的结果报给用户。
IMAGENET_CROPS = {
    935: ("马铃薯（薯类加工品）", "potato"),
    936: ("卷心菜", None),
    937: ("西兰花", None),
    938: ("花椰菜", None),
    939: ("西葫芦", None),
    940: ("南瓜", None),
    941: ("南瓜", None),
    942: ("南瓜", None),
    943: ("黄瓜", "cucumber"),
    945: ("甜椒/番茄类果实", "pepper"),
    948: ("苹果", "apple"),
    949: ("草莓", "strawberry"),
    950: ("柑橘", "citrus"),
    951: ("柠檬", "citrus"),
    952: ("无花果", None),
    953: ("菠萝", None),
    954: ("香蕉", None),
    955: ("菠萝蜜", None),
    956: ("番荔枝", None),
    957: ("石榴", None),
    984: ("油菜", None),
    987: ("玉米", "maize"),
    998: ("禾谷类作物穗（水稻/小麦等）", None),
}

# 兜底结果可信度分档：
#   >= MIN_CONF      判定较可靠，作为"外观识别结果"直接给出
#   >= WEAK_CONF     仅作"疑似"弱提示，措辞上留余地
#   <  WEAK_CONF     宁可不给结论
MIN_CONF = 0.45
WEAK_CONF = 0.20

_session = None
_labels = None
_state = {"ok": False, "err": ""}


def _load():
    """懒加载 ImageNet 模型与标签表，失败不抛异常（返回 False）。"""
    global _session, _labels
    if _session is not None:
        return True
    if ort is None or Image is None:
        _state["err"] = "onnxruntime/Pillow 未安装"
        return False
    if not os.path.exists(MODEL_PATH):
        _state["err"] = "缺少模型文件 mobilenetv2-12-imagenet.onnx"
        return False
    try:
        _session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        with open(LABELS_PATH, encoding="utf-8") as fh:
            _labels = [l.strip() for l in fh.read().splitlines()]
        _state["ok"] = True
        return True
    except Exception as e:  # pragma: no cover
        _state["err"] = str(e)
        _session = None
        return False


def status():
    return {"ok": _state["ok"], "error": _state["err"]}


def _preprocess(path):
    img = Image.open(path).convert("RGB")
    # 与主模型一致的短边缩放 + 中心裁剪预处理
    w, h = img.size
    scale = 256.0 / min(w, h)
    img = img.resize((max(1, int(w * scale + 0.5)), max(1, int(h * scale + 0.5))),
                     Image.BILINEAR)
    w, h = img.size
    left, top = (w - 224) // 2, (h - 224) // 2
    img = img.crop((left, top, left + 224, top + 224))
    x = np.asarray(img, dtype=np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], dtype=np.float32)) \
        / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    return x.transpose(2, 0, 1)[None, ...]


def recognize(path):
    """对一张图片跑 ImageNet 通用识别。

    命中农作物相关类且置信度足够时返回：
        {"name": 中文名, "slug": 平台slug或None, "conf": 0~1,
         "enet": 英文类名}
    否则返回 None（调用方维持原判）。
    """
    if not _load():
        return None
    try:
        x = _preprocess(path)
        logits = _session.run(["output"], {"input": x})[0][0].astype(np.float32)
        logits -= logits.max()
        p = np.exp(logits)
        p /= p.sum()
        order = np.argsort(p)[::-1]
        top1 = int(order[0])
        if top1 not in IMAGENET_CROPS:
            return None
        # 再看 top3 里有没有其他农作物类，取其中最高者，避免真实类是
        # top2/top3（与犬类等高占位类竞争）时被 top1 挤掉
        best = None
        for idx in order[:5]:
            if int(idx) in IMAGENET_CROPS:
                name, slug = IMAGENET_CROPS[int(idx)]
                conf = float(p[int(idx)])
                if best is None or conf > best[2]:
                    best = (name, slug, conf, _labels[int(idx)])
        if best is None or best[2] < WEAK_CONF:
            return None
        name, slug, conf, enet = best
        return {"name": name, "slug": slug, "conf": round(conf, 4),
                "enet": enet, "channel": "imagenet",
                "maybe": bool(conf < MIN_CONF)}
    except Exception as e:  # pragma: no cover
        _state["err"] = str(e)
        return None
