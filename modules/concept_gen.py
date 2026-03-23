import hashlib
import os
from datetime import datetime, timezone

from config import LLM_MODEL, logger
from models.base import GenerationMeta
from models.brand import BrandKB, InsightsBundle
from models.campaign import CampaignGoal, Concept, ConceptResult
from modules.llm_util import call_llm, parse_json_array
from modules.tracker import CampaignTracker

PROMPT_TEMPLATE = "concept_gen_v1.txt"


class ConceptGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
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

        raw_text = call_llm(user_content, max_tokens=8192)
        concepts_data = parse_json_array(raw_text)

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
            model=LLM_MODEL,
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
            model=LLM_MODEL,
            input_hash=input_hash,
        )

        return result
