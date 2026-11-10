# 慧农 AI · 智慧农业助农服务平台

一套同时适配 PC 端与移动端的智慧农业服务平台，核心是**真实落地的作物病害图像识别 AI**：
MobileNetV2 迁移学习模型（ONNX CPU 推理）+ 开放集拒识 + 通用视觉兜底，
配合农技知识库与农产品展销，把「认作物 → 辨病害 → 学防治 → 卖产品」四个环节放进同一个平台。

技术栈：**Flask + SQLite + ONNX Runtime（MobileNetV2）+ 原生响应式前端**

> 演示账号：`admin / admin123`（管理员）、`farmer / farmer123`（农户）、`demo / demo123`（普通用户）

🔗 **在线演示**：<https://agri-ai-platform-50936.app.workbuddy.host/?sharecode=SBBOCRVH7J>
（首次访问需带 `?sharecode=SBBOCRVH7J`；云端与本地数据库相互独立）

---

## 一、团队信息

本作品由 1 名参赛队员独立完成，承担从需求分析到上线演示的全部工作：

| 工作方向 | 具体内容 |
| --- | --- |
| 总体设计 | 选题调研、功能规划、数据库设计、接口与页面结构设计 |
| AI 模型 | 数据集构建与清洗、MobileNetV2 迁移学习训练、开放集拒识校准、ONNX 导出与推理集成 |
| 后端开发 | Flask 路由与业务逻辑、SQLite 数据层、大模型双通道接入、ReAct 智能体工具编排 |
| 前端开发 | Jinja2 模板与原生响应式界面（PC / 平板 / 手机三档断点）、交互与视觉设计 |
| 测试与文档 | 标准集与实景集评测、真实照片回归测试、知识库整理、技术文档与演示视频制作 |

## 二、项目亮点（AI 技术深度）

1. **真模型而非规则引擎**：基于 MobileNetV2（ImageNet 预训练）做迁移学习，
   在 PlantVillage 公开数据集 54,305 张叶片图（38 类 / 14 作物）上训练三层分类头
   （作物 → 病害细类 → 健康状态），导出纯 ONNX + NumPy 权重，**CPU 即可推理，全程离线**。
2. **权威评测指标**：标准测试集作物识别 99.0% / 病害 97.1% / 健康 98.5%；
   模拟田间扰动的 3,000 张测试集上 86.3% / 94.6% / 97.8%（扰动增强训练带来 +13.4pp 提升）。
3. **开放集拒识（OOD）**：物种通道把 17 种平台未收录作物（香蕉、白菜、桃、甘蔗等 1,056 张实景照）
   作为第 15 类「未收录」参与训练，推理时用**判别式未收录概率 + 能量分数 + 1-NN 余弦相似度**
   三重分位融合判据，超出范围就主动拒识并说明原因。实测库内留出集准确率 89.1%，
   训练中见过的未收录作物拒识 73.3%，完全没见过的新物种拒识 53.3%，
   野草、花卉不会再被硬配成库里某个作物。
4. **通用视觉兜底**：叶片模型拒识后，自动调用 ImageNet 原版模型识别果实/籽粒照片
   （黄瓜 99.9%、苹果 86% 等 22 类果蔬），引导用户上传叶片；仍无法判断则给出知识库资料。
5. **结果可解释**：病害诊断附带**遮挡敏感度热力图**（模型关注区域可视化）与置信度分布，
   拒识时逐条给出判据（未收录概率 / 能量分位 / 相似度）。宁可承认"不会"，也不让农户拿着错误结论去打药。

详细评测数据见 `ai_model/benchmark.json`、`ai_model/species_classes.json`。

## 三、功能模块

| 模块 | 地址 | 说明 |
| --- | --- | --- |
| 农作物智能识别 | `/crop-recognize` | 上传/拍照识别作物，输出科普（适种地区、习性、管理、经济价值） |
| 病虫害智能诊断 | `/disease-recognize` | 病害名称 + 发病特征诱因 + 物理/用药/田间/预防四套防治方案 |
| AI 能力实验室 | `/ai-lab` | 展示模型结构、评测指标、开放集拒识案例与能力边界（技术评审重点页面） |
| 农技知识库 | `/knowledge` | 14 种作物 / 34 种病害图文资料，支持搜索与分类筛选 |
| 农产品助农展销 | `/shop` | 商品展示、采购清单、需求单、农户上架（后台审核）、咨询留言 |
| 农技问答助手 | `/assistant` | LLM + RAG 智能问答（默认云服务免密钥大模型，无需自备 Key） |
| 农业智能体 | `/agent` | 5 工具 ReAct 循环，大模型自主规划；无网络时规则规划器兜底 |

## 四、技术架构

```
浏览器（PC / 平板 / 手机响应式）
   │  上传图片 / 提问
   ▼
Flask 应用层（app.py：路由、会话、业务逻辑）
   │
   ├── AI 识别引擎（ai_engine.py）
   │     ├─ MobileNetV2 特征提取（ai_model/mobilenetv2-12-feat.onnx）
   │     ├─ 三层分类头（ai_model/heads.npz：作物/病害/健康）
   │     ├─ 开放集检测（ai_model/ood.npz，余弦相似度阈值 0.75）
   │     ├─ 通用视觉兜底（ai_model/mobilenetv2-12-imagenet.onnx，imagenet_aux.py）
   │     └─ TTA 多视角推理 + 热力图生成
   │
   ├── 农业智能体（agri_agent.py）
   │     └─ 规划 → 调工具（识别/档案/防治/检索/农资）→ 观察结果 → 再规划 → 汇总方案
   │        默认由免密钥大模型自主规划；断网时内置规则规划器接手，链路一致
   │
   ├── 大模型层（llm_client.py）
   │     ├─ 通道一：WorkBuddy 云服务免密钥接口（默认，无需 Key）
   │     └─ 通道二：自备 OpenAI 兼容接口（AI_LLM_* 环境变量，优先）
   │
   ├── LLM 问答（ai_assistant.py）
   │     └─ RAG：检索 agri.db 知识库 → 拼装上下文 → 大模型生成回答
   │
   └── 数据层（db.py + SQLite：users/crops/diseases/products/cart_items/
             orders/messages/history 8 张表，首次运行自动建库）
```

前端：Jinja2 模板 + 原生 CSS/JS，1080/900/640px 三档断点，移动端 `capture="environment"`
直接唤起后置摄像头；静态资源带版本号防缓存。

## 五、快速开始

```bash
# 1. 安装依赖（Python 3.10 ~ 3.13）
pip install -r requirements.txt

# 2.（可选）配置环境变量：复制 .env.example 按需修改，全部有默认值

# 3. 启动（首次运行自动建库并写入知识库数据）
python app.py

# 4. 浏览器访问
http://127.0.0.1:5000
```

Windows 推荐直接双击 `run.bat`（自动挑端口、等服务就绪再开浏览器、防重复启动）。

**环境变量**见 `.env.example`（端口 / SECRET_KEY / 调试开关 / LLM 接口配置），均有默认值。
**依赖清单**见 `requirements.txt`，核心只有 4 个包；不装 onnxruntime 时引擎自动降级为
本地特征引擎，保证演示不中断。

## 六、目录结构

```
├── app.py            # Flask 主程序：全部路由与业务逻辑
├── ai_engine.py      # AI 识别引擎：MobileNetV2 推理 + 开放集拒识
├── species_engine.py # 作物物种识别通道（实景照，覆盖知识库全部作物）
├── imagenet_aux.py   # ImageNet 原版模型兜底（果实/籽粒识别）
├── ai_labels.py      # 模型类别 → 中文/知识库 slug 映射
├── agri_agent.py     # 农业智能体：工具调用 + 规划循环（/agent 与 /api/agent）
├── ai_assistant.py   # LLM + RAG 农技问答
├── llm_client.py     # 大模型统一客户端（云服务免密钥 / 自备 Key 双通道）
├── db.py             # SQLite 数据层：建表、初始化、查询封装
├── vision.py         # 本地特征引擎（模型不可用时的降级兜底）
├── seed_data.py      # 知识库与商品初始数据（14 作物 / 34 病害 / 14 商品）
├── seed_data_ai.py   # AI 病害知识自愈（模型类别缺知识库条目时自动补齐）
├── ai_model/         # ONNX 模型与权重（含 benchmark.json 评测数据）
├── launcher.py       # 启动器：挑端口、拉服务、开浏览器、单实例保护
├── mcp_server.py     # MCP 服务端：stdio + JSON-RPC 2.0，对外开放 5 个农业工具
├── mcp.json          # MCP 客户端配置模板（Claude Desktop / WorkBuddy / Cline 通用）
├── run.bat           # Windows 一键启动
├── .env.example      # 环境变量模板
├── requirements.txt  # 依赖清单
├── static/           # 样式 / 脚本 / 上传图片 / 热力图
└── templates/        # 页面模板（base.html 公共骨架，含 AI 实验室页）
```

## 七、MCP 工具服务（Model Context Protocol）

平台不仅调用大模型，也把自身农业能力按 **MCP 标准**对外开放：`mcp_server.py` 用 Python 标准库
手写 JSON-RPC 2.0 与 stdio 传输，**零第三方依赖**，任何支持 MCP 的客户端配置后即可直接调用。

**协议实现**

| 方法 | 说明 |
| --- | --- |
| `initialize` | 版本协商（2025-06-18 / 2025-03-26 / 2024-11-05），返回 `tools` 能力与 `serverInfo` |
| `tools/list` | 返回 5 个工具的 JSON Schema（名称 / 描述 / 参数 / 只读标注） |
| `tools/call` | 执行工具，按 MCP 规范返回 `content[]` 与 `isError` |
| `ping` / `notifications/initialized` | 心跳与握手确认；未知方法返回 `-32601` |

stdout 只输出协议帧，日志统一写 stderr；参数缺失、工具内部异常都以 `isError: true` 结构化返回，
不会打断客户端会话。

**对外工具**

| 工具 | 作用 |
| --- | --- |
| `recognize_image` | 图像识别：叶片病害模型 → 实景物种模型 → ImageNet 兜底，超范围主动拒识 |
| `crop_profile` | 作物档案：适种区域、生长习性、种植管理、经济价值 |
| `query_disease` | 病害防治方案：症状、发病高峰、物理防治、用药与安全间隔期、田间整改 |
| `search_knowledge` | 知识库模糊检索（RAG 召回） |
| `list_products` | 在售农资/农产品：产地、价格、库存 |

工具实现直接复用 `agri_agent.TOOLS`，与站内智能体调用同一份代码、同一份 SQLite 数据与本地 ONNX 模型，
外部客户端与网页端结论一致。

**运行与接入**

```bash
python mcp_server.py --selftest   # 自检：握手 + 工具枚举 + 真实调用
python mcp_server.py --tools      # 打印工具清单
python mcp_server.py              # stdio 方式启动（由 MCP 客户端拉起）
```

客户端配置（`mcp.json`，路径改为实际项目绝对路径）：

```json
{
  "mcpServers": {
    "huinong-agri": {
      "command": "python",
      "args": ["<项目绝对路径>/mcp_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

> 说明：`command` 必须是**装好本项目依赖的那个解释器**（`pip install -r requirements.txt` 之后）。
> 若系统默认 `python` 未装 `onnxruntime`，`recognize_image` 会返回"识别引擎未就绪"，
> 此时把 `command` 换成项目实际使用的解释器绝对路径即可（其余 4 个工具只用标准库 + SQLite，不受影响）。

## 八、AI 模型复现（训练流程）

**通道 A：叶片病害诊断**（训练代码与数据流水线在开发仓库 `ai/` 目录，不随部署包分发）

1. PlantVillage 54,305 张图，按 8:1:1 划分（随机种子 20261024，保证可复现）
2. 冻结 MobileNetV2 主干，提取 1280 维嵌入；训练 crop / fine / health 三个分类头
3. 田间退化增强：旋转 ±28°、缩放 0.72~0.95、亮度 0.68~1.32、高斯失焦、JPEG 压缩
4. 类别平衡采样；导出 `heads.npz`（纯 NumPy 权重）供 ONNX Runtime CPU 推理
5. 开放集阈值由验证集分布确定（0.75，误拒率 0.26%）

**通道 B：作物物种识别（实景照）**（`species_engine.py` + `species_heads.npz` + `mobilenetv2-ft-species.onnx`）

1. 数据：GBIF / iNaturalist 研究级鉴定的田间实景照片 2,511 张、14 类，覆盖知识库全部作物
   （含通道 A 完全没学过的水稻、小麦、黄瓜、茶树、油菜）；另采集 17 种未收录作物 1,056 张作负类
2. 骨干在 14 类 + 第 15 类「未收录」上联合微调（输出 1 280 维嵌入），导出独立 ONNX，
   与通道 A 的叶片模型互不干扰
3. 拒识判据：判别式未收录概率、能量分数、1-NN 余弦相似度三项各取分位数后等权融合，
   阈值在校准集上按"误拒率优先"搜索确定
4. 实测：库内留出集（9 种 568 张）准确率 89.1%、误拒 14.5%；未见作物拒识 73.3%（训练中见过）、
   53.3%（完全没见过的物种）；桌面 14 张真实照片识别数由 6 张提升到 10 张

## 九、能力边界（如实说明）

- 病害诊断模型在**叶片**样本上训练：果实/籽粒/整株照片由**物种识别通道**回答"是什么作物"，
  但不会给出病害结论（引导用户补拍叶片特写）
- 物种通道对背景复杂的个别种类（茶树、大豆）仍会认错，因此所有实景识别结果都标注
  置信度与"仅供参考"，没把握时宁可拒识并给出知识库资料
- 识别结果仅供参考，请结合田间实际症状复核

## 十、响应式与演示

- PC：完整导航栏、多列布局；移动端：汉堡抽屉、单列、48px 触控目标
- 手机与电脑连同一 WiFi，访问启动窗口打印的内网地址即可（防火墙放行见 `手机访问放行.bat`）
- 端口被占用时启动器自动顺延；同一 WiFi 无法访问请检查防火墙是否放行 Python（`手机访问放行.bat`）
