# -*- coding: utf-8 -*-
"""作物物种识别引擎（实景照片版，v5 可拒识）。

为什么需要它
------------
叶片病害模型（ai_engine）只在实验室条件下拍摄的作物**叶片**上训练过，
覆盖范围有限，遇到用户实际拍摄的田间照、果实照、整株照会触发开放集拒识。
本引擎在 iNaturalist 研究级鉴定实景照片上训练，直接回答"这是什么作物"，
覆盖知识库全部 14 种作物（含叶片模型完全没学过的水稻 / 小麦 / 茶树 / 油菜 / 黄瓜）。

v5 相比 v4 的关键改动（修复"未收录作物被强行配对"）
-------------------------------------------------
v4 用「14 类 softmax 置信度 + 类中心余弦相似度」双门控，两个阈值都是在
已收录作物上调出来的，对没见过的作物几乎不起拦挡作用——实测 12 种未收录
作物（梨/桃/香蕉/白菜/甘蔗/向日葵等 712 张实景照）有 91.2% 被强行判成
库里某个作物（白菜→油菜 100%、桃→苹果 96.7%、甘蔗→玉米 96.7%）。

v5 的做法：
  1. 采集 12 种平台未收录作物共 712 张实景照，作为第 15 类「未收录/其他」
     参与训练 —— 拒识由"拍脑袋定阈值"变成"模型自己学出来的判别"；
  2. 1-NN 余弦距离兜底：与训练集所有样本的最近邻相似度低于阈值即拒识，
     用来挡住训练集里根本没见过的东西（非植物、极端构图等）；
  3. 拒识偏置 δ 与 1-NN 阈值在校准集上联合搜索，控制已收录作物误拒率；
  4. 温度标定（T≈3）把虚高的置信度拉回真实水平，避免"93%  confidently wrong"。

模型文件缺失时 available() 返回 False，系统自动跳过该通道。
"""
import json
import os

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "ai_model")
HEADS = os.path.join(MODEL_DIR, "species_heads.npz")
OOD = os.path.join(MODEL_DIR, "species_ood.npz")
CLS = os.path.join(MODEL_DIR, "species_classes.json")
# v6：专门为物种通道微调过的骨干（输出 1280 维嵌入）。缺失则退回共享 ai_engine 的嵌入。
FT_ONNX = os.path.join(MODEL_DIR, "mobilenetv2-ft-species.onnx")

# slug -> 知识库中文名（与 data/agri.db crops.slug 保持一致）
SPECIES_CN = {
    "rice": "水稻", "wheat": "小麦", "maize": "玉米", "tomato": "番茄",
    "cucumber": "黄瓜", "potato": "马铃薯", "apple": "苹果", "citrus": "柑橘",
    "grape": "葡萄", "pepper": "辣椒", "tea": "茶树", "strawberry": "草莓",
    "soybean": "大豆", "rapeseed": "油菜",
}

_state = {"loaded": False, "ok": False, "err": "", "w": None, "slugs": None,
          "centers": None, "thr": None, "train_emb": None, "emb_mean": None,
          "emb_scale": None, "delta": 0.0, "nn_thr": 0.0, "temp": 1.0,
          "maybe_conf": 0.5, "eval": {}, "ft_sess": None, "ft_loaded": False}


def has_backbone():
    """是否有专用于物种通道的微调骨干。"""
    return os.path.exists(FT_ONNX)


def _ft_session():
    if _state["ft_loaded"]:
        return _state["ft_sess"]
    _state["ft_loaded"] = True
    try:
        import onnxruntime as ort
        o = ort.SessionOptions()
        o.log_severity_level = 3
        _state["ft_sess"] = ort.InferenceSession(
            FT_ONNX, o, providers=["CPUExecutionProvider"])
    except Exception as e:
        _state["ft_sess"] = None
        _state["ft_err"] = "%s: %s" % (type(e).__name__, e)
    return _state["ft_sess"]


def _load():
    if _state["loaded"]:
        return _state["ok"]
    _state["loaded"] = True
    try:
        w = dict(np.load(HEADS))
        meta = json.load(open(CLS, encoding="utf-8"))
        _state["w"] = w
        _state["slugs"] = list(meta["slugs"])
        _state["delta"] = float(meta.get("delta", 0.0))
        _state["nn_thr"] = float(meta.get("nn_thr", 0.0))
        _state["temp"] = float(meta.get("temperature", 1.0))
        _state["maybe_conf"] = float(meta.get("maybe_conf", 0.5))
        _state["eval"] = meta.get("eval", {})
        _state["gate"] = meta.get("gate") or {}
        z = np.load(OOD)
        _state["centers"] = z["centers"].astype(np.float32)
        _state["thr"] = float(z["centers"].shape[0])  # 占位，保持接口
        # v7 三重分位融合的基准（三个信号在已收录验证集上的分位分布）
        for k, arr in (("basis_punk", "basis_punk"), ("basis_energy", "basis_energy"),
                       ("basis_nn", "basis_nn")):
            if arr in z:
                _state[k] = np.sort(z[arr].astype(np.float32))
        if "train_emb" in z:
            _state["train_emb"] = z["train_emb"].astype(np.float32)
            _state["emb_mean"] = z["emb_mean"].astype(np.float32)
            _state["emb_scale"] = z["emb_scale"].astype(np.float32)
            # 参考集必须与查询向量在同一空间：先标准化，再单位化
            # （早期版本漏了标准化，导致 nn_sim 被系统性压低、过度拒识）
            e = (_state["train_emb"] - _state["emb_mean"]) / _state["emb_scale"]
            _state["train_unit"] = e / np.clip(np.linalg.norm(e, axis=1, keepdims=True), 1e-8, None)
        _state["ok"] = True
    except Exception as e:
        _state["err"] = "%s: %s" % (type(e).__name__, e)
        _state["ok"] = False
    return _state["ok"]


def available():
    return _load()


def status():
    _load()
    return {"ok": _state["ok"], "error": _state["err"],
            "classes": _state["slugs"] or [],
            "unk_threshold": _state["delta"], "nn_threshold": _state["nn_thr"],
            "temperature": _state["temp"], "eval": _state["eval"]}


def _unit(a):
    return a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-8, None)


def predict_emb(emb):
    """emb: (1,1280) 已由 ai_engine 提取好的深度特征。返回物种识别结果。

    known=False 表示"平台未收录/无法确认"，调用方应走拒识分支，
    绝不能拿 top1 去匹配知识库条目。
    """
    if not _load():
        return {"ok": False, "error": _state["err"]}
    w = _state["w"]
    slugs = _state["slugs"]
    n_crop = len(slugs)
    x = np.asarray(emb, dtype=np.float32).reshape(1, -1)
    xs = (x - w["mean"]) / w["scale"]
    z = xs @ w["w"].T + w["b"]

    # 第 15 类「未收录」的拒识偏置
    z15 = z.copy()
    if z15.shape[1] > n_crop:
        z15[:, n_crop] += _state["delta"]
    z15 -= z15.max(axis=1, keepdims=True)
    p15 = np.exp(z15)
    p15 /= p15.sum(axis=1, keepdims=True)
    p_unk = float(p15[0, n_crop]) if p15.shape[1] > n_crop else 0.0

    # 温度标定后的作物类条件概率
    zc = z[:, :n_crop] / max(_state["temp"], 1e-6)
    zc -= zc.max(axis=1, keepdims=True)
    pc = np.exp(zc)
    pc /= pc.sum(axis=1, keepdims=True)
    pc = pc[0]

    # 开放集证据：类原型相似度 + 1-NN 相似度
    sim = float((_unit(x) @ _unit(_state["centers"]).T).max())
    nn_sim = None
    if _state.get("train_unit") is not None:
        e = (x - _state["emb_mean"]) / _state["emb_scale"]
        nn_sim = float((_unit(e) @ _state["train_unit"].T).max())

    # 能量分数：logsumexp(作物类 logits)，越大表示越"像"某个已收录作物
    zc_raw = z[:, :n_crop]
    energy = float(np.log(np.exp(zc_raw - zc_raw.max()).sum()) + zc_raw.max())

    order = np.argsort(-pc)
    top = []
    for i in order[:3]:
        slug = slugs[i]
        top.append({"slug": slug, "cn": SPECIES_CN.get(slug, slug),
                    "conf": round(float(pc[i]) * 100, 1)})
    best = top[0]
    conf = float(pc[order[0]])

    # ---- 判定：v7 三重分位融合（量纲统一，避免某一路独裁）----
    gate = _state.get("gate") or {}
    fuse_score = None
    reasons = []
    if all(_state.get(k) is not None for k in ("basis_punk", "basis_energy", "basis_nn")) \
            and nn_sim is not None:
        def pct(basis, v):
            return float(np.searchsorted(basis, v, side="right")) / len(basis)
        s_punk = pct(_state["basis_punk"], -p_unk)           # 未收录概率越高，分位越低
        s_energy = pct(_state["basis_energy"], energy)        # 作物类总分越高越像已收录
        s_nn = pct(_state["basis_nn"], nn_sim)
        fuse_score = round((s_punk + s_energy + s_nn) / 3.0, 4)
        known = fuse_score >= float(gate.get("fuse_thr", 0.08))
        if not known:
            if s_punk < 0.5:
                reasons.append("判别式判为未收录（未收录概率 %.0f%%）" % (p_unk * 100))
            if s_energy < 0.5:
                reasons.append("分类得分偏低（能量分位 %.0f%%），不属于任何已收录作物" % (s_energy * 100))
            if s_nn < 0.5:
                reasons.append("与已收录样本的最近邻相似度 %.2f（分位 %.0f%%）"
                               % (nn_sim, s_nn * 100))
            if not reasons:
                reasons.append("三重证据综合判定不属于已收录作物（融合分位 %.2f，阈值 %.2f）"
                               % (fuse_score, float(gate.get("fuse_thr", 0.08))))
    else:
        # 老模型 / 缺少基准时退回双门控
        if p_unk > 0.5:
            reasons.append("判别式判为未收录（未收录概率 %.0f%%）" % (p_unk * 100))
        if nn_sim is not None and nn_sim < _state["nn_thr"]:
            reasons.append("与已收录样本的最近邻相似度 %.2f 低于阈值 %.2f"
                           % (nn_sim, _state["nn_thr"]))
        known = not reasons

    return {"ok": True, "known": known, "slug": best["slug"], "cn": best["cn"],
            "fuse_score": fuse_score,
            "fuse_thr": float(gate.get("fuse_thr", 0.08)) if fuse_score is not None else None,
            "conf": conf, "conf_pct": best["conf"],
            "sim": round(sim * 100, 1),
            "nn_sim": round(nn_sim, 3) if nn_sim is not None else None,
            "nn_thr": round(_state["nn_thr"], 3),
            "unk_prob": round(p_unk * 100, 1),
            "maybe": bool(conf < _state["maybe_conf"]),
            "top": top, "reject_reasons": reasons,
            "channel": "inat-species-mobilenetv2-v5"}


MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _views(path, tta=True):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    # 与训练/验证保持一致：torchvision 的 Resize(256) 缩的是短边，再中心裁 224
    if min(w, h) != 256:
        s = 256.0 / min(w, h)
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.BILINEAR)
    w, h = img.size
    size = 224
    left, top = (w - size) // 2, (h - size) // 2
    boxes = [(left, top)] if not tta else \
        [(left, top), (0, 0), (w - size, 0), (0, h - size), (w - size, h - size)]
    out = np.empty((len(boxes), 3, size, size), dtype=np.float32)
    for i, (x, y) in enumerate(boxes):
        # 注意：这个骨干是从 torchvision 导出的，输入约定是 0~1（必须 /255）。
        # 叶片通道的 mobilenetv2-12.onnx 用的是 0~255 约定，两者不能混用。
        a = np.asarray(img.crop((x, y, x + size, y + size)), dtype=np.float32) / 255.0
        a = a.transpose(2, 0, 1)
        out[i] = (a - MEAN[:, None, None]) / STD[:, None, None]
    return out


def recognize(path, tta=False):
    """独立入口：自己过一遍骨干网络再分类。

    默认单视角（中心裁剪）——微调时验证集就是这么算的，多视角平均反而
    偏离训练分布。除非显式传 tta=True，否则不做 TTA。

    优先用物种通道专属的微调骨干；没有微调模型时退回 ai_engine 的共享骨干，
    保证老环境也能跑（此时 predict_emb 的权重也是在同一空间训练的老版本）。
    """
    sess = _ft_session() if has_backbone() else None
    if sess is None:
        try:
            import ai_engine
            if not ai_engine.available():
                return {"ok": False, "error": "backbone unavailable"}
            views = ai_engine._load_views(path, tta=tta)
            emb = ai_engine._embed(ai_engine._state["sess"], views).mean(axis=0, keepdims=True)
            return predict_emb(emb)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    try:
        arr = _views(path, tta=tta)
        emb = sess.run(["embedding"], {"input": arr})[0].reshape(arr.shape[0], -1).mean(
            axis=0, keepdims=True)
        r = predict_emb(emb)
        if isinstance(r, dict):
            r["backbone"] = "mobilenetv2-finetuned"
        return r
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
