"""Action Planner: decides the next semantic action from what is on screen
now (spec sections 5 and 7). It never uses stored coordinates; it names the
control, and the executor finds it on the current screen."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .core import Action, ElementKind, Observation, ScreenState
from .verification import Expectation


@dataclass
class NavigationFlow:
    """Progress through the post-answer sequence for one question."""
    question_key: str
    question_number: Optional[int]
    submitted: bool = False
    saved: bool = False
    used: list[str] = field(default_factory=list)


def plan_navigation(obs: Observation, flow: NavigationFlow) -> Optional[tuple[Action, Expectation]]:
    """Pick the next step of the navigation sequence the interface is showing:
    Answer -> Next | Submit -> Next/Continue | Save -> Next | numbered question |
    confirmation -> Continue | Finish."""
    a, states = obs.analysis, obs.states

    if ScreenState.CONFIRMATION_REQUIRED in states:
        confirm = (a.of_kind(ElementKind.BUTTON_CONFIRM, enabled_only=True)
                   or a.of_kind(ElementKind.BUTTON_CONTINUE, enabled_only=True)
                   or a.of_kind(ElementKind.BUTTON_SUBMIT, enabled_only=True)
                   or a.of_kind(ElementKind.BUTTON_FINISH, enabled_only=True))
        if confirm:
            el = confirm[0]
            return (Action("click", "confirm", el.kind, el.label, description=f"confirm dialog via '{el.label}'"),
                    Expectation("dialog_handled", f"dialog '{a.dialog_text[:80]}' is confirmed and closes",
                                previous_question_key=flow.question_key))

    submit = a.of_kind(ElementKind.BUTTON_SUBMIT, enabled_only=True)
    if submit and not flow.submitted and not a.answer_submitted_indicator:
        el = submit[0]
        return (Action("click", "submit", el.kind, el.label, description=f"submit answer via '{el.label}'"),
                Expectation("submitted", "the answer is submitted", previous_question_key=flow.question_key,
                            region=el.bbox))

    save = a.of_kind(ElementKind.BUTTON_SAVE, enabled_only=True)
    if save and not flow.saved and not a.answer_submitted_indicator:
        el = save[0]
        return (Action("click", "save", el.kind, el.label, description=f"save answer via '{el.label}'"),
                Expectation("submitted", "the answer is saved", previous_question_key=flow.question_key,
                            region=el.bbox))

    forward = a.of_kind(ElementKind.BUTTON_NEXT, ElementKind.BUTTON_CONTINUE, enabled_only=True)
    if forward:
        el = forward[0]
        return (Action("click", "next", el.kind, el.label, description=f"advance via '{el.label}'"),
                Expectation("advanced", "the next question (or next step) is displayed",
                            previous_question_key=flow.question_key))

    if flow.question_number is not None:
        target = a.nav_number_element(flow.question_number + 1)
        if target is not None:
            return (Action("click", "number_nav", ElementKind.QUESTION_NAV_NUMBER, target.label,
                           nav_number=flow.question_number + 1,
                           description=f"open question {flow.question_number + 1} from numbered navigation"),
                    Expectation("nav_to_number", f"question {flow.question_number + 1} is displayed",
                                previous_question_key=flow.question_key,
                                target_number=flow.question_number + 1))

    finish = a.of_kind(ElementKind.BUTTON_FINISH, enabled_only=True)
    if finish:
        el = finish[0]
        return (Action("click", "finish", el.kind, el.label, description=f"finish via '{el.label}'"),
                Expectation("advanced", "the test finishes or asks for confirmation",
                            previous_question_key=flow.question_key))
    return None


def plan_dialog(obs: Observation) -> Optional[tuple[Action, Expectation]]:
    """A confirmation dialog or pop-up outside the question flow."""
    flow = NavigationFlow(question_key=obs.analysis.question_key(), question_number=obs.analysis.question_number)
    step = plan_navigation(obs, flow)
    if step and step[0].purpose == "confirm":
        return step
    close = obs.analysis.of_kind(ElementKind.BUTTON_CLOSE, enabled_only=True)
    if close:
        el = close[0]
        return (Action("click", "dismiss_popup", el.kind, el.label, description=f"close pop-up via '{el.label}'"),
                Expectation("screen_changed", "the pop-up closes"))
    return None


def content_scroll_point(obs: Observation) -> tuple[int, int]:
    """Where to put the pointer to scroll the question content: the middle of
    the question/answers area found on THIS screen, else the screen centre."""
    a, shot = obs.analysis, obs.screenshot
    boxes = [e.bbox for e in a.options()] or [e.bbox for e in a.elements if e.kind != ElementKind.SCROLLBAR]
    if boxes:
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes)
        y1 = max(b[3] for b in boxes)
        return (x0 + x1) // 2, (y0 + y1) // 2
    w, h = shot.size
    return shot.left + w // 2, shot.top + h // 2
