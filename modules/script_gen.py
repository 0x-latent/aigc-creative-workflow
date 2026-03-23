import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from config import LLM_MODEL, logger
from models.base import GenerationMeta
from models.brand import BrandKB
from models.campaign import (
    CampaignGoal,
    Direction,
    Scene,
    Script,
    ScriptResult,
)
from modules.brand_kb import extract_script_kb
from modules.llm_util import call_llm, parse_json_array
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE_VIDEO = "script_gen_v1.txt"
PROMPT_TEMPLATE_GRAPHIC = "script_gen_v1_graphic.txt"

# Platforms that use image-text (图文) format instead of video scripts
GRAPHIC_PLATFORMS = {"小红书"}


class ScriptGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        self.tracker = CampaignTracker()

    def _select_template(self, platform: str) -> str:
        if platform in GRAPHIC_PLATFORMS:
            return PROMPT_TEMPLATE_GRAPHIC
        return PROMPT_TEMPLATE_VIDEO

    def _generate_parallel(
        self,
        template: str,
        script_kb: str,
        goal: CampaignGoal,
        direction: Direction,
        num_variants: int,
        feedback: str,
        platform_kb: str,
        sibling_info: str,
    ) -> list[dict]:
        """Generate multiple variants via parallel single-variant calls.

        Each call produces 1 variant. Previous variants' outlines are fed as
        sibling_info to subsequent calls for differentiation. First batch runs
        truly parallel, using variant index as differentiation hint.
        """
        logger.info(f"  图文方案拆分为 {num_variants} 次并发调用（每次 1 套）")

        # Build per-variant differentiation hints
        variant_hints = []
        for i in range(num_variants):
            parts = []
            if sibling_info:
                parts.append(sibling_info)
            parts.append(f"你是第 {i+1}/{num_variants} 个变体，必须与其他变体在叙事结构和视觉风格上明显不同。")
            if i == 0:
                parts.append("作为第一个变体，请大胆尝试最直觉的方案。")
            elif i == 1:
                parts.append("作为第二个变体，请尝试完全不同的叙事角度和视觉风格。")
            else:
                parts.append("作为第三个变体，请探索前两者都未涉及的创意空间。")
            variant_hints.append("\n".join(parts))

        def gen_one(variant_idx):
            data, _ = self._call_once(
                template, script_kb, goal, direction,
                num_variants=1,
                feedback=feedback,
                platform_kb=platform_kb,
                sibling_info=variant_hints[variant_idx],
            )
            return data[0] if data else None

        results = []
        with ThreadPoolExecutor(max_workers=num_variants) as pool:
            futures = {pool.submit(gen_one, i): i for i in range(num_variants)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        results.append((idx, result))
                except Exception as e:
                    logger.error(f"  变体 {idx+1} 生成失败: {e}")

        # Sort by original index to maintain order
        results.sort(key=lambda x: x[0])
        scripts_data = [r[1] for r in results]

        logger.info(f"  并发完成，成功 {len(scripts_data)}/{num_variants} 套")
        return scripts_data

    def _call_once(
        self,
        template: str,
        script_kb: str,
        goal: CampaignGoal,
        direction: Direction,
        num_variants: int,
        feedback: str,
        platform_kb: str,
        sibling_info: str,
    ) -> list[dict]:
        """Single LLM call, returns parsed JSON array."""
        user_content = template.format(
            brand_kb=script_kb,
            direction_title=direction.title,
            direction_description=direction.description,
            platform_notes=direction.platform_notes,
            objective=goal.objective,
            platform=goal.platform,
            platform_kb=platform_kb or "无",
            num_variants=num_variants,
            feedback=feedback or "无",
            sibling_info=sibling_info or "无（当前是唯一分支）",
        )
        raw_text = call_llm(user_content, max_tokens=16384)
        return parse_json_array(raw_text), user_content

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        direction: Direction,
        num_variants: int = 3,
        feedback: str = "",
        platform_kb: str = "",
        sibling_info: str = "",
    ) -> ScriptResult:
        prompt_template = self._select_template(goal.platform)
        template_path = os.path.join(self.prompts_dir, prompt_template)
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        script_kb = extract_script_kb(brand_kb.raw_md)

        # For graphic platforms (5-9 scenes per variant), split into parallel
        # single-variant calls to avoid output truncation.
        if prompt_template == PROMPT_TEMPLATE_GRAPHIC and num_variants > 1:
            scripts_data = self._generate_parallel(
                template, script_kb, goal, direction,
                num_variants, feedback, platform_kb, sibling_info,
            )
            # Use first variant's prompt for input_hash
            user_content = template.format(
                brand_kb=script_kb,
                direction_title=direction.title,
                direction_description=direction.description,
                platform_notes=direction.platform_notes,
                objective=goal.objective,
                platform=goal.platform,
                platform_kb=platform_kb or "无",
                num_variants=num_variants,
                feedback=feedback or "无",
                sibling_info=sibling_info or "无（当前是唯一分支）",
            )
        else:
            scripts_data, user_content = self._call_once(
                template, script_kb, goal, direction,
                num_variants, feedback, platform_kb, sibling_info,
            )
            if len(scripts_data) < num_variants:
                logger.warning(f"请求 {num_variants} 套脚本，实际解析到 {len(scripts_data)} 套（可能因输出截断）")

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        scripts = []
        for i, s in enumerate(scripts_data):
            scenes = [
                Scene(
                    scene_no=sc["scene_no"],
                    duration_sec=sc["duration_sec"],
                    visual_description=sc["visual_description"],
                    voiceover=sc["voiceover"],
                    image_prompt=sc["image_prompt"],
                    page_type=sc.get("page_type", ""),
                )
                for sc in s["scenes"]
            ]
            scripts.append(
                Script(
                    id=f"script_{i+1}",
                    outline=s["outline"],
                    scenes=scenes,
                    visual_style=s.get("visual_style", ""),
                )
            )

        meta = GenerationMeta(
            prompt_template=prompt_template,
            model=LLM_MODEL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            input_hash=input_hash,
        )

        result = ScriptResult(scripts=scripts, meta=meta)

        # Save scripts JSON to output
        scripts_dir = os.path.join("output", goal.campaign_id, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(
            os.path.join(scripts_dir, "scripts.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(scripts_data, f, ensure_ascii=False, indent=2)

        self.tracker.record(
            campaign_id=goal.campaign_id,
            step="script_gen",
            input_snapshot={
                "direction_id": direction.id,
                "direction_title": direction.title,
                "num_variants": num_variants,
                "feedback": feedback,
            },
            output_snapshot={"scripts_count": len(scripts)},
            prompt_template=prompt_template,
            model=LLM_MODEL,
            input_hash=input_hash,
        )

        return result
