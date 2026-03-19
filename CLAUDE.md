# AIGC 创意营销工作流

## 项目概述
一个基于 LLM + AI 图像生成的创意营销内容生产工作流（CLI 工具）。面向品牌营销团队，从品牌知识库和用户洞察出发，经过多轮人工审核（Human-in-the-loop），逐步生成：核心创意理念 → 创意执行方向 → 分镜脚本 → AI 配图。

## 技术栈
- **Python 3.10+**（dataclass, type hints）
- **Anthropic Claude API** — 文本生成（创意/方向/脚本）
- **Replicate API (flux-dev)** — AI 图像生成
- **SQLite** — 追溯数据库（campaign_tracker.db）
- 无 Web 框架，纯 CLI 交互

## 项目结构
```
workflow.py          # 主编排入口
config.py            # 集中配置（模型、API key 检查、日志）
db.py                # SQLite 初始化与连接
models/              # 数据模型（dataclass）
  base.py            # GenerationMeta, ReviewDecision
  brand.py           # BrandKB, InsightsBundle
  campaign.py        # CampaignGoal, Concept, Direction, Scene, Script, Image
modules/             # 业务模块
  brand_kb.py        # 品牌知识库加载（读取 brands/{id}/knowledge_base.md）
  insights.py        # 用户洞察加载（读取 brands/{id}/insights/*.md）
  concept_gen.py     # 核心创意理念生成（Claude API）
  direction_gen.py   # 创意方向生成（Claude API）
  script_gen.py      # 分镜脚本生成（Claude API）
  image_gen.py       # AI 配图生成（Replicate flux-dev）
  review_gate.py     # 人工审核门（CLI 交互）
  tracker.py         # 追溯记录写入 SQLite
prompts/             # Prompt 模板
  concept_gen_v1.txt
  direction_gen_v1.txt
  script_gen_v1.txt
brands/              # 品牌数据（按 brand_id 组织）
  {brand_id}/
    knowledge_base.md
    insights/*.md
raw_data/            # 原始品牌素材（PDF/图片）
output/              # 生成产物（按 campaign_id 组织）
```

## 工作流步骤
1. 加载品牌知识库 + 用户洞察
2. 生成核心创意理念（3-5个）→ 人工审核选择 1 个
3. 生成创意执行方向（3-5个）→ 人工审核选择 1 个
4. 生成分镜脚本（3套变体）→ 人工审核选择 1 套
5. 按脚本逐场景 AI 生图 → 人工审核
6. 所有步骤记录到 SQLite 追溯数据库

## 运行方式
```bash
python workflow.py --brand yishanfu --objective "提升品牌认知" --platform "抖音" --notes "面向30-45岁男性"
```

## 环境变量
- `ANTHROPIC_API_KEY` — Claude API 密钥（必需）
- `REPLICATE_API_TOKEN` — Replicate API 密钥（必需）
- `AIGC_LLM_MODEL` — LLM 模型（默认 claude-sonnet-4-20250514）
- `AIGC_IMAGE_MODEL` — 图像模型（默认 black-forest-labs/flux-dev）
- `AIGC_LOG_LEVEL` — 日志级别（默认 INFO）

## 开发约定
- 模块间通过 dataclass 传递数据，不使用 dict
- 每个生成模块自带重试逻辑和追溯记录
- Prompt 模板存放在 prompts/ 目录，通过 .format() 填充变量
- 品牌数据以 Markdown 格式存放，知识库和洞察分离
