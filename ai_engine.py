# -*- coding: utf-8 -*-
"""慧农 AI 识别引擎（真实模型版）。

识别链路
--------
    上传图片
      -> 图像预处理（缩放 / 中心裁剪 224 / ImageNet 归一化 / 5 视角测试增强）
      -> MobileNetV2 预训练主干提取 1280 维深度特征（ONNX Runtime，CPU 即可运行）
      -> 迁移学习分类头（在本项目自建数据集上训练得到的线性分类器，softmax 输出置信度）
      -> 开放集检测：嵌入与最近类中心的余弦相似度过低 -> 判为"未收录作物"，拒绝下结论
      -> 层次化决策：先判作物，再在该作物的病害集合内细分，降低跨作物误判
      -> 输出 Top-3 中文结果 + 健康判定 + 可解释性热力图

模型缺失或加载失败时自动回退到旧的手工特征引擎，保证功能不中断。
"""
import json
import os
import time

import numpy as np

import ai_labels as L
import species_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "ai_model")
ONNX = os.path.join(MODEL_DIR, "mobilenetv2-12-feat.onnx")
HEADS = os.path.join(MODEL_DIR, "heads.npz")
CLASSES = os.path.join(MODEL_DIR, "classes.json")
OOD = os.path.join(MODEL_DIR, "ood.npz")

MEAN = (np.array([0.485, 0.456, 0.406], dtype=np.float32) * 255.0)
STD = (np.array([0.229, 0.224, 0.225], dtype=np.float32) * 255.0)

_state = {"loaded": False, "ok": False, "err": "", "sess": None, "w": None, "cls": None,
          "ood_centers": None, "ood_thr": None}


# ---------------- 加载 ---------------- #

def _load():
    if _state["loaded"]:
        return _state["ok"]
    _state["loaded"] = True
    try:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        opts.intra_op_num_threads = 2
        _state["sess"] = ort.InferenceSession(ONNX, opts, providers=["CPUExecutionProvider"])
        _state["w"] = dict(np.load(HEADS))
        with open(CLASSES, encoding="utf-8") as fh:
            _state["cls"] = json.load(fh)
        if os.path.exists(OOD):  # 开放集检测参数（可选，缺失时跳过未知作物拒绝）
            z = np.load(OOD)
            _state["ood_centers"] = z["centers"].astype(np.float32)
            _state["ood_thr"] = float(z["threshold"])
        _state["ok"] = True
    except Exception as e:  # 模型缺失 / 依赖未装 -> 回退
        _state["err"] = "%s: %s" % (type(e).__name__, e)
        _state["ok"] = False
    return _state["ok"]


def available():
    return _load()


BUILD_ID = "v4.1-species/20261026"


def status():
    _load()
    return {"ok": _state["ok"], "error": _state["err"], "build": BUILD_ID,
            "onnx": os.path.exists(ONNX), "heads": os.path.exists(HEADS),
            "ood": os.path.exists(OOD)}


# ---------------- 预处理 ---------------- #

def _load_views(path, tta=True):
    """返回 (N,3,224,224) 预处理后的数组；tta=True 时为 [中心, 左上, 右上, 左下, 右下]。"""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) != 256:
        s = 256.0 / max(w, h)
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.BILINEAR)
    w, h = img.size
    size = 224
    left, top = (w - size) // 2, (h - size) // 2
    if not tta:
        boxes = [(left, top)]
    else:
        boxes = [(left, top), (0, 0), (w - size, 0), (0, h - size), (w - size, h - size)]
    out = np.empty((len(boxes), 3, size, size), dtype=np.float32)
    for i, (x, y) in enumerate(boxes):
        a = np.asarray(img.crop((x, y, x + size, y + size)), dtype=np.float32)
        a = a.transpose(2, 0, 1)
        a = (a - MEAN[:, None, None]) / STD[:, None, None]
        out[i] = a
    return out


def _embed(sess, arr):
    return sess.run(["embedding"], {"input": arr})[0].reshape(arr.shape[0], -1)


def _softmax_head(x, w_key):
    """标准化 + 线性层 + softmax（二分类时退化为 sigmoid，返回 [P(负类), P(正类)]）。"""
    w = _state["w"]
    x = (x - w[w_key + "_mean"]) / w[w_key + "_scale"]
    z = x @ w[w_key + "_w"].T + w[w_key + "_b"]
    if z.shape[1] == 1:  # 二分类（健康 / 感病）
        p1 = 1.0 / (1.0 + np.exp(-z[:, 0]))
        return np.stack([1.0 - p1, p1], axis=1)
    z = z - z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


# ---------------- 主识别 ---------------- #

def analyze(path, crop_hint=None, tta=True, explain=False):
    """识别入口。返回统一结构的结果字典。"""
    t0 = time.time()
    if not _load():
        return _legacy(path, crop_hint)

    sess, cls = _state["sess"], _state["cls"]
    views = _load_views(path, tta=tta)
    emb = _embed(sess, views).mean(axis=0, keepdims=True)

    # 开放集检测：嵌入与最近类中心的余弦相似度，过低说明"不在 38 类范围内"
    ood_sim = None
    known = True
    centers = _state.get("ood_centers")
    if centers is not None:
        e = emb / np.clip(np.linalg.norm(emb, axis=1, keepdims=True), 1e-8, None)
        ood_sim = float((e @ centers.T).max())
        known = ood_sim >= _state["ood_thr"]

    # 通道 B：作物物种识别。
    # v6 起物种通道改用「微调过的骨干」（mobilenetv2-ft-species.onnx）。它和通道 A
    # 的叶片模型不在同一嵌入空间，不能再复用 emb，必须由 species_engine 自己跑一遍
    # 骨干。代价是一次额外前向（~0.3s），换来特征更"作物专用"，拒识与准确率才拉得开。
    # 没有微调模型时自动退回共用嵌入，功能不受影响。
    species = None
    try:
        sp = species_engine.recognize(path) if species_engine.has_backbone() \
            else species_engine.predict_emb(emb)
        if isinstance(sp, dict) and sp.get("ok"):
            species = sp
    except Exception:
        species = None

    p_crop = _softmax_head(emb, "crop")[0]
    p_fine = _softmax_head(emb, "fine")[0]
    p_health = _softmax_head(emb, "health")[0]
    crop_labels = cls["crop"]
    fine_labels = cls["fine"]
    healthy_prob = float(p_health[1]) if len(p_health) > 1 else float(p_health[0])

    # 层次化：作物置信度足够高时，只在该作物的类别内重排
    ci = int(np.argmax(p_crop))
    crop_key = crop_labels[ci]
    crop_conf = float(p_crop[ci])
    order = np.argsort(-p_fine)
    if crop_conf >= 0.5:
        inside = [i for i in order if L.crop_of(fine_labels[i]) == crop_key]
        outside = [i for i in order if L.crop_of(fine_labels[i]) != crop_key]
        order = np.array(inside + outside, dtype=int)

    top = []
    for i in order[:3]:
        lab = fine_labels[i]
        top.append({"label": lab, "cn": L.cn(lab), "crop_cn": L.crop_cn(lab),
                    "conf": round(float(p_fine[i]) * 100, 1),
                    "healthy": L.is_healthy(lab),
                    "slug": L.LABEL_TO_DISEASE_SLUG.get(lab),
                    "crop_slug": L.CROP_TO_SLUG.get(L.crop_of(lab))})

    best = top[0]
    crop_pred = {"key": crop_key, "cn": L.CROP_CN.get(crop_key, crop_key),
                 "conf": round(crop_conf * 100, 1),
                 "slug": L.CROP_TO_SLUG.get(crop_key)}
    # 作物层级排序（用于展示备选）
    crop_top = []
    for i in np.argsort(-p_crop)[:3]:
        k = crop_labels[i]
        crop_top.append({"key": k, "cn": L.CROP_CN.get(k, k),
                         "conf": round(float(p_crop[i]) * 100, 1),
                         "slug": L.CROP_TO_SLUG.get(k)})

    out = {
        "engine": "onnx-mobilenetv2-transfer",
        "build": BUILD_ID,
        "ok": True,
        "known": bool(known),
        "ood_sim": round(ood_sim * 100, 1) if ood_sim is not None else None,
        "crop": crop_pred,
        "crop_top": crop_top,
        "species": species,
        "fine": best,
        "top": top,
        "healthy": bool(healthy_prob >= 0.5),
        "health_conf": round(max(healthy_prob, 1 - healthy_prob) * 100, 1),
        "healthy_prob": round(healthy_prob * 100, 1),
        "timing_ms": int((time.time() - t0) * 1000),
    }
    if not known:
        # 未收录作物：不给出病害结论，只说明"最像的已知类"供参考
        out["healthy"] = False
        out["health_conf"] = 0.0
        out["healthy_prob"] = 0.0
        for t in out["top"]:
            t["slug"] = None
        out["crop"] = None
        out["fine"] = None
        out["ood_note"] = ("图片特征与已支持的 %d 个作物类别匹配度不足（%.1f%% < 阈值 %.1f%%），"
                           "按开放集检测策略拒绝输出病害结论，避免误导用药。"
                           % (len(cls["fine"]), ood_sim * 100, _state["ood_thr"] * 100))
        # 通用视觉兜底：物种模型也没把握时，再用 ImageNet 预训练模型认一次外观
        # （只报品类不做病害诊断，命中常见果蔬时给个方向）
        if not (species and species.get("known")):
            try:
                import imagenet_aux
                out["aux"] = imagenet_aux.recognize(path)
            except Exception:
                out["aux"] = None
    if explain:
        out["heatmap"] = occlusion_map(path, sess)
    return out


def _legacy(path, crop_hint=None):
    """旧引擎兜底（手工 HSV 特征 + 人工签名比对）。"""
    try:
        import vision
        import seed_data
        f = vision.extract_features(path)
        crops = [dict(c) for c in seed_data.CROPS]
        diseases = [dict(d) for d in seed_data.DISEASES]
        m = vision.match_crop(f, crops)
        md, healthy = vision.match_disease(f, diseases, None)
        top = []
        for c, conf in (m or [])[:3]:
            top.append({"label": c["slug"], "cn": c["name"], "crop_cn": c["name"],
                        "conf": conf, "healthy": False, "slug": None, "crop_slug": c["slug"]})
        return {"engine": "legacy-hsv-signature", "ok": bool(m),
                "crop": {"key": m[0][0]["slug"], "cn": m[0][0]["name"], "conf": m[0][1],
                         "slug": m[0][0]["slug"]} if m else None,
                "crop_top": [], "fine": top[0] if top else None, "top": top,
                "healthy": bool(healthy), "health_conf": 0.0, "healthy_prob": 0.0,
                "timing_ms": 0, "fallback": _state["err"]}
    except Exception as e:
        return {"engine": "legacy-hsv-signature", "ok": False, "error": str(e)}


# ---------------- 可解释性：遮挡敏感度热力图 ---------------- #

def occlusion_map(path, sess=None, patch=36, stride=28, out="auto"):
    """黑盒可解释性：滑动遮挡，看模型置信度掉多少，掉得越多说明越看重该区域。

    返回保存后的热力图相对路径（img/ai/xxx.png，即 static/img/ai/）。
    """
    if sess is None:
        if not _load():
            return None
        sess = _state["sess"]
    try:
        from PIL import Image
        base = _load_views(path, tta=False)[0]
        p0 = _softmax_head(_embed(sess, base[None]), "fine")[0]
        target = int(np.argmax(p0))
        base_conf = float(p0[target])

        H = W = 224
        grid = []
        xs = list(range(0, H - patch + 1, stride))
        ys = list(range(0, W - patch + 1, stride))
        arrs = np.repeat(base[None], len(xs) * len(ys), axis=0)
        idx = 0
        for x in xs:
            for y in ys:
                arrs[idx, :, x:x + patch, y:y + patch] = 0.0
                idx += 1
        emb = _embed(sess, arrs)
        probs = _softmax_head(emb, "fine")[:, target]
        drop = base_conf - probs
        grid = drop.reshape(len(xs), len(ys))
        g = grid - grid.min()
        if g.max() > 0:
            g = g / g.max()

        img = Image.open(path).convert("RGB").resize((224, 224))
        import colorsys
        heat = np.zeros((224, 224, 3), dtype=np.float32)
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                v = float(g[i, j])
                r, gg, b = colorsys.hsv_to_rgb(0.66 * (1 - v), 0.9, 0.35 + 0.65 * v)
                heat[x:x + patch, y:y + patch] = (r * 255, gg * 255, b * 255)
        heat = Image.fromarray(heat.astype(np.uint8))
        merged = Image.blend(img, heat, 0.55)

        d = os.path.join(BASE_DIR, "static", "img", "ai")  # 与返回的 img/ai/xxx.png 保持一致
        os.makedirs(d, exist_ok=True)
        name = "cam_%d.png" % (int(time.time() * 1000) % 100000000)
        merged.save(os.path.join(d, name))
        return "img/ai/" + name
    except Exception:
        return None
