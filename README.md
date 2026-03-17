# AIGC 创意营销工作流系统

从品牌知识库到素材产出的完整生产流程，每步可追溯、可打回重生成。

## 安装

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 环境变量

```bash
export ANTHROPIC_API_KEY="your-api-key"
export REPLICATE_API_TOKEN="your-replicate-token"
```

## 运行

```bash
source .venv/bin/activate
python workflow.py --brand yishanshu --objective "提升品牌认知" --platform "小红书"
```

## 工作流程

1. **加载品牌知识库** - 读取 `brands/{brand_id}/knowledge_base.md`
2. **加载用户洞察** - 读取 `brands/{brand_id}/insights/*.md`
3. **生成核心理念** - Claude API 生成 3-5 个创意理念 → 人工审核
4. **生成创意方向** - 基于选定理念生成 3-5 个执行方向 → 人工审核
5. **生成脚本** - 生成 3 套分镜脚本变体 → 人工审核
6. **生成图片** - Replicate flux-dev 为每个场景生图 → 人工审核

每步审核时可选择通过或打回重新生成。所有步骤记录写入 SQLite 数据库。

## 目录结构

```
brands/          # 品牌知识库和洞察数据
modules/         # 各功能模块
models/          # 数据模型定义
prompts/         # Prompt 模板
output/          # 生成产物（按 campaign_id 归档）
```

## 追溯

所有生成步骤和审核决策记录在 `output/campaign_tracker.db` 中，可用任意 SQLite 工具查看。
