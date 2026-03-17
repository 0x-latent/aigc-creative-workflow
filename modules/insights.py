import hashlib
import os
from models.brand import InsightsBundle


class InsightsLoader:
    def __init__(self, brands_dir: str = "brands"):
        self.brands_dir = brands_dir

    def load(self, brand_id: str) -> InsightsBundle:
        insights_dir = os.path.join(self.brands_dir, brand_id, "insights")
        if not os.path.exists(insights_dir):
            return InsightsBundle(
                brand_id=brand_id, raw_text="", sources=[], version=""
            )

        md_files = sorted(
            f for f in os.listdir(insights_dir) if f.endswith(".md")
        )
        if not md_files:
            return InsightsBundle(
                brand_id=brand_id, raw_text="", sources=[], version=""
            )

        parts = []
        sources = []
        hash_parts = []

        for fname in md_files:
            fpath = os.path.join(insights_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            parts.append(f"--- 来源: {fname} ---\n{content}")
            sources.append(fpath)
            hash_parts.append(hashlib.md5(content.encode("utf-8")).hexdigest())

        raw_text = "\n\n".join(parts)
        combined_hash = hashlib.md5("".join(hash_parts).encode("utf-8")).hexdigest()

        return InsightsBundle(
            brand_id=brand_id,
            raw_text=raw_text,
            sources=sources,
            version=combined_hash,
        )
