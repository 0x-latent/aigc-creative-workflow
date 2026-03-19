"""自动化测试脚本 - 跳过人工审核，自动选择第 1 个方案，保存每步中间结果。"""

import json
import os
import uuid
from datetime import datetime, timezone

from config import check_api_keys, logger
from db import init_db
from modules.brand_kb import BrandKBReader
from modules.insights import InsightsLoader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.script_gen import ScriptGenerator
from modules.image_gen import ImageGenerator
from modules.tracker import CampaignTracker
from models.campaign import CampaignGoal


def save_step(output_dir: str, step_name: str, data):
    """将中间结果保存为 JSON 文件。"""
    path = os.path.join(output_dir, f"{step_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"  中间结果已保存: {path}")


def run():
    check_api_keys()
    init_db()

    campaign_id = f"test_{uuid.uuid4().hex[:8]}"
    output_dir = os.path.join("output", campaign_id)
    os.makedirs(output_dir, exist_ok=True)

    logger.info(f"{'='*60}")
    logger.info(f"  自动化测试运行 - Campaign: {campaign_id}")
    logger.info(f"{'='*60}")

    goal = CampaignGoal(
        campaign_id=campaign_id,
        brand_id="yishanfu",
        objective="提升品牌认知",
        platform="抖音",
        notes="面向30-45岁男性",
    )
    tracker = CampaignTracker()

    # ── Step 1: 加载品牌数据 ──
    logger.info("[Step 1] 加载品牌知识库 + 用户洞察...")
    brand_kb = BrandKBReader().load(goal.brand_id)
    insights = InsightsLoader().load(goal.brand_id)
    logger.info(f"  品牌: {brand_kb.name} (version: {brand_kb.version[:8]})")
    logger.info(f"  洞察来源: {len(insights.sources)} 个文件")
    save_step(output_dir, "01_brand_data", {
        "brand_name": brand_kb.name,
        "brand_version": brand_kb.version,
        "kb_length": len(brand_kb.raw_md),
        "insights_sources": insights.sources,
        "insights_length": len(insights.raw_text),
    })

    # ── Step 2: 生成核心创意理念 ──
    logger.info("[Step 2] 生成核心创意理念...")
    concept_gen = ConceptGenerator()
    concept_result = concept_gen.generate(goal, brand_kb, insights)
    concepts_data = [
        {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale}
        for c in concept_result.concepts
    ]
    save_step(output_dir, "02_concepts", concepts_data)

    selected_concept = concept_result.concepts[0]  # 自动选第 1 个
    logger.info(f"  自动选定理念: [{selected_concept.id}] {selected_concept.title}")
    tracker.record(
        campaign_id=campaign_id, step="concept_review",
        input_snapshot={"concepts_count": len(concepts_data)},
        output_snapshot={"status": "approved", "selected_index": 0},
        review_status="approved",
    )

    # ── Step 3: 生成创意方向 ──
    logger.info("[Step 3] 生成创意方向...")
    direction_gen = DirectionGenerator()
    direction_result = direction_gen.generate(goal, brand_kb, selected_concept)
    directions_data = [
        {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
        for d in direction_result.directions
    ]
    save_step(output_dir, "03_directions", directions_data)

    selected_direction = direction_result.directions[0]  # 自动选第 1 个
    logger.info(f"  自动选定方向: [{selected_direction.id}] {selected_direction.title}")
    tracker.record(
        campaign_id=campaign_id, step="direction_review",
        input_snapshot={"directions_count": len(directions_data)},
        output_snapshot={"status": "approved", "selected_index": 0},
        review_status="approved",
    )

    # ── Step 4: 生成分镜脚本 ──
    logger.info("[Step 4] 生成分镜脚本...")
    script_gen = ScriptGenerator()
    script_result = script_gen.generate(goal, brand_kb, selected_direction)
    scripts_data = [
        {
            "id": s.id,
            "outline": s.outline,
            "scenes": [
                {
                    "scene_no": sc.scene_no,
                    "duration_sec": sc.duration_sec,
                    "visual_description": sc.visual_description,
                    "voiceover": sc.voiceover,
                    "image_prompt": sc.image_prompt,
                }
                for sc in s.scenes
            ],
        }
        for s in script_result.scripts
    ]
    save_step(output_dir, "04_scripts", scripts_data)

    selected_script = script_result.scripts[0]  # 自动选第 1 套
    logger.info(f"  自动选定脚本: [{selected_script.id}] 共 {len(selected_script.scenes)} 个场景")
    tracker.record(
        campaign_id=campaign_id, step="script_review",
        input_snapshot={"scripts_count": len(scripts_data)},
        output_snapshot={"status": "approved", "selected_index": 0},
        review_status="approved",
    )

    # ── Step 5: 生成图片 ──
    logger.info("[Step 5] 生成 AI 配图...")
    image_gen = ImageGenerator()
    image_result = image_gen.generate(goal, selected_script)
    images_data = [
        {"scene_no": img.scene_no, "image_prompt": img.image_prompt, "image_path": img.image_path}
        for img in image_result.images
    ]
    save_step(output_dir, "05_images", images_data)
    tracker.record(
        campaign_id=campaign_id, step="image_review",
        input_snapshot={"image_count": len(images_data)},
        output_snapshot={"status": "approved", "paths": [img.image_path for img in image_result.images]},
        review_status="approved",
    )

    # ── 写 summary ──
    summary = {
        "campaign_id": campaign_id,
        "brand_id": goal.brand_id,
        "objective": goal.objective,
        "platform": goal.platform,
        "selected_concept": {"id": selected_concept.id, "title": selected_concept.title},
        "selected_direction": {"id": selected_direction.id, "title": selected_direction.title},
        "selected_script": {"id": selected_script.id, "outline": selected_script.outline},
        "images": [img.image_path for img in image_result.images],
    }
    save_step(output_dir, "summary", summary)

    logger.info(f"\n{'='*60}")
    logger.info(f"  测试运行完成!")
    logger.info(f"  Campaign ID: {campaign_id}")
    logger.info(f"  输出目录: {output_dir}/")
    logger.info(f"  中间结果文件:")
    for fname in sorted(os.listdir(output_dir)):
        if fname.endswith(".json"):
            fpath = os.path.join(output_dir, fname)
            size = os.path.getsize(fpath)
            logger.info(f"    {fname} ({size:,} bytes)")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    run()
