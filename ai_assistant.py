# -*- coding: utf-8 -*-
"""农技问答助手（LLM + RAG，可选模块）。

架构：检索增强生成（RAG）
  1. 检索：对用户问题做关键词打分，从 agri.db 检出最相关的作物/病害知识条目
  2. 增强：把命中的知识条目拼装成上下文，连同问题一起交给 LLM
  3. 生成：要求模型"仅基于给定资料回答"，降低幻觉风险
  4. 兜底：未配置 API Key / 接口异常 / 未安装依赖时优雅降级，
     返回检索到的知识库原文，功能不中断

配置（环境变量，见 .env.example）：
  AI_LLM_BASE_URL  OpenAI 兼容接口地址，如 https://api.deepseek.com/v1
  AI_LLM_API_KEY   对应服务的 API Key
  AI_LLM_MODEL     模型名，如 deepseek-chat
"""
import json
import os
import re
import urllib.request

import llm_client

STOPWORDS = {"的", "了", "吗", "呢", "是", "在", "我", "有", "和", "与", "怎么",
             "什么", "如何", "请问", "请教", "一下", "为什么", "啥", "咋"}


def _cfg():
    return llm_client.config() or {}


def enabled():
    """是否已有可用的大模型通道（自备 Key 或云服务免密钥）。"""
    return llm_client.enabled()


def llm_model():
    """当前生效的模型名（供页面展示，评审可一眼看到接的是哪个模型）。"""
    return _cfg().get("model") or ""


def llm_label():
    """当前通道说明（如"云服务免密钥" / "自备 Key（deepseek-chat）"）。"""
    return _cfg().get("label") or ""


def _tokens(q):
    # 简易中文分词：先按常见长度切，再退化为 2-gram
    q = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", " ", q)
    words = [w for w in q.split() if w]
    out = []
    for w in words:
        if len(w) <= 3:
            out.append(w)
        else:
            out.extend(w[i:i + 2] for i in range(len(w) - 1))
    return [t for t in out if t not in STOPWORDS] or list({t for t in out})


def retrieve(db, question, top_k=4):
    """关键词检索知识库，返回相关条目列表。db 为 app 的 db 模块。"""
    toks = _tokens(question)
    scored = []

    def score_row(text_fields):
        s = 0
        joined = " ".join(str(f or "") for f in text_fields)
        for t in toks:
            if t and t in joined:
                s += 2 if len(t) >= 2 else 1
        return s

    for c in db.query("SELECT name, alias, intro, habits, management, value FROM crops"):
        s = score_row([c["name"], c["alias"], c["intro"], c["habits"],
                       c["management"], c["value"]])
        if s:
            scored.append((s, "作物", c["name"],
                           (c["intro"] or "") + "\n生长习性：" + (c["habits"] or "") +
                           "\n种植管理：" + (c["management"] or "")))
    for d in db.query(
            "SELECT d.name, d.dtype, d.symptoms, d.cause, d.physical, d.chemical, "
            "d.field_mgmt, d.prevention, c.name crop_name FROM diseases d "
            "LEFT JOIN crops c ON c.id = d.crop_id"):
        s = score_row([d["name"], d["symptoms"], d["cause"], d["crop_name"]])
        if s:
            scored.append((s, "病害", "%s（%s）" % (d["name"], d["crop_name"] or "通用"),
                           "症状：" + (d["symptoms"] or "") +
                           "\n物理防治：" + (d["physical"] or "") +
                           "\n用药建议：" + (d["chemical"] or "") +
                           "\n田间整改：" + (d["field_mgmt"] or "") +
                           "\n后期预防：" + (d["prevention"] or "")))
    scored.sort(key=lambda x: -x[0])
    return [{"kind": k, "title": t, "content": c} for _, k, t, c in scored[:top_k]]


SYSTEM_PROMPT = (
    "你是智慧农业平台的农技问答助手。回答规则："
    "1) 只依据【参考资料】回答，资料里没有的就说建议咨询当地农技站，不要编造；"
    "2) 涉及用药时提醒遵守安全间隔期，先小面积试用；"
    "3) 回答用简体中文，简洁分条，面向普通农户，避免术语堆砌；"
    "4) 结尾提醒：识别与建议仅供参考，重要病虫害请结合田间实际复核；"
    "5) 纯文本输出，不要使用 Markdown 标记（**、#、|、```），分条用「1. 2. 3.」。"
)


def answer(question, refs):
    """调用 LLM 生成回答。失败时抛异常，由调用方降级。"""
    ctx = "\n\n".join("【资料%d·%s】%s\n%s" % (i + 1, r["kind"], r["title"], r["content"])
                      for i, r in enumerate(refs))
    user_msg = "【参考资料】\n%s\n\n【用户问题】\n%s" % (ctx or "（未检索到相关资料）", question)
    return llm_client.chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": user_msg}],
        temperature=0.3, max_tokens=900, timeout=120)
