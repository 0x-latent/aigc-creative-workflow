import hashlib
import json
import os
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

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        direction: Direction,
        num_variants: int = 3,
        feedback: str = "",
        platform_kb: str = "",
    ) -> ScriptResult:
        prompt_template = self._select_template(goal.platform)
        template_path = os.path.join(self.prompts_dir, prompt_template)
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        user_content = template.format(
            brand_kb=brand_kb.raw_md,
            direction_title=direction.title,
            direction_description=direction.description,
            platform_notes=direction.platform_notes,
            objective=goal.objective,
            platform=goal.platform,
            platform_kb=platform_kb or "无",
            num_variants=num_variants,
            feedback=feedback or "无",
        )

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        raw_text = call_llm(user_content, max_tokens=8192)
        scripts_data = parse_json_array(raw_text)

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
