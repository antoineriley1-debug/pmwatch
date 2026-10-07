"""Swappable AI model interface (spec section 2).

The orchestrator talks only to this interface, so different models can be
benchmarked under identical conditions. Adapters receive images as PNG
bytes and return plain dicts that match the schemas in schemas.py. Nothing
here knows about Windows, the mouse or the keyboard."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ModelImage:
    png: bytes
    width: int
    height: int
    caption: str = ""


@dataclass
class ModelCall:
    """Raw record of one model call, kept for the audit trail."""
    purpose: str
    model_requested: str
    model_served: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    error: str = ""
    response: dict = field(default_factory=dict)


class ModelRefusal(RuntimeError):
    pass


class ReasoningModel(ABC):
    model_id: str

    def __init__(self):
        self.calls: list[ModelCall] = []

    @abstractmethod
    def identity(self) -> dict:
        """Provider, model id and version information recorded with the run."""

    @abstractmethod
    def analyze_screen(self, image: ModelImage, effort: str) -> dict:
        """Full-screen perception -> SCREEN_SCHEMA dict."""

    @abstractmethod
    def answer_question(self, context: dict, images: list[ModelImage], effort: str) -> dict:
        """-> ANSWER_SCHEMA dict."""

    @abstractmethod
    def review_answer(self, context: dict, current: dict, image: ModelImage, effort: str) -> dict:
        """Dwell-time recheck -> REVIEW_SCHEMA dict."""

    @abstractmethod
    def infer_unknown_screen(self, summary: str, image: ModelImage, effort: str) -> dict:
        """-> UNKNOWN_SCHEMA dict."""

    @abstractmethod
    def verify_action(self, before: ModelImage, after: ModelImage, intent: str,
                      expectation: str, effort: str) -> dict:
        """-> VERIFY_SCHEMA dict."""
