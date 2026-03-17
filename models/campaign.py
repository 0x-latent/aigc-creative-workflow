from dataclasses import dataclass, field
from models.base import GenerationMeta


@dataclass
class CampaignGoal:
    campaign_id: str
    brand_id: str
    objective: str
    platform: str
    notes: str


@dataclass
class Concept:
    id: str
    title: str
    description: str
    rationale: str


@dataclass
class ConceptResult:
    concepts: list[Concept]
    meta: GenerationMeta


@dataclass
class Direction:
    id: str
    title: str
    description: str
    platform_notes: str


@dataclass
class DirectionResult:
    directions: list[Direction]
    meta: GenerationMeta


@dataclass
class Scene:
    scene_no: int
    duration_sec: int
    visual_description: str
    voiceover: str
    image_prompt: str


@dataclass
class Script:
    id: str
    outline: str
    scenes: list[Scene]


@dataclass
class ScriptResult:
    scripts: list[Script]
    meta: GenerationMeta


@dataclass
class GeneratedImage:
    scene_no: int
    script_id: str
    image_prompt: str
    image_path: str
    model: str
    generation_params: dict


@dataclass
class ImageResult:
    images: list[GeneratedImage]
    meta: GenerationMeta
