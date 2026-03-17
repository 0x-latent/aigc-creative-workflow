import hashlib
import json
import os
from datetime import datetime, timezone

import anthropic

from models.base import GenerationMeta
from models.brand import BrandKB
from models.campaign import CampaignGoal, Concept, Direction, DirectionResult
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE = "direction_gen_v1.txt"
MODEL = "claude-sonnet-4-20250514"


class DirectionGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        self.client = anthropic.Anthropic()
        self.tracker = CampaignTracker()

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        concept: Concept,
        feedback: str = "",
    ) -> DirectionResult:
        template_path = os.path.join(self.prompts_dir, PROMPT_TEMPLATE)
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        user_content = template.format(
            brand_kb=brand_kb.raw_md,
            concept_title=concept.title,
            concept_description=concept.description,
            concept_rationale=concept.rationale,
            objective=goal.objective,
            platform=goal.platform,
            feedback=feedback or "无",
        )

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = response.content[0].text
        directions_data = self._parse_json(raw_text)

        directions = [
            Direction(
                id=f"direction_{i+1}",
                title=d["title"],
                description=d["description"],
                platform_notes=d["platform_notes"],
            )
            for i, d in enumerate(directions_data)
        ]

        meta = GenerationMeta(
            prompt_template=PROMPT_TEMPLATE,
            model=MODEL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            input_hash=input_hash,
        )

        result = DirectionResult(directions=directions, meta=meta)

        self.tracker.record(
            campaign_id=goal.campaign_id,
            step="direction_gen",
            input_snapshot={
                "concept_id": concept.id,
                "concept_title": concept.title,
                "feedback": feedback,
            },
            output_snapshot={"directions": directions_data},
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
