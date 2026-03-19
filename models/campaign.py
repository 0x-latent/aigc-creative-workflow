from dataclasses import dataclass
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
    page_type: str = ""  # "cover" / "body" / "summary" for graphic platforms


@dataclass
class Script:
    id: str
    outline: str
    scenes: list[Scene]
    visual_style: str = ""


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


@dataclass
class ScriptBranch:
    script_index: int
    confirmed_style: str = ""
    images: list[GeneratedImage] | None = None


@dataclass
class DirectionBranch:
    direction_index: int
    scripts: list[Script] | None = None
    selected_script_indices: list[int] | None = None
    script_branches: list[ScriptBranch] | None = None


@dataclass
class ConceptBranch:
    concept_index: int
    directions: list[Direction] | None = None
    selected_direction_indices: list[int] | None = None
    direction_branches: list[DirectionBranch] | None = None
