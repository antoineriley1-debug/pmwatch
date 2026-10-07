"""Verification Engine (spec section 10): compare BEFORE vs AFTER and decide
whether the intended action actually happened."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .core import ElementKind, Observation, ScreenState, same_question, text_similarity
from .perception.capture import changed_fraction


@dataclass
class Expectation:
    kind: str           # option_selected | option_deselected | text_entered | submitted |
                        # advanced | nav_to_number | dialog_handled | scrolled | screen_changed
    description: str
    label: str = ""
    letter: str = ""
    text: str = ""
    previous_question_key: str = ""
    target_number: Optional[int] = None
    region: Optional[tuple[int, int, int, int]] = None   # screen pixels


def _local_region(obs: Observation, region):
    if not region:
        return None
    shot = obs.screenshot
    pad = 10
    return (region[0] - shot.left - pad, region[1] - shot.top - pad,
            region[2] - shot.left + pad, region[3] - shot.top + pad)


class Verifier:
    def __init__(self, perceiver, effort: str):
        self.perceiver = perceiver
        self.model = perceiver.model
        self.effort = effort

    def verify(self, before: Observation, after: Observation, exp: Expectation) -> tuple[bool, str]:
        a = after.analysis
        whole = changed_fraction(before.screenshot.image, after.screenshot.image)
        local = changed_fraction(before.screenshot.image, after.screenshot.image,
                                 _local_region(before, exp.region)) if exp.region else whole
        advanced = bool(a.question_key()) and not same_question(a.question_key(), exp.previous_question_key)
        complete = ScreenState.TEST_COMPLETE in after.states

        if exp.kind == "option_selected":
            el = a.find_option(exp.label, exp.letter)
            if el is not None and el.selected:
                return True, f"'{el.label}' is visibly selected"
            if local > 0.01:
                return self._model_check(before, after, exp)
            return False, "selection not visible and the option area did not change"

        if exp.kind == "option_deselected":
            el = a.find_option(exp.label, exp.letter)
            if el is not None and not el.selected:
                return True, f"'{el.label}' is no longer selected"
            return False, "option still appears selected"

        if exp.kind == "text_entered":
            fields = a.of_kind(ElementKind.TEXT_FIELD)
            if any(text_similarity(f.value, exp.text) >= 0.85 for f in fields):
                return True, "typed text is visible in the field"
            if local > 0.005:
                return self._model_check(before, after, exp)
            return False, "typed text not visible"

        if exp.kind == "submitted":
            if a.answer_submitted_indicator or advanced or complete:
                return True, "submission acknowledged"
            if ScreenState.CONFIRMATION_REQUIRED in after.states:
                return True, "confirmation requested after submit"
            new_nav = (ScreenState.NEXT_AVAILABLE in after.states
                       and ScreenState.NEXT_AVAILABLE not in before.states)
            if new_nav:
                return True, "navigation became available after submit"
            if whole > 0.003:
                return self._model_check(before, after, exp)
            return False, "screen unchanged after submit"

        if exp.kind == "advanced":
            if complete:
                return True, "test complete screen reached"
            if advanced and ScreenState.QUESTION_READY in after.states:
                return True, f"new question {a.question_key()} recognized"
            if ScreenState.CONFIRMATION_REQUIRED in after.states and \
                    ScreenState.CONFIRMATION_REQUIRED not in before.states:
                return True, "confirmation dialog appeared"
            if a.answer_submitted_indicator and not before.analysis.answer_submitted_indicator:
                return True, "answer submitted; navigation continues"
            return False, "question did not change"

        if exp.kind == "nav_to_number":
            if a.question_number == exp.target_number:
                return True, f"question {exp.target_number} displayed"
            return False, f"expected question {exp.target_number}, saw {a.question_number}"

        if exp.kind == "dialog_handled":
            if ScreenState.CONFIRMATION_REQUIRED not in after.states:
                return True, "dialog dismissed"
            return False, "dialog still present"

        if exp.kind == "scrolled":
            if exp.previous_question_key and a.question_key() and advanced:
                return False, "scroll changed the question (treated as navigation, not scrolling)"
            if whole > 0.01:
                return True, "viewport content moved"
            return False, "viewport did not move (end of content?)"

        if exp.kind == "screen_changed":
            if whole > 0.003 or after.states != before.states:
                return True, "screen changed"
            return False, "screen unchanged"

        return False, f"unknown expectation '{exp.kind}'"

    def _model_check(self, before: Observation, after: Observation, exp: Expectation) -> tuple[bool, str]:
        """Pixel evidence is ambiguous: ask the model to compare the two screens."""
        try:
            b, _ = self.perceiver.model_image(before.screenshot, "BEFORE")
            a, _ = self.perceiver.model_image(after.screenshot, "AFTER")
            result = self.model.verify_action(b, a, exp.description, exp.description, self.effort)
        except Exception as exc:
            return False, f"verification call failed: {exc}"
        return bool(result.get("action_succeeded")), "model: " + result.get("observation", "")
