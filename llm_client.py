# -*- coding: utf-8 -*-
"""统一大模型客户端（双通道）。

通道 1（自备 Key）：环境变量 AI_LLM_BASE_URL / AI_LLM_API_KEY / AI_LLM_MODEL，
                  任意 OpenAI 兼容接口（DeepSeek / 通义 / 智谱 / 中转均可）。
通道 2（免密钥）：WorkBuddy 云服务大模型接口，使用应用自身的 publishableKey 鉴权，
                  调用方无需申请任何 Key。接口只支持 SSE 流式返回，本模块内部拼装完整文本。

对外只暴露三个函数：
  config()  -> 当前生效的通道配置（None 表示都不可用）
  enabled() -> 是否可用
  chat(messages, ...) -> str
"""
import json
import os
import re
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 云服务（免密钥）默认配置：与应用发布域一致，可用环境变量覆盖
WBCS_ENDPOINT = "https://agri-ai-platform-50936.app.workbuddy.host"
WBCS_KEY = "wbpk_q3IyQSS1Y5InqRyMw520fq_5hOlXzSynLtPVcGiUatN24k62PrVVIvL"
WBCS_MODEL = "hunyuan-chat"
# 主模型不可用（参数不兼容 / 空返回 / 超时）时按顺序兜底
WBCS_FALLBACK = ("glm-5.3-flash", "deepseek-v4-flash")


def load_env_file(path=None):
    """读取项目根目录 .env（KEY=VALUE 逐行），已存在的环境变量优先。"""
    path = path or os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(path):
        return 0
    n = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.split(" #")[0].strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
                    n += 1
    except Exception:
        pass
    return n


load_env_file()


def config():
    """返回当前生效的通道；都不可用时返回 None。"""
    base = (os.environ.get("AI_LLM_BASE_URL") or "").rstrip("/")
    key = os.environ.get("AI_LLM_API_KEY") or ""
    model = os.environ.get("AI_LLM_MODEL") or ""
    if base and key and model:
        return {"provider": "openai", "base_url": base, "api_key": key,
                "model": model, "label": "自备 Key（%s）" % model}
    if os.environ.get("AI_LLM_DISABLE_CLOUD") == "1":
        return None
    return {"provider": "wbcs",
            "base_url": (os.environ.get("WBCS_ENDPOINT") or WBCS_ENDPOINT).rstrip("/"),
            "api_key": os.environ.get("WBCS_PUBLISHABLE_KEY") or WBCS_KEY,
            "model": model or os.environ.get("WBCS_MODEL") or WBCS_MODEL,
            "label": "云服务免密钥"}


def enabled():
    return config() is not None


def _post_json(c, payload, timeout):
    req = urllib.request.Request(
        c["base_url"] + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + c["api_key"]},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _post_stream(c, payload, timeout):
    """调用云服务 SSE 接口，拼装 delta.content。"""
    req = urllib.request.Request(
        c["base_url"] + "/.cloud/llm/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Origin": c["base_url"],
                 "x-wb-webapp-access-key": c["api_key"]},
        method="POST")
    parts, reason = [], []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                obj = json.loads(chunk)
            except Exception:
                continue
            if obj.get("error"):
                raise RuntimeError(str(obj["error"])[:160])
            for ch in obj.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("content"):
                    parts.append(d["content"])
                if d.get("reasoning_content"):
                    reason.append(d["reasoning_content"])
    text = "".join(parts).strip()
    if not text:
        # 个别思考型模型把正文放在 reasoning_content 里
        text = "".join(reason).strip()
    if not text:
        raise RuntimeError("模型返回为空")
    return text


def _clean(text):
    """去掉模型偶发的 Markdown 标记，页面按纯文本渲染，保持排版干净。"""
    s = (text or "").replace("**", "").replace("__", "").replace("```", "")
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)      # 标题井号
    s = re.sub(r"(?m)^\s{0,3}>\s?", "", s)          # 引用符
    s = re.sub(r"(?m)^\s*[-*]\s+", "· ", s)          # 列表符号统一为中文点
    return s.strip()


def chat(messages, temperature=0.3, max_tokens=900, timeout=120):
    """统一对话入口，失败抛异常（调用方负责降级）。"""
    c = config()
    if not c:
        raise RuntimeError("未配置大模型接口")
    if c["provider"] == "openai":
        return _clean(_post_json(c, {"model": c["model"], "messages": messages,
                                     "temperature": temperature,
                                     "max_tokens": max_tokens, "stream": False}, timeout))
    models = [c["model"]]
    if not os.environ.get("WBCS_MODEL") and not os.environ.get("AI_LLM_MODEL"):
        models += [m for m in WBCS_FALLBACK if m != c["model"]]
    last = None
    for m in models:
        payload = {"model": m, "messages": messages, "stream": True}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            return _clean(_post_stream(c, payload, timeout))
        except Exception as e:      # 换下一个模型；全失败时抛出最后一个错误
            last = e
    raise last or RuntimeError("模型调用失败")
