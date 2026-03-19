import hashlib
import os
from datetime import datetime, timezone

from config import LLM_MODEL, logger
from models.base import GenerationMeta
from models.brand import BrandKB
from models.campaign import CampaignGoal, Concept, Direction, DirectionResult
from modules.llm_util import call_llm, parse_json_array
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE = "direction_gen_v1.txt"


class DirectionGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        self.tracker = CampaignTracker()

    def generate(
        self,
        goal: CampaignGoal,
        brand_kb: BrandKB,
        concept: Concept,
        feedback: str = "",
        platform_kb: str = "",
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
            platform_kb=platform_kb or "无",
            feedback=feedback or "无",
        )

        input_hash = hashlib.md5(user_content.encode("utf-8")).hexdigest()

        raw_text = call_llm(user_content)
        directions_data = parse_json_array(raw_text)

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
            model=LLM_MODEL,
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
            model=LLM_MODEL,
            input_hash=input_hash,
        )

        return result
