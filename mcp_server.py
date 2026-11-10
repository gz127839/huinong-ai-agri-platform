#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""慧农 AI 农业工具 MCP 服务端（stdio / JSON-RPC 2.0）。

把平台已有的五个能力以标准 Model Context Protocol 暴露给任意 MCP 客户端
（Claude Desktop、WorkBuddy、Cline、自研客户端等），客户端无需改一行代码即可接入：

    recognize_image   看图识别作物/病害（叶片模型 → 实景物种模型 → ImageNet 兜底）
    crop_profile      作物档案（适种区域、生长习性、种植管理、经济价值）
    query_disease     病害防治方案（症状、用药、安全间隔期、田间整改）
    search_knowledge  知识库模糊检索（RAG 召回）
    list_products     在售农资/农产品（价格、库存、产地）

设计说明
--------
1. 不依赖任何 MCP SDK，只用标准库手写 JSON-RPC 2.0 与 stdio 传输，
   评审环境里 `pip install -r requirements.txt` 之后即可直接运行。
2. stdout 只走协议数据，日志一律写 stderr，避免污染 JSON-RPC 帧。
3. 工具实现直接复用 agri_agent.TOOLS，与站内智能体用的是同一份代码，
   保证「网页智能体」和「外部 MCP 客户端」看到的农业能力完全一致。

用法
----
    python mcp_server.py             # 以 stdio 方式启动（供 MCP 客户端拉起）
    python mcp_server.py --selftest  # 自检：跑一遍 initialize / tools.list / tools.call
    python mcp_server.py --tools     # 打印工具清单（人看的）

客户端配置见项目根目录 mcp.json 与 README「MCP 工具服务」一节。
"""
import io
import json
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

SERVER_NAME = "huinong-agri-mcp"
SERVER_VERSION = "1.0.0"
# 优先返回客户端请求的版本；不在列表内则回落到服务端支持的最新版
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

INSTRUCTIONS = (
    "慧农 AI 智慧农业工具服务，提供 5 个农业领域工具：图像识别（作物/病害）、"
    "作物档案、病害防治方案、知识库检索、农资与农产品查询。"
    "识别结果仅供参考，用药请遵照农药标签与当地农技部门指导。"
)

# 工具的 JSON Schema：与 agri_agent.TOOLS 一一对应
TOOL_SCHEMAS = [
    {
        "name": "recognize_image",
        "title": "作物图像识别",
        "description": ("识别一张农作物照片，回答「这是什么作物 / 得了什么病」。"
                        "三通道级联：叶片病害模型 → 实景物种模型 → ImageNet 通用兜底；"
                        "不在支持范围内的图片会明确拒识，不会强行归类。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "图片的绝对路径（也接受相对项目根目录的路径）"}
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "crop_profile",
        "title": "作物档案",
        "description": "查询某种作物的档案：适种区域、生长季节、生长习性、种植管理要点、经济价值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "作物名，如 番茄、水稻、黄瓜"}
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "query_disease",
        "title": "病害防治方案",
        "description": ("查询病害的防治方案：症状、发病高峰、物理防治、用药建议、"
                        "田间整改、后期预防。可按病害名、作物名或症状关键词查询。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "病害名（早疫病）/ 作物名（番茄）/ 症状关键词（叶斑）"}
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "search_knowledge",
        "title": "知识库检索",
        "description": "在农业知识库里做模糊检索，用于兜底查找作物、病害、栽培管理资料（RAG 召回）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词或自然语言问题"}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_products",
        "title": "农资与农产品查询",
        "description": "查询平台在售的农药、肥料、种苗与农产品，含产地、价格、库存，用于给出可执行的采购建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "商品关键词，如 杀菌剂、番茄、有机肥"}
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

_TOOL_MAP = {t["name"]: t for t in TOOL_SCHEMAS}


def log(msg):
    """日志只写 stderr，绝不能污染 stdout 的 JSON-RPC 帧。"""
    sys.stderr.write("[mcp] %s\n" % msg)
    sys.stderr.flush()


# ---------------------------------------------------------------- 工具执行

_state = {}


def _deps():
    """延迟导入：避免客户端只发 initialize 时就加载 onnxruntime 等重依赖。"""
    if "agent" not in _state:
        import db as _db
        import agri_agent
        _state["db"] = _db
        _state["agent"] = agri_agent
    return _state["db"], _state["agent"]


def _resolve_path(path):
    path = (path or "").strip().strip('"').strip("'")
    if not path:
        return path
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return os.path.normpath(path)


def call_tool(name, args):
    """执行工具，返回 (结构化结果, is_error)。"""
    if name not in _TOOL_MAP:
        return {"ok": False, "msg": "未知工具：%s" % name}, True

    schema = _TOOL_MAP[name]["inputSchema"]
    args = args or {}
    missing = [k for k in schema["required"] if not str(args.get(k, "")).strip()]
    if missing:
        return {"ok": False, "msg": "缺少必填参数：%s" % "、".join(missing)}, True

    try:
        db, agent = _deps()
        fn = agent.TOOLS[name]["fn"]
        call_args = dict(args)
        if name == "recognize_image":
            call_args["path"] = _resolve_path(call_args.get("path"))
            if not os.path.exists(call_args["path"]):
                return {"ok": False, "msg": "图片不存在：%s" % call_args["path"]}, True
        result = fn(db, **call_args)
    except Exception as exc:  # 工具内部异常不应打断整个 MCP 会话
        log("tool %s failed: %s" % (name, exc))
        return {"ok": False, "msg": "工具执行异常：%s" % exc,
                "trace": traceback.format_exc(limit=2)}, True

    is_error = isinstance(result, dict) and result.get("ok") is False
    return result, is_error


def _text_of(result):
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- JSON-RPC

def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message, data=None):
    e = {"code": code, "message": message}
    if data:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}


def handle(req):
    """处理一条请求；notification 返回 None（不回复）。"""
    if not isinstance(req, dict):
        return _err(None, -32600, "Invalid Request")

    method = req.get("method")
    rid = req.get("id")
    is_notification = "id" not in req

    if method == "initialize":
        params = req.get("params") or {}
        want = params.get("protocolVersion")
        version = want if want in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        log("initialize from %s (protocol %s)" % (
            ((params.get("clientInfo") or {}).get("name") or "unknown"), version))
        return _ok(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })

    if method in ("notifications/initialized", "notifications/cancelled",
                  "initialized", "exit"):
        return None

    if method == "ping":
        return _ok(rid, {})

    if method == "tools/list":
        return _ok(rid, {"tools": TOOL_SCHEMAS})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        result, is_error = call_tool(name, args)
        log("tools/call %s -> %s" % (name, "error" if is_error else "ok"))
        return _ok(rid, {
            "content": [{"type": "text", "text": _text_of(result)}],
            "isError": bool(is_error),
        })

    if method in ("resources/list", "prompts/list"):
        key = method.split("/")[0]
        return _ok(rid, {key: []})

    if is_notification:
        return None
    return _err(rid, -32601, "Method not found: %s" % method)


# ---------------------------------------------------------------- 传输层

def _stdio():
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    log("server %s v%s ready (stdio)" % (SERVER_NAME, SERVER_VERSION))
    for raw in stdin:
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:
            stdout.write(json.dumps(_err(None, -32700, "Parse error", str(exc)),
                                    ensure_ascii=False) + "\n")
            stdout.flush()
            continue

        # 支持批量请求（JSON 数组）
        if isinstance(req, list):
            out = [r for r in (handle(x) for x in req) if r]
            if out:
                stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                stdout.flush()
            continue

        resp = handle(req)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()


def _selftest():
    """无需客户端即可验证协议与工具链路。"""
    print("== 1. initialize ==")
    print(json.dumps(handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05",
                                        "clientInfo": {"name": "selftest"}}}),
                     ensure_ascii=False, indent=2)[:400])

    print("\n== 2. tools/list ==")
    resp = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    print("工具 %d 个：%s" % (len(names), "、".join(names)))

    print("\n== 3. tools/call crop_profile(番茄) ==")
    resp = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "crop_profile", "arguments": {"name": "番茄"}}})
    print(resp["result"]["content"][0]["text"][:400])
    print("isError =", resp["result"]["isError"])

    print("\n== 4. tools/call 参数缺失（应报错但不崩） ==")
    resp = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                   "params": {"name": "query_disease", "arguments": {}}})
    print(resp["result"]["content"][0]["text"], "| isError =", resp["result"]["isError"])

    print("\n== 5. 未知方法 ==")
    print(handle({"jsonrpc": "2.0", "id": 5, "method": "foo/bar"}))
    print("\n自检完成。")


def main():
    if "--tools" in sys.argv:
        for t in TOOL_SCHEMAS:
            req = "、".join(t["inputSchema"]["required"])
            print("- %-17s (%s)\n    %s" % (t["name"], req, t["description"]))
        return
    if "--selftest" in sys.argv:
        _selftest()
        return
    try:
        _stdio()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
