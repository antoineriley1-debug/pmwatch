"""AI model selection. Add an adapter here to benchmark another model under
the same conditions."""
from __future__ import annotations

from .base import ReasoningModel

AVAILABLE_MODELS = [
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-fable-5-1",
]


def create_model(model_id: str) -> ReasoningModel:
    if model_id.startswith("claude-"):
        from .anthropic_model import ClaudeModel
        return ClaudeModel(model_id)
    raise ValueError(f"No adapter registered for model '{model_id}'.")
