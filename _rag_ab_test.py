# -*- coding: utf-8 -*-
"""RAG 消融对比 + Agent 决策轨迹实测（技术文档第五章数据来源）。

跑法：
  envs/default/Scripts/python.exe _rag_ab_test.py
输出：_rag_ab_result.json（供文档引用）
"""
import json
import os
import sys
import time

import db
import llm_client
import ai_assistant
import agri_agent

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "_rag_ab_result.json")

QUESTIONS = [
    "番茄晚疫病怎么防治？",
    "辣椒炭疽病打什么药？",
    "草莓灰霉病的高峰期和预防方法？",
]

# 无检索提示（裸 LLM 对照：无 SYSTEM_PROMPT 约束、无资料）
BARE_PROMPT = "你是有经验的农技专家。请回答下面的农技问题，分条给出防治建议。"


def run_bare(question):
    return llm_client.chat(
        [{"role": "system", "content": BARE_PROMPT},
         {"role": "user", "content": question}],
        temperature=0.3, max_tokens=900, timeout=120)


def main():
    if not llm_client.enabled():
        print("LLM 通道不可用，退出")
        sys.exit(1)
    cfg = llm_client.config()
    print("当前通道:", cfg.get("label"))

    result = {"model": cfg.get("model"), "label": cfg.get("label"),
              "ab": [], "agent_trace": None}

    for q in QUESTIONS:
        print("=" * 30)
        print("问题:", q)
        t0 = time.time()
        refs = ai_assistant.retrieve(db, q)
        t_retrieve = round(time.time() - t0, 3)
        bare = run_bare(q)
        rag = ai_assistant.answer(q, refs)
        entry = {
            "question": q,
            "retrieval_ms": int(t_retrieve * 1000),
            "refs": [{"kind": r["kind"], "title": r["title"]} for r in refs],
            "bare_answer": bare,
            "rag_answer": rag,
        }
        result["ab"].append(entry)
        print("检索命中:", [r["title"] for r in refs], "(%dms)" % entry["retrieval_ms"])
        print("裸LLM:", bare[:200].replace("\n", " "))
        print("RAG  :", rag[:200].replace("\n", " "))

    # Agent 决策轨迹
    print("=" * 30)
    print("Agent: 黄瓜霜霉病该买什么药")
    t0 = time.time()
    res = agri_agent.run(db, "我的黄瓜得了霜霉病，该买什么药？怎么用？")
    elapsed = round(time.time() - t0, 1)
    steps = res.get("steps") or res.get("trace") or []
    result["agent_trace"] = {
        "question": "我的黄瓜得了霜霉病，该买什么药？怎么用？",
        "elapsed_s": elapsed,
        "n_steps": len(steps),
        "steps": [{k: s.get(k) for k in ("n", "thought", "tool", "args", "obs", "ok", "ms") if k in s}
                  for s in steps],
        "answer_head": (res.get("answer") or "")[:300],
    }
    for s in steps:
        print(" -", s.get("tool"), str(s.get("args"))[:60], "→", str(s.get("summary"))[:80])

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
