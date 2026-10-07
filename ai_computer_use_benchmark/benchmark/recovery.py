"""Recovery Manager (spec section 11).

Action failed -> capture fresh screen -> reclassify -> relocate intended
control -> determine whether page changed -> corrected interaction -> verify.
Never clicks the same location twice for one action."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .core import (Action, ElementKind, Observation, ScreenAnalysis, ScreenState, UIElement, same_question,
                   text_similarity)
from .verification import Expectation

_BUTTON_KINDS = (
    ElementKind.BUTTON_SUBMIT, ElementKind.BUTTON_NEXT, ElementKind.BUTTON_CONTINUE,
    ElementKind.BUTTON_FINISH, ElementKind.BUTTON_SAVE, ElementKind.BUTTON_CONFIRM,
    ElementKind.BUTTON_CLOSE, ElementKind.BUTTON_CANCEL, ElementKind.BUTTON_PREVIOUS,
)
SAME_POINT_TOLERANCE = 6


def locate(action: Action, analysis: ScreenAnalysis) -> Optional[UIElement]:
    """Find the intended control on the current screen by meaning."""
    if action.purpose in ("select_answer", "deselect_answer"):
        return analysis.find_option(action.target_label, action.target_letter)
    if action.target_kind == ElementKind.TEXT_FIELD:
        fields = analysis.of_kind(ElementKind.TEXT_FIELD, enabled_only=True)
        return fields[0] if fields else None
    if action.target_kind == ElementKind.QUESTION_NAV_NUMBER and action.nav_number is not None:
        return analysis.nav_number_element(action.nav_number)
    if action.target_kind is not None:
        same_kind = [e for e in analysis.of_kind(action.target_kind) if not e.disabled]
        if same_kind:
            return max(same_kind, key=lambda e: text_similarity(e.label, action.target_label))
        # Re-perception may name the same control differently (Next vs Continue):
        # fall back to any enabled button with the same visible label.
        buttons = [e for e in analysis.of_kind(*_BUTTON_KINDS) if not e.disabled]
        if buttons and action.target_label:
            best = max(buttons, key=lambda e: text_similarity(e.label, action.target_label))
            if text_similarity(best.label, action.target_label) >= 0.75:
                return best
    if action.target_label:
        best = max(analysis.elements, key=lambda e: text_similarity(e.label, action.target_label), default=None)
        if best is not None and text_similarity(best.label, action.target_label) >= 0.85:
            return best
    return None


def candidate_points(el: UIElement) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = el.bbox
    cy = (y0 + y1) // 2
    w = max(1, x1 - x0)
    return [
        el.click_point,
        el.center,
        (x0 + min(18, w // 4), cy),      # leading control (radio/checkbox) side
        (x0 + w // 3, cy),
        (x1 - min(18, w // 4), cy),
    ]


def choose_point(el: UIElement, tried: list[tuple[int, int]]) -> Optional[tuple[int, int]]:
    for p in candidate_points(el):
        if all(abs(p[0] - t[0]) > SAME_POINT_TOLERANCE or abs(p[1] - t[1]) > SAME_POINT_TOLERANCE
               for t in tried):
            return p
    return None


@dataclass
class RecoveryOutcome:
    status: str                       # late_success | retry | page_changed | not_found
    observation: Observation
    element: Optional[UIElement] = None
    note: str = ""


class RecoveryManager:
    def __init__(self, observe, verifier, wait_for_settle):
        self.observe = observe
        self.verifier = verifier
        self.wait_for_settle = wait_for_settle

    def recover(self, action: Action, exp: Expectation, before: Observation) -> RecoveryOutcome:
        # 1-2. Fresh screen, reclassified (observe() runs perception + state engine).
        fresh = self.wait_for_settle(self.observe("recovery"))

        # Did the action land late (slow UI)? Re-verify against the original BEFORE.
        ok, msg = self.verifier.verify(before, fresh, exp)
        if ok:
            return RecoveryOutcome("late_success", fresh, note=msg)

        # 4. Page changed in an unintended way?
        before_key, now_key = before.analysis.question_key(), fresh.analysis.question_key()
        unexpected = (
            (before_key and now_key and not same_question(before_key, now_key) and exp.kind not in ("advanced", "nav_to_number"))
            or (ScreenState.UNKNOWN_STATE in fresh.states and ScreenState.UNKNOWN_STATE not in before.states)
        )
        if unexpected:
            return RecoveryOutcome("page_changed", fresh, note=f"screen changed from {before_key or 'n/a'} "
                                                               f"to {now_key or 'unrecognized'}")

        # 3. Relocate the intended control on the fresh screen.
        el = locate(action, fresh.analysis)
        if el is None:
            return RecoveryOutcome("not_found", fresh, note=f"could not relocate {action.description}")
        return RecoveryOutcome("retry", fresh, element=el, note=f"relocated {el.describe()} at {el.click_point}")
