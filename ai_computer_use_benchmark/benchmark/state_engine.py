"""Screen State Engine (spec section 5). Several states can hold at once."""
from __future__ import annotations

from .core import ElementKind, ScreenAnalysis, ScreenState

_NEXT_KINDS = (ElementKind.BUTTON_NEXT, ElementKind.BUTTON_CONTINUE)


def classify(analysis: ScreenAnalysis) -> set[ScreenState]:
    states: set[ScreenState] = set()
    if not analysis.parse_ok:
        return {ScreenState.UNKNOWN_STATE}

    if analysis.is_test_complete or analysis.is_results_screen:
        states.add(ScreenState.TEST_COMPLETE)
    if analysis.is_loading:
        states.add(ScreenState.LOADING)
    if analysis.has_error_message:
        states.add(ScreenState.ERROR)
    if analysis.has_confirmation_dialog:
        states.add(ScreenState.CONFIRMATION_REQUIRED)

    if analysis.is_question_screen and (analysis.question_text or analysis.options()):
        states.add(ScreenState.QUESTION_READY)
        if analysis.content_continues_below or analysis.content_continues_above:
            states.add(ScreenState.QUESTION_REQUIRES_SCROLL)
        if analysis.selected_options() or any(e.value for e in analysis.of_kind(ElementKind.TEXT_FIELD)):
            states.add(ScreenState.ANSWER_SELECTED)
    if analysis.answer_submitted_indicator:
        states.add(ScreenState.ANSWER_SUBMITTED)

    if analysis.of_kind(ElementKind.BUTTON_SUBMIT, ElementKind.BUTTON_SAVE, enabled_only=True):
        states.add(ScreenState.SUBMIT_AVAILABLE)
    if analysis.of_kind(*_NEXT_KINDS, ElementKind.BUTTON_FINISH, enabled_only=True):
        states.add(ScreenState.NEXT_AVAILABLE)
    if analysis.of_kind(ElementKind.QUESTION_NAV_NUMBER, enabled_only=True):
        states.add(ScreenState.NUMBER_NAVIGATION_AVAILABLE)

    meaningful = states - {ScreenState.SUBMIT_AVAILABLE, ScreenState.NEXT_AVAILABLE,
                           ScreenState.NUMBER_NAVIGATION_AVAILABLE}
    if not meaningful and not states:
        states.add(ScreenState.UNKNOWN_STATE)
    elif not meaningful and not analysis.is_question_screen:
        # Only navigation controls with no recognizable question/dialog/result:
        # still unfamiliar, but a navigation control may be the safe way forward.
        states.add(ScreenState.UNKNOWN_STATE)
    return states


def describe(states: set[ScreenState]) -> str:
    order = list(ScreenState)
    return " + ".join(s.value for s in sorted(states, key=order.index)) or ScreenState.UNKNOWN_STATE.value
