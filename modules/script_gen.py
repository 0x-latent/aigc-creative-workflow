import hashlib
import json
import os
from datetime import datetime, timezone

import anthropic

from models.base import GenerationMeta
from models.brand import BrandKB
from models.campaign import (
    CampaignGoal,
    Direction,
    Scene,
    Script,
    ScriptResult,
)
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE = "script_gen_v1.txt"
MODEL = "claude-sonnet-4-20250514"


class ScriptGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        self.client = anthropic.Anthropic()
        self.tracker = CampaignTracker()

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        direction: Direction,
        num_variants: int = 3,
        feedback: str = "",
    ) -> ScriptResult:
        template_path = os.path.join(self.prompts_dir, PROMPT_TEMPLATE)
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        user_content = template.format(
            brand_kb=brand_kb.raw_md,
            direction_title=direction.title,
            direction_description=direction.description,
            platform_notes=direction.platform_notes,
            objective=goal.objective,
            platform=goal.platform,
            num_variants=num_variants,
            feedback=feedback or "无",
        )

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = response.content[0].text
        scripts_data = self._parse_json(raw_text)

        scripts = []
        for i, s in enumerate(scripts_data):
            scenes = [
                Scene(
                    scene_no=sc["scene_no"],
                    duration_sec=sc["duration_sec"],
                    visual_description=sc["visual_description"],
                    voiceover=sc["voiceover"],
                    image_prompt=sc["image_prompt"],
                )
                for sc in s["scenes"]
            ]
            scripts.append(
                Script(id=f"script_{i+1}", outline=s["outline"], scenes=scenes)
            )

        meta = GenerationMeta(
            prompt_template=PROMPT_TEMPLATE,
            model=MODEL,
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
            prompt_template=PROMPT_TEMPLATE,
            model=MODEL,
            input_hash=input_hash,
        )

        return result

    def _parse_json(self, text: str) -> list[dict]:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"Cannot parse JSON from response: {text[:200]}")
