from dataclasses import dataclass


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
