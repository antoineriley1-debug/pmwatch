"""Claude adapter for the ReasoningModel interface."""
from __future__ import annotations

import base64
import json
import time

import anthropic

from . import prompts, schemas
from .base import ModelCall, ModelImage, ModelRefusal, ReasoningModel


def _image_block(image: ModelImage) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png",
                   "data": base64.standard_b64encode(image.png).decode()},
    }


class ClaudeModel(ReasoningModel):
    provider = "anthropic"

    def __init__(self, model_id: str, max_tokens: int = 32000):
        super().__init__()
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic()
        self._served_models: set[str] = set()

    def identity(self) -> dict:
        info = {"provider": self.provider, "model_id": self.model_id,
                "sdk_version": anthropic.__version__,
                "models_served": sorted(self._served_models)}
        try:
            meta = self.client.models.retrieve(self.model_id)
            info["display_name"] = meta.display_name
            info["created_at"] = str(meta.created_at)
        except anthropic.APIError as exc:
            info["lookup_error"] = str(exc)
        return info

    # ------------------------------------------------------------------
    def _call(self, purpose: str, content: list, schema: dict, effort: str) -> dict:
        record = ModelCall(purpose=purpose, model_requested=self.model_id)
        started = time.monotonic()
        try:
            with self.client.messages.stream(
                model=self.model_id,
                max_tokens=self.max_tokens,
                system=prompts.PARTICIPANT_SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": effort,
                               "format": {"type": "json_schema", "schema": schema}},
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIError as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            record.latency_s = time.monotonic() - started
            self.calls.append(record)
            raise
        record.latency_s = time.monotonic() - started
        record.model_served = message.model
        record.stop_reason = message.stop_reason or ""
        record.input_tokens = message.usage.input_tokens
        record.output_tokens = message.usage.output_tokens
        self._served_models.add(message.model)
        if message.stop_reason == "refusal":
            record.error = "refusal"
            self.calls.append(record)
            raise ModelRefusal(f"{purpose}: model declined the request")
        if message.stop_reason == "max_tokens":
            record.error = "max_tokens"
            self.calls.append(record)
            raise ValueError(f"{purpose}: response truncated at max_tokens")
        text = next((b.text for b in message.content if b.type == "text"), "{}")
        data = json.loads(text)
        record.response = data
        self.calls.append(record)
        return data

    # ------------------------------------------------------------------
    def analyze_screen(self, image: ModelImage, effort: str) -> dict:
        content = [_image_block(image),
                   {"type": "text", "text": prompts.PERCEPTION_INSTRUCTIONS.format(
                       width=image.width, height=image.height)}]
        return self._call("perception", content, schemas.SCREEN_SCHEMA, effort)

    def answer_question(self, context: dict, images: list[ModelImage], effort: str) -> dict:
        content: list = []
        for i, img in enumerate(images, 1):
            content.append({"type": "text", "text": f"Screenshot {i} of {len(images)} {img.caption}".strip()})
            content.append(_image_block(img))
        content.append({"type": "text", "text": prompts.ANSWER_INSTRUCTIONS.format(**context)})
        return self._call("answer", content, schemas.ANSWER_SCHEMA, effort)

    def review_answer(self, context: dict, current: dict, image: ModelImage, effort: str) -> dict:
        text = prompts.REVIEW_INSTRUCTIONS.format(
            current_answer=current.get("display", ""),
            reasoning=current.get("reasoning_summary", ""),
            **context)
        return self._call("review", [_image_block(image), {"type": "text", "text": text}],
                          schemas.REVIEW_SCHEMA, effort)

    def infer_unknown_screen(self, summary: str, image: ModelImage, effort: str) -> dict:
        text = prompts.UNKNOWN_INSTRUCTIONS.format(summary=summary)
        return self._call("unknown_state", [_image_block(image), {"type": "text", "text": text}],
                          schemas.UNKNOWN_SCHEMA, effort)

    def verify_action(self, before: ModelImage, after: ModelImage, intent: str,
                      expectation: str, effort: str) -> dict:
        content = [
            {"type": "text", "text": prompts.VERIFY_INSTRUCTIONS.format(intent=intent, expectation=expectation)},
            {"type": "text", "text": "BEFORE:"}, _image_block(before),
            {"type": "text", "text": "AFTER:"}, _image_block(after),
        ]
        return self._call("verify", content, schemas.VERIFY_SCHEMA, effort)
