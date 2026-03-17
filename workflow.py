"""AIGC Creative Marketing Workflow - Main orchestration entry point."""

import argparse
import uuid
from dataclasses import asdict

from db import init_db
from modules.brand_kb import BrandKBReader
from modules.insights import InsightsLoader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.script_gen import ScriptGenerator
from modules.image_gen import ImageGenerator
from modules.review_gate import ReviewGate
from modules.tracker import CampaignTracker
from models.campaign import CampaignGoal


def run_workflow(brand_id: str, objective: str, platform: str, notes: str = ""):
    # Init
    init_db()
    campaign_id = f"campaign_{uuid.uuid4().hex[:8]}"
    print(f"\n🚀 启动创意工作流 - Campaign: {campaign_id}")

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
    print("\n📚 加载品牌知识库和用户洞察...")
    brand_kb = BrandKBReader().load(brand_id)
    insights = InsightsLoader().load(brand_id)
    print(f"  品牌: {brand_kb.name} (version: {brand_kb.version[:8]})")
    print(f"  洞察来源: {len(insights.sources)} 个文件")

    # Step 2: Generate concepts → ReviewGate
    print("\n💡 生成核心创意理念...")
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
            output_snapshot={"status": decision.status, "feedback": decision.feedback},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_idx = int(decision.feedback) - 1
            selected_concept = concept_result.concepts[selected_idx]
            print(f"  ✅ 选定理念: {selected_concept.title}")
            break
        feedback = decision.feedback
        print(f"  🔄 根据反馈重新生成: {feedback}")

    # Step 3: Generate directions → ReviewGate
    print("\n🎨 生成创意方向...")
    direction_gen = DirectionGenerator()
    feedback = ""
    while True:
        direction_result = direction_gen.generate(goal, brand_kb, selected_concept, feedback)
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
            output_snapshot={"status": decision.status, "feedback": decision.feedback},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_idx = int(decision.feedback) - 1
            selected_direction = direction_result.directions[selected_idx]
            print(f"  ✅ 选定方向: {selected_direction.title}")
            break
        feedback = decision.feedback
        print(f"  🔄 根据反馈重新生成: {feedback}")

    # Step 4: Generate scripts (3 variants) → ReviewGate
    print("\n📝 生成脚本...")
    script_gen = ScriptGenerator()
    feedback = ""
    while True:
        script_result = script_gen.generate(goal, brand_kb, selected_direction, feedback=feedback)
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
            output_snapshot={"status": decision.status, "feedback": decision.feedback},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )
        if decision.status == "approved":
            selected_idx = int(decision.feedback) - 1
            selected_script = script_result.scripts[selected_idx]
            print(f"  ✅ 选定脚本: {selected_script.id}")
            break
        feedback = decision.feedback
        print(f"  🔄 根据反馈重新生成: {feedback}")

    # Step 5: Generate images → ReviewGate
    print("\n🖼️  生成图片...")
    image_gen = ImageGenerator()
    feedback = ""
    while True:
        image_result = image_gen.generate(goal, selected_script)
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
            print("  ✅ 图片已通过审核")
            break
        feedback = decision.feedback
        print(f"  🔄 根据反馈重新生成: {feedback}")
        # For image regen, we could modify prompts but for MVP just regenerate
        # TODO: incorporate feedback into image prompts

    # Done
    print(f"\n{'='*60}")
    print(f"  ✅ 工作流完成!")
    print(f"  Campaign ID: {campaign_id}")
    print(f"  输出目录: output/{campaign_id}/")
    print(f"  追溯数据库: output/campaign_tracker.db")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="AIGC Creative Marketing Workflow")
    parser.add_argument("--brand", required=True, help="Brand ID (e.g., yishanshu)")
    parser.add_argument("--objective", required=True, help="Campaign objective")
    parser.add_argument("--platform", required=True, help="Target platform")
    parser.add_argument("--notes", default="", help="Additional notes")
    args = parser.parse_args()

    run_workflow(args.brand, args.objective, args.platform, args.notes)


if __name__ == "__main__":
    main()
