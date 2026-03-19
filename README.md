# AIGC 创意营销工作流

基于 LLM + AI 图像生成的创意营销内容生产工作流。面向品牌营销团队，从品牌知识库和用户洞察出发，经过多轮人工审核，逐步生成完整的创意营销方案。

## 工作流总览

```
品牌知识库 + 用户洞察
        │
        ▼
┌─────────────────┐
│ 核心创意理念(3-5个) │ ← Claude API 生成
└────────┬────────┘
         │ 人工审核：选择 1 个 / 打回 / 退出
         ▼
┌─────────────────┐
│ 创意执行方向(3-5个) │ ← Claude API 生成
└────────┬────────┘
         │ 人工审核：选择 1 个 / 打回 / 退出
         ▼
┌─────────────────┐
│  分镜脚本(3套变体)  │ ← Claude API 生成
└────────┬────────┘
         │ 人工审核：选择 1 套 / 打回 / 退出
         ▼
┌─────────────────┐
│  逐场景 AI 配图    │ ← Replicate flux-dev 生成
└────────┬────────┘
         │ 人工审核：通过 / 打回 / 退出
         ▼
   output/{campaign_id}/
   ├── scripts/scripts.json
   ├── images/scene_*.png
   └── summary.json
```

每个步骤都支持 **Human-in-the-loop**：审核不通过可以附带反馈意见，系统会据此重新生成。所有步骤记录到 SQLite 追溯数据库。

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| 语言 | Python 3.10+ |
| 文本生成 | Anthropic Claude API（默认 claude-sonnet-4-20250514） |
| 图像生成 | Replicate API（默认 black-forest-labs/flux-dev） |
| 数据追溯 | SQLite（output/campaign_tracker.db） |
| 数据模型 | dataclass + type hints |
| 交互方式 | 纯 CLI |

## 项目结构

```
├── workflow.py                 # 主编排入口
├── config.py                   # 集中配置（模型、API key、日志）
├── db.py                       # SQLite 初始化与连接
│
├── models/                     # 数据模型（dataclass）
│   ├── base.py                 #   GenerationMeta, ReviewDecision
│   ├── brand.py                #   BrandKB, InsightsBundle
│   └── campaign.py             #   CampaignGoal, Concept, Direction, Script, Scene, Image 等
│
├── modules/                    # 业务模块
│   ├── llm_util.py             #   共享 LLM 调用 + JSON 解析
│   ├── brand_kb.py             #   品牌知识库加载
│   ├── insights.py             #   用户洞察加载
│   ├── concept_gen.py          #   核心创意理念生成
│   ├── direction_gen.py        #   创意方向生成
│   ├── script_gen.py           #   分镜脚本生成
│   ├── image_gen.py            #   AI 配图生成
│   ├── review_gate.py          #   人工审核门（CLI 交互）
│   └── tracker.py              #   追溯记录写入 SQLite
│
├── prompts/                    # Prompt 模板
│   ├── concept_gen_v1.txt
│   ├── direction_gen_v1.txt
│   └── script_gen_v1.txt
│
├── brands/                     # 品牌数据（按 brand_id 组织）
│   └── {brand_id}/
│       ├── knowledge_base.md   #   品牌知识库
│       └── insights/           #   用户洞察（多个 .md 文件）
│
├── raw_data/                   # 原始品牌素材（PDF/图片等）
├── output/                     # 生成产物（按 campaign_id 组织）
├── requirements.txt
├── .env.example
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入 API 密钥：

```bash
cp .env.example .env
```

```env
# 必需
ANTHROPIC_API_KEY=sk-ant-xxx
REPLICATE_API_TOKEN=r8_xxx

# 可选
# AIGC_LLM_MODEL=claude-sonnet-4-20250514
# AIGC_IMAGE_MODEL=black-forest-labs/flux-dev
# AIGC_LOG_LEVEL=INFO
```

### 3. 准备品牌数据

在 `brands/` 目录下按 brand_id 创建文件夹，放入：

- `knowledge_base.md` — 品牌知识库（品牌定位、产品信息、竞争优势等）
- `insights/*.md` — 用户洞察文件（市场分析、目标人群、竞品分析等）

项目已包含示例品牌 `yishanfu`，可直接使用。

### 4. 运行

```bash
python workflow.py --brand yishanfu --objective "提升品牌认知" --platform "抖音" --notes "面向30-45岁男性"
```

参数说明：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--brand` | 是 | 品牌 ID，对应 `brands/` 下的目录名 |
| `--objective` | 是 | 营销目标 |
| `--platform` | 是 | 目标平台（如 抖音、小红书、微信视频号） |
| `--notes` | 否 | 补充说明（目标人群、风格偏好等） |

### 5. 人工审核交互

工作流每个阶段会在 CLI 中展示生成结果并等待输入：

- **输入数字**（如 `1`、`2`）— 选择对应方案并通过
- **输入 `r`** — 打回重新生成，随后输入修改方向
- **输入 `q`** — 退出工作流

## 输出产物

运行完成后，产物保存在 `output/{campaign_id}/` 目录：

```
output/campaign_abcd1234/
├── scripts/
│   └── scripts.json        # 完整分镜脚本（含所有场景）
├── images/
│   ├── scene_1.png          # 各场景 AI 配图
│   ├── scene_2.png
│   └── ...
└── summary.json             # 工作流摘要（选定的理念、方向、脚本等）
```

追溯数据库位于 `output/campaign_tracker.db`，记录每个步骤的输入输出、审核结果等，可用任意 SQLite 工具查询。

## 架构设计

### 数据流

模块间通过 **dataclass** 传递数据，不使用裸 dict：

```
BrandKBReader  →  BrandKB
InsightsLoader →  InsightsBundle
                                    ┐
ConceptGenerator  →  ConceptResult  │  每个 Generator 接收上游产物
DirectionGenerator → DirectionResult│  + CampaignGoal，输出 Result
ScriptGenerator   →  ScriptResult   │
ImageGenerator    →  ImageResult    ┘
```

### LLM 调用

所有文本生成模块共享 `modules/llm_util.py`：

- `call_llm()` — 统一的 Claude API 调用，内置重试逻辑和 system prompt（约束纯 JSON 输出）
- `parse_json_array()` — 从 LLM 响应中提取 JSON 数组，自动去除 markdown code fence

Prompt 模板存放在 `prompts/` 目录，通过 `.format()` 填充变量。

### 重试机制

- LLM 调用：最多 3 次重试，指数退避（2s → 4s → 8s）
- 图像生成 API 调用：同上
- 图片下载：同上

### 追溯记录

`CampaignTracker` 将每个步骤写入 SQLite，字段包括：

| 字段 | 说明 |
|------|------|
| campaign_id | 工作流实例 ID |
| step | 步骤名（concept_gen / direction_gen / script_gen / image_gen / *_review） |
| input_snapshot | 输入参数 JSON |
| output_snapshot | 输出结果 JSON |
| prompt_template | 使用的 Prompt 模板文件名 |
| model | 使用的模型 |
| review_status | 审核结果（approved / rejected） |
| review_feedback | 审核反馈 |

## 添加新品牌

1. 在 `brands/` 下创建品牌目录：

```
brands/mybrand/
├── knowledge_base.md
└── insights/
    ├── 01_market.md
    └── 02_audience.md
```

2. 运行时指定 `--brand mybrand` 即可。

知识库和洞察均为 Markdown 格式，无特殊格式要求。知识库的第一个 `# 标题` 会被识别为品牌名称。

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `ANTHROPIC_API_KEY` | 是 | — | Claude API 密钥 |
| `REPLICATE_API_TOKEN` | 是 | — | Replicate API 密钥 |
| `AIGC_LLM_MODEL` | 否 | `claude-sonnet-4-20250514` | LLM 模型 |
| `AIGC_IMAGE_MODEL` | 否 | `black-forest-labs/flux-dev` | 图像生成模型 |
| `AIGC_LOG_LEVEL` | 否 | `INFO` | 日志级别（DEBUG / INFO / WARNING / ERROR） |
