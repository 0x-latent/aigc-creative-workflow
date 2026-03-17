from dataclasses import dataclass


@dataclass
class BrandKB:
    brand_id: str
    name: str
    raw_md: str
    version: str
    file_path: str


@dataclass
class InsightsBundle:
    brand_id: str
    raw_text: str
    sources: list[str]
    version: str
