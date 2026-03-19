import os

from models.brand import PlatformKB


class PlatformKBReader:
    def __init__(self, platforms_dir: str = "platforms"):
        self.platforms_dir = platforms_dir

    def load(self, platform: str) -> PlatformKB:
        """Load platform knowledge base. Returns empty content if file not found."""
        file_path = os.path.join(self.platforms_dir, f"{platform}.md")
        if not os.path.exists(file_path):
            return PlatformKB(platform=platform, raw_md="", file_path="")

        with open(file_path, "r", encoding="utf-8") as f:
            raw_md = f.read()

        return PlatformKB(platform=platform, raw_md=raw_md, file_path=file_path)
