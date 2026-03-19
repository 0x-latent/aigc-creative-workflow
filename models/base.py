from dataclasses import dataclass
from typing import Optional


@dataclass
class GenerationMeta:
    prompt_template: str
    model: str
    timestamp: str
    input_hash: str


@dataclass
class ReviewDecision:
    status: str       # "approved" or "rejected"
    feedback: str     # required when rejected
    timestamp: str
    selected_index: Optional[int] = None  # 0-based index of the selected item
    selected_indices: Optional[list[int]] = None  # for multi-select
