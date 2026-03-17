import hashlib
import os
from models.brand import BrandKB


class BrandKBReader:
    def __init__(self, brands_dir: str = "brands"):
        self.brands_dir = brands_dir

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
