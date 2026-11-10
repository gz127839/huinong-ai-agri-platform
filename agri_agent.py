# -*- coding: utf-8 -*-
"""慧农 AI 农业智能体（AgriAgent）——会规划、会调工具、会看结果的闭环。

与"问答助手（RAG）"的本质区别
--------------------------------
问答助手是单向的：检索一次 -> 让大模型说一段话 -> 结束。
智能体是闭环的：拿到目标后自己决定"先做什么、再做什么"，每调一次工具
就把返回结果拿回来观察，据此调整下一步，直到能给出可执行方案为止。

    目标 ->【规划】-> 调工具 ->【观察结果】-> 再规划 -> ... -> 汇总 -> 可执行方案
              ^                                    |
              +------------------------------------+   （反馈回路）

本项目把平台已有的能力全部包装成标准工具，交给智能体按需调用：

    recognize_image   图像识别（叶片病害模型 / 实景物种模型 / ImageNet 兜底）
    crop_profile      作物档案（适种区域、生长习性、种植管理要点）
    query_disease     病害防治方案（症状、用药、安全间隔期、田间整改）
    search_knowledge  知识库模糊检索（RAG 召回，兜底用）
    list_products     农资与农产品（价格、库存、产地）

降级设计（重要）
----------------
没有配置大模型接口时，智能体不会"罢工"，而是切换到内置的规则规划器：
按问题语义与图像识别结果自动编排工具调用顺序，并用模板汇总成建议。
这样在没有 Key 的评审环境里，智能体的规划—执行—观察链路仍然完整可见。

配置（环境变量，见 .env.example）：
    AI_LLM_BASE_URL / AI_LLM_API_KEY / AI_LLM_MODEL
"""
import json
import os
import re
import time
import urllib.request

import llm_client

MAX_STEPS = 6          # 单轮最多推理步数，防止死循环
OBS_CHARS = 700        # 单条观察结果喂给模型的最大字符数


# ============================================================ 工具层

def _row2text(d):
    return "\n".join("%s：%s" % (k, v) for k, v in d.items() if v)


def _clip(s, n=OBS_CHARS):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + " …（已截断）"


def _fmt_obs(obs, limit=900):
    """把工具返回的 dict 压成给人看的纯文本（页面轨迹用）。"""
    if isinstance(obs, dict):
        parts = []
        data = obs.get("data")
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict):
                    parts.append("；".join("%s：%s" % (k, v) for k, v in d.items() if v))
                else:
                    parts.append(str(d))
        for k, v in obs.items():
            if k in ("data", "inputs", "ok", "count"):
                continue
            if v not in (None, "", True, False):
                parts.append("%s：%s" % (k, v))
        txt = "\n".join(parts)
    else:
        txt = str(obs)
    return txt[:limit] + (" …" if len(txt) > limit else "")


def tool_recognize_image(db, path):
    """调用平台识别引擎看图：先叶片病害模型，拒识后转实景物种模型，
    再不行走 ImageNet 通用兜底。返回结构化判定。"""
    import ai_engine
    if not path or not os.path.exists(path):
        return {"ok": False, "msg": "没有提供图片路径，跳过图像识别。"}
    if not ai_engine.available():
        return {"ok": False, "msg": "识别引擎未就绪（缺少模型文件）。"}
    r = ai_engine.analyze(path)
    out = {"ok": True, "known": r.get("known"), "相似度": r.get("ood_sim")}
    if r.get("crop"):
        out["叶片模型判定作物"] = "%s（%.1f%%）" % (
            r["crop"].get("cn") or r["crop"].get("slug"), (r["crop"].get("conf") or 0) * 100)
    if r.get("fine"):
        out["细类判定"] = "%s（%.1f%%）" % (
            r["fine"].get("cn"), (r["fine"].get("conf") or 0) * 100)
    sp = r.get("species") or {}
    if sp.get("cn"):
        out["实景物种模型"] = "%s（%s%%）%s" % (
            sp["cn"], sp.get("conf_pct"), "" if sp.get("known") else "·低置信，仅供参考")
    aux = r.get("aux") or {}
    if aux.get("name"):
        out["通用视觉兜底"] = "%s（%.1f%%）" % (aux["name"], (aux.get("conf") or 0) * 100)
    if not out.get("叶片模型判定作物") and not sp.get("cn") and not aux.get("name"):
        out["结论"] = "三通道均未给出可靠结果，图片可能不在支持范围内。"
    return out


def tool_crop_profile(db, name):
    """查作物档案：适种区域、生长习性、种植管理、经济价值。"""
    rows = db.query("SELECT name, alias, regions, seasons, habits, management, value "
                    "FROM crops WHERE name LIKE ? OR alias LIKE ? LIMIT 2",
                    ["%%%s%%" % name, "%%%s%%" % name])
    if not rows:
        return {"ok": False, "msg": "知识库中没有名为「%s」的作物档案。" % name}
    out = []
    for r in rows:
        out.append({k: v for k, v in r.items() if v})
    return {"ok": True, "count": len(out), "data": out}


def tool_query_disease(db, keyword):
    """查病害防治方案：症状识别、物理防治、用药建议、田间整改、后期预防。"""
    rows = db.query("SELECT d.name, d.dtype, c.name crop_name, d.symptoms, d.peak, "
                    "d.physical, d.chemical, d.field_mgmt, d.prevention "
                    "FROM diseases d LEFT JOIN crops c ON c.id=d.crop_id "
                    "WHERE d.name LIKE ? OR d.symptoms LIKE ? OR c.name LIKE ? LIMIT 3",
                    ["%%%s%%" % keyword, "%%%s%%" % keyword, "%%%s%%" % keyword])
    if not rows:
        return {"ok": False, "msg": "未找到与「%s」相关的病害条目。" % keyword}
    return {"ok": True, "count": len(rows), "data": [_row2text(r) for r in rows]}


def tool_search_knowledge(db, query):
    """知识库模糊检索（RAG 召回），找不到精确条目时用它兜底。"""
    import ai_assistant
    refs = ai_assistant.retrieve(db, query, top_k=4)
    if not refs:
        return {"ok": False, "msg": "知识库未检索到相关内容。"}
    return {"ok": True, "count": len(refs),
            "data": ["【%s】%s\n%s" % (r["kind"], r["title"], r["content"][:400]) for r in refs]}


def _is_input(name, category):
    """判断一条商品是不是生产资料（农药/肥料/种苗），而不是可售农产品。"""
    s = "%s%s" % (name or "", category or "")
    return ("农资" in s or "种苗" in s or
            any(k in (name or "") for k in ("剂", "肥", "药", "种苗", "种子")))


def tool_list_products(db, keyword):
    """查在售农资/农产品：名称、产地、价格、库存。用于给出可操作的采购建议。"""
    # 农资优先：问"买什么药"时，杀菌剂/肥料/种苗应排在可售农产品前面
    rows = db.query("SELECT name, category, origin, price, unit, stock, description "
                    "FROM products WHERE status='approved' AND "
                    "(name LIKE ? OR category LIKE ? OR description LIKE ?) "
                    "ORDER BY (CASE WHEN category LIKE '%农资%' OR name LIKE '%剂%' "
                    "OR name LIKE '%肥%' OR name LIKE '%种%' THEN 0 ELSE 1 END), "
                    "stock DESC LIMIT 5",
                    ["%%%s%%" % keyword, "%%%s%%" % keyword, "%%%s%%" % keyword])
    if not rows:
        rows = db.query("SELECT name, category, origin, price, unit, stock, description "
                        "FROM products WHERE status='approved' ORDER BY stock DESC LIMIT 4")
        if not rows:
            return {"ok": False, "msg": "商城暂无在售商品。"}
        return {"ok": True, "count": len(rows), "inputs": [],
                "data": ["%s | %s | ¥%s/%s | 库存%s" % (r["name"], r["origin"], r["price"],
                                                        r["unit"], r["stock"]) for r in rows],
                "note": "未命中关键词，给出的是在售列表"}

    def _line(r):
        return "%s | %s | ¥%s/%s | 库存%s | %s" % (
            r["name"], r["origin"], r["price"], r["unit"], r["stock"],
            (r["description"] or "")[:60])

    inputs = [r for r in rows if _is_input(r["name"], r["category"])]
    return {"ok": True, "count": len(rows),
            "data": [_line(r) for r in rows],
            "inputs": [_line(r) for r in inputs]}


TOOLS = {
    "recognize_image": {
        "desc": "识别一张农作物照片，回答'这是什么作物/得了什么病'。参数是图片在服务器上的绝对路径。",
        "args": {"path": "图片绝对路径（字符串）"},
        "fn": tool_recognize_image,
    },
    "crop_profile": {
        "desc": "查询某种作物的档案：适种区域、生长习性、种植管理要点、经济价值。",
        "args": {"name": "作物名（如 番茄、水稻）"},
        "fn": tool_crop_profile,
    },
    "query_disease": {
        "desc": "查询病害的防治方案：症状、发病高峰、物理防治、用药建议、田间整改、后期预防。",
        "args": {"keyword": "病害名或作物名或症状关键词"},
        "fn": tool_query_disease,
    },
    "search_knowledge": {
        "desc": "在农业知识库里做模糊检索，用于兜底查找资料。",
        "args": {"query": "检索词"},
        "fn": tool_search_knowledge,
    },
    "list_products": {
        "desc": "查询平台在售的农资/农产品与价格库存，用于给出采购建议。",
        "args": {"keyword": "商品关键词（如 杀菌剂、番茄）"},
        "fn": tool_list_products,
    },
}


def _tool_help():
    return "\n".join(
        "- %s(%s)：%s" % (n, "，".join(t["args"].keys()), t["desc"])
        for n, t in TOOLS.items())


# ============================================================ 大模型层

def _cfg():
    return llm_client.config() or {}


def llm_enabled():
    return llm_client.enabled()


def llm_model():
    """当前生效的模型名（供页面展示）。"""
    return _cfg().get("model") or ""


def llm_label():
    """当前通道说明。"""
    return _cfg().get("label") or ""


AGENT_SYSTEM = (
    "你是智慧农业平台的农业智能体，能调用工具获取真实数据后再回答。\n"
    "可用工具：\n" + _tool_help() + "\n\n"
    "工作方式（严格按此格式，每轮只输出一步）：\n"
    "思考：你当前掌握什么、还缺什么、下一步该查什么\n"
    "行动：工具名({\"参数名\": \"参数值\"})\n"
    "当你已掌握足够信息，输出：\n"
    "行动：finish\n"
    "回答：（面向农户的可执行建议，分条、通俗、不超过 400 字；"
    "纯文本，不要用 Markdown 符号；"
    "涉及用药必须提醒安全间隔期与先小面积试用）\n\n"
    "规则：\n"
    "1) 只能使用上面列出的工具，参数必须是合法 JSON；\n"
    "2) 用户没有提供图片时，绝对不要调用 recognize_image（没有文件可识别），"
    "直接从文本问题出发查知识库 / 病害防治；\n"
    "2) 涉及具体作物、病害、用药、价格的问题，必须先调工具拿真实数据，"
    "在完成至少 2 次有效工具调用前不允许 finish；\n"
    "3) 回答里的病害名称、症状、药剂和剂量必须来自工具返回，"
    "工具没给的不要凭记忆补充；确实没有就说明\"知识库未收录\"并建议咨询当地农技站；\n"
    "4) 工具没查到就换关键词或换工具，最多 6 步，不要原地重复；\n"
    "5) 回答用简体中文。"
)


def _llm_chat(messages, timeout=45):
    """调用大模型（自备 Key 优先，否则云服务免密钥通道）。"""
    return llm_client.chat(messages, temperature=0.2, max_tokens=700, timeout=timeout)


# ============================================================ 规则规划器（无 Key 降级）

CROP_WORDS_CACHE = {"names": None}


def _known_crop_names(db):
    if CROP_WORDS_CACHE["names"] is None:
        CROP_WORDS_CACHE["names"] = [r["name"] for r in db.query("SELECT name FROM crops")]
    return CROP_WORDS_CACHE["names"]


DISEASE_HINT = re.compile(r"病|斑|黄|枯|烂|霉|虫|萎|卷|死|发蔫|叶尖|腐烂|发黄")
BUY_HINT = re.compile(r"买|价格|多少.?钱|药剂|农药|杀菌|打药|施肥|种子|哪里.?买")


def _crop_from_obs(obs):
    """从识别工具的返回里抽出作物名，供后续步骤使用（观察 → 指导下一步）。"""
    if not isinstance(obs, dict):
        return None
    for k in ("叶片模型判定作物", "实景物种模型", "通用视觉兜底"):
        v = obs.get(k)
        if v:
            return re.split(r"[（(]", str(v))[0].strip()
    return None


def rule_next(db, question, image_path, state, used):
    """规则规划器：根据「当前已掌握的信息」决定下一个该调哪个工具。

    注意这里不是一次性把计划排完，而是每执行完一步、看过返回结果之后
    再重新规划下一步——识别出了作物，下一步才查这个作物的档案；
    病害条目没查到，下一步就换成模糊检索。这就是"观察驱动决策"。
    """
    q = (question or "").strip()
    crop = state.get("crop")
    if not crop:
        # 从问题文本里认作物名（"番茄早疫病..." -> 番茄）
        for n in _known_crop_names(db):
            if n and n in q:
                crop = n
                state["crop"] = crop
                break

    if image_path and "recognize_image" not in used:
        return ("recognize_image", {"path": image_path},
                "用户上传了照片，先调用识别工具看清是什么作物、有没有病害")
    if crop and "crop_profile" not in used:
        return ("crop_profile", {"name": crop},
                "已定位到作物「%s」，查它的种植管理要点" % crop)
    if (DISEASE_HINT.search(q) or state.get("from_image")) and "query_disease" not in used:
        kw = crop or q[:14]
        return ("query_disease", {"keyword": kw},
                "存在病害相关描述，查「%s」的防治方案" % kw)
    if state.get("last_miss") and "search_knowledge" not in used:
        return ("search_knowledge", {"query": q or crop or "病害防治"},
                "上一步「%s」没查到结果，改用知识库模糊检索兜底" % state["last_miss"])
    if BUY_HINT.search(q) and "list_products" not in used:
        return ("list_products", {"keyword": crop or q[:12]},
                "用户关心购买，查一下在售农资与价格")
    if "search_knowledge" not in used:
        return ("search_knowledge", {"query": q or "农业种植"},
                "未在问题中定位到具体作物/病害，先做知识库模糊检索")
    return None


def rule_summary(question, steps):
    """把工具观察结果拼成结构化建议（无大模型时的"汇总"环节）。"""
    lines, crop_name, disease_txt, product_txt = [], None, None, None
    for st in steps:
        obs = st.get("obs")
        if not isinstance(obs, dict) or not obs.get("ok"):
            continue
        if st["tool"] == "recognize_image":
            for k in ("叶片模型判定作物", "细类判定", "实景物种模型", "通用视觉兜底"):
                if obs.get(k):
                    lines.append("识别结果 · %s：%s" % (k, obs[k]))
            if obs.get("叶片模型判定作物"):
                crop_name = obs["叶片模型判定作物"].split("（")[0]
        elif st["tool"] == "crop_profile":
            d = (obs.get("data") or [{}])[0]
            if d.get("name"):
                crop_name = crop_name or d["name"]
                if d.get("management"):
                    lines.append("种植管理：%s" % _clip(d["management"], 260))
                if d.get("regions"):
                    lines.append("适种区域：%s" % _clip(d["regions"], 120))
        elif st["tool"] == "query_disease":
            txt = (obs.get("data") or [""])[0]
            disease_txt = txt
            m = re.search(r"name：(.+)", txt)
            if m:
                lines.append("匹配病害：%s" % m.group(1).strip())
            for key, label in (("symptoms", "典型症状"), ("chemical", "用药建议"),
                               ("physical", "物理防治"), ("field_mgmt", "田间整改"),
                               ("prevention", "后期预防")):
                mm = re.search(r"%s：(.+)" % key, txt)
                if mm and mm.group(1).strip():
                    lines.append("%s：%s" % (label, _clip(mm.group(1), 220)))
        elif st["tool"] == "list_products":
            # 只有生产资料（农药/肥料/种苗）才算采购建议，可售农产品不算
            inputs = obs.get("inputs") or []
            if inputs:
                lines.append("可采购农资：" + "；".join(
                    str(x).split("|")[0].strip() for x in inputs[:3]))
            else:
                lines.append("采购提示：平台暂无对应的农药/肥料在售，"
                             "请到当地农资店按需购买，严格按标签说明配制")
        elif st["tool"] == "search_knowledge":
            lines.append("知识库资料：%s" % _clip((obs.get("data") or [""])[0], 260))

    if not lines:
        return ("这一步没查到可靠资料。建议补充信息：作物名称 + 发病部位 + 症状描述，"
                "或直接咨询当地农技站。")

    chain = " → ".join(st["tool"] for st in steps if st.get("tool")) or "（未调用工具）"
    head = "智能体按「%s」的顺序完成 %d 步工具调用，结论如下：" % (chain, len(steps))
    tail = ("\n\n用药提醒：严格遵守农药安全间隔期，先小面积试用再大面积施用；"
            "本建议由智能体基于知识库自动生成，仅供参考，重要病虫害请结合田间实际复核。")
    return head + "\n" + "\n".join("· " + x for x in lines) + tail


# ============================================================ 智能体主循环

def _parse_action(text):
    """从模型输出里解析出 (工具名, 参数dict) 或 ('finish', None)。"""
    m = re.search(r"行动\s*[:：]\s*(\w+)", text or "")
    if not m:
        return None, None, "未解析到行动指令"
    name = m.group(1).strip()
    if name.lower() in ("finish", "完成", "done", "结束"):
        return "finish", None, None
    if name not in TOOLS:
        return None, None, "工具 %s 不存在" % name
    am = re.search(r"%s\s*\(\s*(\{.*?\})\s*\)" % name, text, re.S)
    args = {}
    if am:
        try:
            args = json.loads(am.group(1))
        except Exception:
            return name, None, "参数不是合法 JSON"
    return name, args, None


def _extract_final(text):
    """从最终一步的回复里取"回答："后面的正文。"""
    m = re.search(r"回答\s*[:：]\s*(.+)", text or "", re.S)
    if m:
        return m.group(1).strip()
    # 兜底：去掉思考/行动行，剩下的当正文
    body = re.sub(r"(思考|行动)\s*[:：].*", "", text or "", flags=re.S)
    return body.strip()


def run(db, question, image_path=None, history=None, use_llm=None):
    """执行智能体。

    返回 dict：
        ok        是否拿到结论
        mode      'llm' 大模型驱动 | 'rule' 规则规划（降级）
        steps     执行轨迹 [{n, thought, tool, args, obs, ok, ms}]
        answer    最终建议
        tools_used 用到的工具名列表
        elapsed_ms 总耗时
    """
    t0 = time.time()
    steps = []
    mode = "rule"
    answer = ""

    if use_llm is None:
        use_llm = llm_enabled()

    # ---------- A. 大模型驱动：规划 → 调工具 → 观察 → 再规划 ----------
    if use_llm:
        mode = "llm"
        messages = [{"role": "system", "content": AGENT_SYSTEM}]
        for h in (history or [])[-3:]:
            messages.append({"role": "user", "content": h.get("q", "")})
            if h.get("a"):
                messages.append({"role": "assistant", "content": h["a"]})
        goal = question or "（用户上传了一张图片，请识别并给出建议）"
        if image_path:
            goal += "\n（图片路径：%s）" % image_path
        else:
            goal += "\n（本次未上传图片，不要调用 recognize_image）"
        messages.append({"role": "user", "content": goal})

        nudge = 0
        for i in range(MAX_STEPS):
            try:
                reply = _llm_chat(messages)
            except Exception as e:
                steps.append({"n": len(steps) + 1, "thought": "调用大模型失败",
                              "tool": None, "args": None,
                              "obs": "接口异常：%s，已切换为内置规则规划器" % e.__class__.__name__,
                              "ok": False, "ms": 0})
                mode = "rule"
                break
            thought = ""
            mt = re.search(r"思考\s*[:：]\s*(.+)", reply, re.S)
            if mt:
                thought = mt.group(1).split("\n")[0].strip()[:200]
            messages.append({"role": "assistant", "content": reply})

            name, args, err = _parse_action(reply)
            if name == "finish":
                ok_n = len([s for s in steps if s.get("ok")])
                if ok_n < 2 and nudge < 1:
                    nudge += 1
                    messages.append({"role": "user", "content":
                                     "当前只有 %d 次有效工具调用，信息不足。"
                                     "请先调用合适的工具核实作物、病害或防治方案，再 finish。" % ok_n})
                    continue
                answer = _extract_final(reply)
                break
            if err:
                steps.append({"n": len(steps) + 1, "thought": thought, "tool": name,
                              "args": None, "obs": err, "ok": False, "ms": 0})
                messages.append({"role": "user", "content": "上一步出错：%s，请修正后继续。" % err})
                continue
            ts = time.time()
            try:
                obs = TOOLS[name]["fn"](db, **(args or {}))
                ok = True
            except Exception as e:
                obs = "工具执行异常：%s" % e.__class__.__name__
                ok = False
            ms = int((time.time() - ts) * 1000)
            steps.append({"n": len(steps) + 1, "thought": thought, "tool": name,
                          "args": args, "obs": obs, "obs_text": _fmt_obs(obs),
                          "ok": ok, "ms": ms})
            messages.append({"role": "user", "content": "工具 %s 返回：\n%s"
                             % (name, _clip(json.dumps(obs, ensure_ascii=False), OBS_CHARS))})
        if not answer and steps and mode == "llm":
            answer = "已达到最大推理步数，以下为已获取的资料：\n" + \
                     "\n".join("· %s -> %s" % (s["tool"], _clip(
                         json.dumps(s["obs"], ensure_ascii=False), 200)) for s in steps if s["ok"])

    # ---------- B. 规则规划器（无 Key 或大模型失败时） ----------
    if mode == "rule":
        used, state = [], {}
        for _ in range(MAX_STEPS - 1):
            nxt = rule_next(db, question, image_path, state, used)
            if not nxt:
                break
            name, args, thought = nxt
            ts = time.time()
            try:
                obs = TOOLS[name]["fn"](db, **args)
                ok = True
            except Exception as e:
                obs = "工具执行异常：%s" % e.__class__.__name__
                ok = False
            used.append(name)
            steps.append({"n": len(steps) + 1, "thought": thought, "tool": name,
                          "args": args, "obs": obs, "obs_text": _fmt_obs(obs),
                          "ok": ok, "ms": int((time.time() - ts) * 1000)})
            # 观察结果回写状态：识别到作物 -> 后续步骤围绕它展开
            if name == "recognize_image":
                c = _crop_from_obs(obs)
                if c:
                    state["crop"] = c
                    state["from_image"] = True
            miss = (not ok) or (isinstance(obs, dict) and not obs.get("ok"))
            state["last_miss"] = name if miss else None
        answer = rule_summary(question, steps)

    return {
        "ok": bool([s for s in steps if s.get("ok")]),
        "mode": mode,
        "steps": steps,
        "answer": answer,
        "tools_used": [s["tool"] for s in steps if s.get("tool")],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def tool_catalog():
    """给前端展示工具清单。"""
    return [{"name": n, "desc": t["desc"], "args": list(t["args"].keys())}
            for n, t in TOOLS.items()]
