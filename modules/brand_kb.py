import hashlib
import os
import re
from models.brand import BrandKB

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Sections of knowledge base relevant to script/image generation
# (product appearance, brand identity, target audience, visual assets)
_SCRIPT_RELEVANT_HEADINGS = {
    "品牌概述", "产品信息", "基本信息", "产品规格",
    "品牌核心传播概念", "沟通概念", "人群洞察", "品牌定位",
    "差异化优势", "信任支撑",
    "目标人群", "品牌视觉资产",
}


def extract_script_kb(raw_md: str) -> str:
    """Extract only the sections of brand KB relevant to script generation.

    Keeps: brand overview, product info, positioning, target audience, visual assets.
    Drops: clinical data, competitor analysis, market data, history, detailed mechanisms.
    """
    lines = raw_md.split("\n")
    result = []
    include = True  # include content before the first heading (brand name etc.)

    for line in lines:
        heading_match = re.match(r"^(#{1,3})\s+(.+)", line)
        if heading_match:
            heading_text = heading_match.group(2).strip()
            # Check if this heading or any relevant heading is a substring match
            include = any(h in heading_text or heading_text in h for h in _SCRIPT_RELEVANT_HEADINGS)
        if include:
            result.append(line)

    extracted = "\n".join(result).strip()
    return extracted if extracted else raw_md  # fallback to full KB if extraction yields nothing


class BrandKBReader:
    def __init__(self, brands_dir: str = "brands"):
        self.brands_dir = brands_dir

    def discover_brand_images(self, brand_id: str) -> list[str]:
        """Discover product images under brands/{brand_id}/image/. Returns empty list if none."""
        image_dir = os.path.join(self.brands_dir, brand_id, "image")
        if not os.path.isdir(image_dir):
            return []
        images = []
        for fname in sorted(os.listdir(image_dir)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                images.append(os.path.join(image_dir, fname))
        return images

    def load(self, brand_id: str) -> BrandKB:
        file_path = os.path.join(self.brands_dir, brand_id, "knowledge_base.md")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Brand knowledge base not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            raw_md = f.read()

        version = hashlib.md5(raw_md.encode("utf-8")).hexdigest()

        # Extract brand name from first heading or use brand_id
        name = brand_id
        for line in raw_md.splitlines():
            if line.startswith("# "):
                name = line[2:].strip()
                break

        return BrandKB(
            brand_id=brand_id,
            name=name,
            raw_md=raw_md,
            version=version,
            file_path=file_path,
        )
