"""AIGC Creative Marketing Workflow — Tree Mode.

Preserves ALL generated results in a persistent tree structure.
Supports resume, branch-from-any-node, interactive exploration, and HTML visualization.

Usage:
    # New campaign
    python tree_workflow.py --brand yishanfu --objective "提升品牌认知" --platform "抖音"

    # Resume
    python tree_workflow.py --resume campaign_a3c9e08d

    # Branch from a specific node
    python tree_workflow.py --resume campaign_a3c9e08d --branch-from n_a3f8b2c1

    # Interactive tree exploration
    python tree_workflow.py --resume campaign_a3c9e08d --explore

    # Generate HTML visualization
    python tree_workflow.py --resume campaign_a3c9e08d --visualize
"""

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict

from config import check_api_keys, logger
from db import init_db
from models.campaign import (
    CampaignGoal,
    Concept,
    Direction,
    Script,
    Scene,
)
from models.tree import CampaignTree
from modules.brand_kb import BrandKBReader
from modules.concept_gen import ConceptGenerator
from modules.direction_gen import DirectionGenerator
from modules.image_gen import ImageGenerator
from modules.insights import InsightsLoader
from modules.platform_kb import PlatformKBReader
from modules.review_gate import ReviewGate
from modules.script_gen import ScriptGenerator
from modules.tracker import CampaignTracker
from modules.tree_manager import TreeManager


# ── Step runners ───────────────────────────────────────────────

def step_concepts(tree_mgr: TreeManager, goal, brand_kb, insights, parent_id):
    """Generate concepts under *parent_id*, review, return (selected_node_id, Concept)."""
    review_gate = ReviewGate()
    tracker = CampaignTracker()
    concept_gen = ConceptGenerator()
    feedback = ""

    while True:
        concept_result = concept_gen.generate(goal, brand_kb, insights, feedback)
        items_data = [
            {"id": c.id, "title": c.title, "description": c.description, "rationale": c.rationale}
            for c in concept_result.concepts
        ]
        node_ids = tree_mgr.add_generation_batch(
            parent_id, "concept", items_data, asdict(concept_result.meta), feedback,
        )
        tree_mgr.tree.save()

        display_items = list(items_data)  # ReviewGate expects list[dict]
        decision = review_gate.review_list(display_items, "核心创意理念")
        tracker.record(
            campaign_id=goal.campaign_id,
            step="concept_review",
            input_snapshot={"concepts_count": len(items_data)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )

        if decision.status == "approved":
            selected_nid = node_ids[decision.selected_index]
            tree_mgr.select_node(selected_nid)
            tree_mgr.tree.save()
            selected = concept_result.concepts[decision.selected_index]
            logger.info(f"  选定理念: {selected.title}")
            return selected_nid, selected

        tree_mgr.reject_batch(node_ids, decision.feedback)
        tree_mgr.tree.save()
        feedback = decision.feedback
        logger.info(f"  根据反馈重新生成: {feedback}")


def step_directions(tree_mgr: TreeManager, goal, brand_kb, concept: Concept, platform_kb, parent_id):
    """Generate directions under *parent_id*, review, return (selected_node_id, Direction)."""
    review_gate = ReviewGate()
    tracker = CampaignTracker()
    direction_gen = DirectionGenerator()
    feedback = ""

    while True:
        direction_result = direction_gen.generate(
            goal, brand_kb, concept, feedback, platform_kb=platform_kb,
        )
        items_data = [
            {"id": d.id, "title": d.title, "description": d.description, "platform_notes": d.platform_notes}
            for d in direction_result.directions
        ]
        node_ids = tree_mgr.add_generation_batch(
            parent_id, "direction", items_data, asdict(direction_result.meta), feedback,
        )
        tree_mgr.tree.save()

        decision = review_gate.review_list(items_data, "创意方向")
        tracker.record(
            campaign_id=goal.campaign_id,
            step="direction_review",
            input_snapshot={"directions_count": len(items_data)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )

        if decision.status == "approved":
            selected_nid = node_ids[decision.selected_index]
            tree_mgr.select_node(selected_nid)
            tree_mgr.tree.save()
            selected = direction_result.directions[decision.selected_index]
            logger.info(f"  选定方向: {selected.title}")
            return selected_nid, selected

        tree_mgr.reject_batch(node_ids, decision.feedback)
        tree_mgr.tree.save()
        feedback = decision.feedback
        logger.info(f"  根据反馈重新生成: {feedback}")


def step_scripts(tree_mgr: TreeManager, goal, brand_kb, direction: Direction, platform_kb, parent_id):
    """Generate scripts under *parent_id*, review, return (selected_node_id, Script)."""
    review_gate = ReviewGate()
    tracker = CampaignTracker()
    script_gen = ScriptGenerator()
    feedback = ""

    while True:
        script_result = script_gen.generate(
            goal, brand_kb, direction, feedback=feedback, platform_kb=platform_kb,
        )
        items_data = []
        for i, s in enumerate(script_result.scripts):
            items_data.append({
                "id": s.id,
                "title": f"脚本方案 {i+1}",
                "outline": s.outline,
                "visual_style": s.visual_style,
                "scenes": [
                    {
                        "scene_no": sc.scene_no,
                        "duration_sec": sc.duration_sec,
                        "visual_description": sc.visual_description,
                        "voiceover": sc.voiceover,
                        "image_prompt": sc.image_prompt,
                        "page_type": sc.page_type,
                    }
                    for sc in s.scenes
                ],
            })

        node_ids = tree_mgr.add_generation_batch(
            parent_id, "script", items_data, asdict(script_result.meta), feedback,
        )
        tree_mgr.tree.save()

        # ReviewGate display (simplified scenes for readability)
        display_items = [
            {
                "id": d["id"],
                "title": d["title"],
                "outline": d["outline"],
                "scenes": [
                    {"scene_no": sc["scene_no"], "visual_description": sc["visual_description"], "voiceover": sc["voiceover"]}
                    for sc in d["scenes"]
                ],
            }
            for d in items_data
        ]
        decision = review_gate.review_list(display_items, "脚本方案")
        tracker.record(
            campaign_id=goal.campaign_id,
            step="script_review",
            input_snapshot={"scripts_count": len(items_data)},
            output_snapshot={"status": decision.status, "selected_index": decision.selected_index},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )

        if decision.status == "approved":
            selected_nid = node_ids[decision.selected_index]
            tree_mgr.select_node(selected_nid)
            tree_mgr.tree.save()
            selected = script_result.scripts[decision.selected_index]
            logger.info(f"  选定脚本: {selected.id}")
            return selected_nid, selected

        tree_mgr.reject_batch(node_ids, decision.feedback)
        tree_mgr.tree.save()
        feedback = decision.feedback
        logger.info(f"  根据反馈重新生成: {feedback}")


def step_style_confirm(script: Script) -> str:
    """Confirm visual style interactively. Returns confirmed style string."""
    recommended = script.visual_style or "写实摄影风"
    logger.info(f"  推荐视觉风格: {recommended}")
    print(f"\n{'─'*60}")
    print(f"  推荐视觉风格: {recommended}")
    print("  预设选项: 写实摄影风 / 3D渲染风 / 扁平插画风 / 水墨中国风 / 电影感")
    print("  直接回车使用推荐风格，或输入自定义风格：")
    print(f"{'─'*60}")
    style_input = input("  视觉风格: ").strip()
    confirmed = style_input if style_input else recommended
    logger.info(f"  确认视觉风格: {confirmed}")
    return confirmed


def step_images(tree_mgr: TreeManager, goal, script: Script, visual_style, brand_images, parent_id):
    """Generate images under *parent_id*, review, return selected_node_id."""
    review_gate = ReviewGate()
    tracker = CampaignTracker()
    image_gen = ImageGenerator()
    feedback = ""
    branch_prefix = parent_id  # use script node_id as branch prefix for unique dirs

    while True:
        image_result = image_gen.generate(
            goal, script, feedback=feedback,
            visual_style=visual_style, reference_images=brand_images,
            branch_prefix=branch_prefix,
        )
        images_data = {
            "visual_style": visual_style,
            "images": [
                {
                    "scene_no": img.scene_no,
                    "image_path": img.image_path,
                    "image_prompt": img.image_prompt,
                }
                for img in image_result.images
            ],
        }
        node_ids = tree_mgr.add_generation_batch(
            parent_id, "images", [images_data], asdict(image_result.meta), feedback,
        )
        tree_mgr.tree.save()

        image_paths = [img.image_path for img in image_result.images]
        decision = review_gate.review_images(image_paths)
        tracker.record(
            campaign_id=goal.campaign_id,
            step="image_review",
            input_snapshot={"image_count": len(image_paths)},
            output_snapshot={"status": decision.status, "paths": image_paths},
            review_status=decision.status,
            review_feedback=decision.feedback,
        )

        if decision.status == "approved":
            selected_nid = node_ids[0]
            tree_mgr.select_node(selected_nid)
            tree_mgr.tree.save()
            logger.info("  图片已通过审核")
            return selected_nid

        tree_mgr.reject_batch(node_ids, decision.feedback)
        tree_mgr.tree.save()
        feedback = decision.feedback
        logger.info(f"  根据反馈重新生成: {feedback}")


# ── Reconstruct typed objects from tree node data ──────────────

def _concept_from_data(data: dict) -> Concept:
    return Concept(id=data["id"], title=data["title"],
                   description=data["description"], rationale=data["rationale"])


def _direction_from_data(data: dict) -> Direction:
    return Direction(id=data["id"], title=data["title"],
                     description=data["description"], platform_notes=data["platform_notes"])


def _script_from_data(data: dict) -> Script:
    scenes = [
        Scene(
            scene_no=s["scene_no"],
            duration_sec=s.get("duration_sec", 0),
            visual_description=s["visual_description"],
            voiceover=s["voiceover"],
            image_prompt=s["image_prompt"],
            page_type=s.get("page_type", ""),
        )
        for s in data.get("scenes", [])
    ]
    return Script(id=data["id"], outline=data["outline"], scenes=scenes,
                  visual_style=data.get("visual_style", ""))


# ── Main workflow from a starting point ────────────────────────

def run_from_node(tree_mgr: TreeManager, goal, brand_kb, insights, platform_kb, brand_images, start_node_id: str, next_step: str):
    """Run the workflow from a given node and step type onwards."""
    ctx = tree_mgr.get_branch_point_context(start_node_id)

    if next_step == "concept":
        nid, concept = step_concepts(tree_mgr, goal, brand_kb, insights, start_node_id)
        ctx["concept"] = tree_mgr.get_node(nid).data
        next_step = "direction"
        start_node_id = nid

    if next_step == "direction":
        concept = _concept_from_data(ctx["concept"])
        nid, direction = step_directions(tree_mgr, goal, brand_kb, concept, platform_kb, start_node_id)
        ctx["direction"] = tree_mgr.get_node(nid).data
        next_step = "script"
        start_node_id = nid

    if next_step == "script":
        direction = _direction_from_data(ctx["direction"])
        nid, script = step_scripts(tree_mgr, goal, brand_kb, direction, platform_kb, start_node_id)
        ctx["script"] = tree_mgr.get_node(nid).data
        next_step = "images"
        start_node_id = nid

    if next_step == "images":
        script = _script_from_data(ctx["script"])
        visual_style = step_style_confirm(script)
        step_images(tree_mgr, goal, script, visual_style, brand_images, start_node_id)

    return tree_mgr


# ── Interactive explore mode ───────────────────────────────────

def explore_mode(tree_mgr: TreeManager, goal, brand_kb, insights, platform_kb, brand_images):
    """Interactive loop: browse tree, inspect nodes, branch from any node."""
    from modules.tree_manager import _NEXT_STEP

    while True:
        tree_mgr.print_ascii_tree()
        print("  命令:")
        print("    <节点ID>        — 查看节点详情")
        print("    b <节点ID>      — 从该节点开新分支")
        print("    v               — 生成 HTML 可视化")
        print("    q               — 退出")
        print()
        cmd = input("  > ").strip()

        if not cmd:
            continue
        if cmd.lower() == "q":
            break
        if cmd.lower() == "v":
            _generate_visualization(tree_mgr)
            continue

        if cmd.lower().startswith("b "):
            node_id = cmd.split(None, 1)[1].strip()
            if node_id not in tree_mgr.tree.nodes:
                print(f"  节点 {node_id} 不存在")
                continue
            node = tree_mgr.get_node(node_id)
            next_step = _NEXT_STEP.get(node.node_type, "")
            if not next_step:
                print(f"  节点 {node_id} 是终端节点（图片），无法继续分支")
                continue
            print(f"\n  从 {node_id} ({node.node_type}) 开始新分支 → 生成{next_step}...")
            run_from_node(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images, node_id, next_step)
            continue

        # Treat as node ID for detail view
        node_id = cmd.strip()
        if node_id in tree_mgr.tree.nodes:
            tree_mgr.print_node_detail(node_id)
        else:
            print(f"  未找到节点: {node_id}")


def _generate_visualization(tree_mgr: TreeManager):
    from modules.tree_visualizer import TreeVisualizer
    viz = TreeVisualizer()
    path = viz.generate_html(tree_mgr.tree)
    print(f"  已生成可视化: {path}")


# ── Entry points ───────────────────────────────────────────────

def run_new_campaign(brand_id: str, objective: str, platform: str, notes: str = ""):
    check_api_keys()
    init_db()
    campaign_id = f"campaign_{uuid.uuid4().hex[:8]}"
    logger.info(f"启动创意树工作流 — Campaign: {campaign_id}")

    goal = CampaignGoal(campaign_id, brand_id, objective, platform, notes)

    # Load brand data
    brand_kb = BrandKBReader().load(brand_id)
    insights = InsightsLoader().load(brand_id)
    platform_kb_obj = PlatformKBReader().load(platform)
    platform_kb = platform_kb_obj.raw_md
    brand_images = BrandKBReader().discover_brand_images(brand_id)

    logger.info(f"  品牌: {brand_kb.name} (version: {brand_kb.version[:8]})")
    logger.info(f"  洞察来源: {len(insights.sources)} 个文件")

    # Create tree
    tree = CampaignTree.create(
        campaign_id=campaign_id,
        brand_id=brand_id,
        objective=objective,
        platform=platform,
        notes=notes,
        root_data={
            "brand_name": brand_kb.name,
            "insights_count": len(insights.sources),
            "platform_kb_loaded": bool(platform_kb),
        },
    )
    tree.save()
    tree_mgr = TreeManager(tree)

    # Run full workflow
    run_from_node(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images,
                  tree.root_id, "concept")

    # Write backward-compatible summary
    _write_summary(tree_mgr, goal)

    # Generate visualization
    _generate_visualization(tree_mgr)

    logger.info(f"{'='*60}")
    logger.info(f"  创意树工作流完成!")
    logger.info(f"  Campaign ID: {campaign_id}")
    logger.info(f"  创意树: output/{campaign_id}/campaign_tree.json")
    logger.info(f"  可视化: output/{campaign_id}/creative_tree.html")
    logger.info(f"{'='*60}")


def run_resume(campaign_id: str, branch_from: str | None = None):
    check_api_keys()
    init_db()

    tree = CampaignTree.load(campaign_id)
    tree_mgr = TreeManager(tree)
    goal = CampaignGoal(tree.campaign_id, tree.brand_id, tree.objective, tree.platform, tree.notes)

    brand_kb = BrandKBReader().load(tree.brand_id)
    insights = InsightsLoader().load(tree.brand_id)
    platform_kb_obj = PlatformKBReader().load(tree.platform)
    platform_kb = platform_kb_obj.raw_md
    brand_images = BrandKBReader().discover_brand_images(tree.brand_id)

    logger.info(f"恢复创意树工作流 — Campaign: {campaign_id}")

    if branch_from:
        if branch_from not in tree.nodes:
            logger.error(f"节点 {branch_from} 不存在")
            sys.exit(1)
        from modules.tree_manager import _NEXT_STEP
        node = tree_mgr.get_node(branch_from)
        next_step = _NEXT_STEP.get(node.node_type, "")
        if not next_step:
            logger.error(f"节点 {branch_from} 是终端节点，无法分支")
            sys.exit(1)
        logger.info(f"  从节点 {branch_from} ({node.node_type}) 开新分支")
        run_from_node(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images,
                      branch_from, next_step)
    else:
        node_id, next_step = tree_mgr.find_resume_point()
        if not next_step:
            logger.info("  该 campaign 已完成，进入浏览模式")
            explore_mode(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images)
            return
        logger.info(f"  从 {node_id} 继续，下一步: {next_step}")
        run_from_node(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images,
                      node_id, next_step)

    _write_summary(tree_mgr, goal)
    _generate_visualization(tree_mgr)

    logger.info(f"  创意树已更新: output/{campaign_id}/campaign_tree.json")
    logger.info(f"  可视化已更新: output/{campaign_id}/creative_tree.html")


def run_explore(campaign_id: str):
    tree = CampaignTree.load(campaign_id)
    tree_mgr = TreeManager(tree)
    goal = CampaignGoal(tree.campaign_id, tree.brand_id, tree.objective, tree.platform, tree.notes)

    brand_kb = BrandKBReader().load(tree.brand_id)
    insights = InsightsLoader().load(tree.brand_id)
    platform_kb_obj = PlatformKBReader().load(tree.platform)
    platform_kb = platform_kb_obj.raw_md
    brand_images = BrandKBReader().discover_brand_images(tree.brand_id)

    explore_mode(tree_mgr, goal, brand_kb, insights, platform_kb, brand_images)


def run_visualize(campaign_id: str):
    tree = CampaignTree.load(campaign_id)
    tree_mgr = TreeManager(tree)
    _generate_visualization(tree_mgr)


# ── Summary (backward compat) ─────────────────────────────────

def _write_summary(tree_mgr: TreeManager, goal: CampaignGoal):
    """Write a summary.json from the active path for backward compatibility."""
    tree = tree_mgr.tree
    ctx = {}
    for nid in tree.active_path:
        node = tree.nodes[nid]
        if node.node_type != "root":
            ctx[node.node_type] = node.data

    summary: dict = {
        "campaign_id": tree.campaign_id,
        "brand_id": tree.brand_id,
        "objective": tree.objective,
        "platform": tree.platform,
    }
    if "concept" in ctx:
        summary["selected_concept"] = {"id": ctx["concept"].get("id"), "title": ctx["concept"].get("title")}
    if "direction" in ctx:
        summary["selected_direction"] = {"id": ctx["direction"].get("id"), "title": ctx["direction"].get("title")}
    if "script" in ctx:
        summary["selected_script"] = {"id": ctx["script"].get("id"), "outline": ctx["script"].get("outline")}
    if "images" in ctx:
        summary["visual_style"] = ctx["images"].get("visual_style", "")
        summary["images"] = [img.get("image_path") for img in ctx["images"].get("images", [])]

    summary_dir = os.path.join("output", tree.campaign_id)
    os.makedirs(summary_dir, exist_ok=True)
    with open(os.path.join(summary_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AIGC 创意营销工作流 — 树模式")
    parser.add_argument("--brand", help="品牌 ID（新建时必填）")
    parser.add_argument("--objective", help="营销目标（新建时必填）")
    parser.add_argument("--platform", help="目标平台（新建时必填）")
    parser.add_argument("--notes", default="", help="补充说明")
    parser.add_argument("--resume", metavar="CAMPAIGN_ID", help="恢复已有 campaign")
    parser.add_argument("--branch-from", metavar="NODE_ID", help="从指定节点开新分支")
    parser.add_argument("--explore", action="store_true", help="交互式浏览创意树")
    parser.add_argument("--visualize", action="store_true", help="生成 HTML 可视化")
    args = parser.parse_args()

    if args.visualize and args.resume:
        run_visualize(args.resume)
    elif args.explore and args.resume:
        run_explore(args.resume)
    elif args.resume:
        run_resume(args.resume, args.branch_from)
    elif args.brand and args.objective and args.platform:
        run_new_campaign(args.brand, args.objective, args.platform, args.notes)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
