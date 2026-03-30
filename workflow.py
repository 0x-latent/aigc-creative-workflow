"""AIGC Creative Marketing Workflow - Main orchestration entry point."""

import argparse
import json
import os
import uuid

from config import check_api_keys, logger
from db import init_db
from modules.brand_kb import BrandKBReader
from modules.insights import InsightsLoader
from modules.platform_kb import PlatformKBReader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.script_gen import ScriptGenerator
from modules.image_gen import ImageGenerator
from modules.review_gate import ReviewGate
from modules.tracker import CampaignTracker
from models.campaign import CampaignGoal


def _merge_feedback(items: list[dict], decision) -> str:
    """Build feedback for merge: selected items + user instruction."""
    parts = []
    for idx in (decision.selected_indices or []):
        item = items[idx]
        title = item.get("title") or item.get("outline") or item.get("id", "")
        desc = item.get("description", "")
        parts.append(f"方案{idx+1}「{title}」: {desc}")
    return f"请融合以下方案的优点，生成新方案：\n" + "\n".join(parts) + f"\n用户指令：{decision.feedback}"


def run_workflow(brand_id: str, objective: str, platform: str, notes: str = ""):
    # Init
    check_api_keys()
    init_db()
    campaign_id = f"campaign_{uuid.uuid4().hex[:8]}"
    logger.info(f"启动创意工作流 - Campaign: {campaign_id}")

    goal = CampaignGoal(
        campaign_id=campaign_id,
        brand_id=brand_id,
        objective=objective,
        platform=platform,
        notes=notes,
    )

    review_gate = ReviewGate()
    tracker = CampaignTracker()

    # Step 1: Load brand KB + insights
    logger.info("加载品牌知识库和用户洞察...")
    brand_kb = BrandKBReader().load(brand_id)
    insights = InsightsLoader().load(brand_id)
    platform_kb_obj = PlatformKBReader().load(platform)
    platform_kb = platform_kb_obj.raw_md
    brand_images = BrandKBReader().discover_brand_images(brand_id)
    logger.info(f"  品牌: {brand_kb.name} (version: {brand_kb.version[:8]})")
    logger.info(f"  洞察来源: {len(insights.sources)} 个文件")
    if platform_kb:
        logger.info(f"  平台知识: {platform} (已加载)")
    if brand_images:
        logger.info(f"  品牌产品图: {len(brand_images)} 张")

    # Step 2: Generate concepts → ReviewGate
    logger.info("生成核心创意理念...")
    concept_gen = ConceptGenerator()
    feedback = ""
    while True:
        concept_result = concept_gen.generate(goal, brand_kb, insights, feedback)
        items = [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "rationale": c.rationale,
            }
            for c in concept_result.concepts
        ]
        decision = review_gate.review_list(items, "核心创意理念")
        tracker.record(
            campaign_id=campaign_id,
            step="concept_review",
            input_snapshot={"concepts_count": len(items)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_concept = concept_result.concepts[decision.selected_index]
            logger.info(f"  选定理念: {selected_concept.title}")
            break
        feedback = _merge_feedback(items, decision) if decision.status == "merge" else decision.feedback
        logger.info(f"  根据反馈重新生成...")

    # Step 3: Generate directions → ReviewGate
    logger.info("生成创意方向...")
    direction_gen = DirectionGenerator()
    feedback = ""
    while True:
        direction_result = direction_gen.generate(goal, brand_kb, selected_concept, feedback, platform_kb=platform_kb)
        items = [
            {
                "id": d.id,
                "title": d.title,
                "description": d.description,
                "platform_notes": d.platform_notes,
            }
            for d in direction_result.directions
        ]
        decision = review_gate.review_list(items, "创意方向")
        tracker.record(
            campaign_id=campaign_id,
            step="direction_review",
            input_snapshot={"directions_count": len(items)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_direction = direction_result.directions[decision.selected_index]
            logger.info(f"  选定方向: {selected_direction.title}")
            break
        feedback = _merge_feedback(items, decision) if decision.status == "merge" else decision.feedback
        logger.info(f"  根据反馈重新生成...")

    # Step 4: Generate scripts (3 variants) → ReviewGate
    logger.info("生成脚本...")
    script_gen = ScriptGenerator()
    feedback = ""
    while True:
        script_result = script_gen.generate(goal, brand_kb, selected_direction, feedback=feedback, platform_kb=platform_kb)
        items = [
            {
                "id": s.id,
                "title": f"脚本方案 {i+1}",
                "outline": s.outline,
                "scenes": [
                    {
                        "scene_no": sc.scene_no,
                        "visual_description": sc.visual_description,
                        "voiceover": sc.voiceover,
                    }
                    for sc in s.scenes
                ],
            }
            for i, s in enumerate(script_result.scripts)
        ]
        decision = review_gate.review_list(items, "脚本方案")
        tracker.record(
            campaign_id=campaign_id,
            step="script_review",
            input_snapshot={"scripts_count": len(items)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_script = script_result.scripts[decision.selected_index]
            logger.info(f"  选定脚本: {selected_script.id}")
            break
        feedback = _merge_feedback(items, decision) if decision.status == "merge" else decision.feedback
        logger.info(f"  根据反馈重新生成...")

    # Step 4.5: Visual style confirmation
    recommended_style = selected_script.visual_style or "写实摄影风"
    logger.info(f"  推荐视觉风格: {recommended_style}")
    print(f"\n{'─'*60}")
    print(f"  推荐视觉风格: {recommended_style}")
    print("  预设选项: 写实摄影风 / 3D渲染风 / 扁平插画风 / 水墨中国风 / 电影感")
    print("  直接回车使用推荐风格，或输入自定义风格：")
    print(f"{'─'*60}")
    style_input = input("  视觉风格: ").strip()
    confirmed_style = style_input if style_input else recommended_style
    logger.info(f"  确认视觉风格: {confirmed_style}")

    # Step 5: Generate images → ReviewGate
    logger.info("生成图片...")
    image_gen = ImageGenerator()
    feedback = ""
    while True:
        image_result = image_gen.generate(
            goal, selected_script, feedback=feedback,
            visual_style=confirmed_style, reference_images=brand_images,
        )
        image_paths = [img.image_path for img in image_result.images]
        decision = review_gate.review_images(image_paths)
        tracker.record(
            campaign_id=campaign_id,
            step="image_review",
            input_snapshot={"image_count": len(image_paths)},
            output_snapshot={"status": decision.status, "paths": image_paths},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            logger.info("  图片已通过审核")
            break
        feedback = decision.feedback
        logger.info(f"  根据反馈重新生成: {feedback}")

    # Write summary
    summary = {
        "campaign_id": campaign_id,
        "brand_id": brand_id,
        "objective": objective,
        "platform": platform,
        "selected_concept": {"id": selected_concept.id, "title": selected_concept.title},
        "selected_direction": {"id": selected_direction.id, "title": selected_direction.title},
        "selected_script": {"id": selected_script.id, "outline": selected_script.outline},
        "visual_style": confirmed_style,
        "images": [img.image_path for img in image_result.images],
    }
    summary_dir = os.path.join("output", campaign_id)
    os.makedirs(summary_dir, exist_ok=True)
    with open(os.path.join(summary_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Done
    logger.info(f"{'='*60}")
    logger.info(f"  工作流完成!")
    logger.info(f"  Campaign ID: {campaign_id}")
    logger.info(f"  输出目录: output/{campaign_id}/")
    logger.info(f"  追溯数据库: output/campaign_tracker.db")
    logger.info(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="AIGC 创意营销工作流")
    parser.add_argument("--brand", required=True, help="品牌 ID（如 yishanfu）")
    parser.add_argument("--objective", required=True, help="营销目标")
    parser.add_argument("--platform", required=True, help="目标平台（如 抖音、小红书）")
    parser.add_argument("--notes", default="", help="补充说明")
    args = parser.parse_args()

    run_workflow(args.brand, args.objective, args.platform, args.notes)


if __name__ == "__main__":
    main()
