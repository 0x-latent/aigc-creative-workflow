import hashlib
import json
import os
from datetime import datetime, timezone

import anthropic

from models.base import GenerationMeta
from models.brand import BrandKB, InsightsBundle
from models.campaign import CampaignGoal, Concept, ConceptResult
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE = "concept_gen_v1.txt"
MODEL = "claude-sonnet-4-20250514"


class ConceptGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        self.client = anthropic.Anthropic()
        self.tracker = CampaignTracker()

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        insights: InsightsBundle,
        feedback: str = "",
    ) -> ConceptResult:
        template_path = os.path.join(self.prompts_dir, PROMPT_TEMPLATE)
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        user_content = template.format(
            brand_kb=brand_kb.raw_md,
            insights=insights.raw_text,
            objective=goal.objective,
            platform=goal.platform,
            notes=goal.notes,
            feedback=feedback or "无",
        )

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = response.content[0].text
        # Extract JSON from response
        concepts_data = self._parse_json(raw_text)

        concepts = [
            Concept(
                id=f"concept_{i+1}",
                title=c["title"],
                description=c["description"],
                rationale=c["rationale"],
            )
            for i, c in enumerate(concepts_data)
        ]

        meta = GenerationMeta(
            prompt_template=PROMPT_TEMPLATE,
            model=MODEL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            input_hash=input_hash,
        )

        result = ConceptResult(concepts=concepts, meta=meta)

        self.tracker.record(
            campaign_id=goal.campaign_id,
            step="concept_gen",
            input_snapshot={
                "objective": goal.objective,
                "platform": goal.platform,
                "brand_version": brand_kb.version,
                "feedback": feedback,
            },
            output_snapshot={"concepts": concepts_data},
            prompt_template=PROMPT_TEMPLATE,
            model=MODEL,
            input_hash=input_hash,
        )

        return result

    def _parse_json(self, text: str) -> list[dict]:
        # Try to find JSON array in response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"Cannot parse JSON from response: {text[:200]}")
