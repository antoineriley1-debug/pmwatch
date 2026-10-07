"""Shared data types for every module."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ScreenState(str, Enum):
    QUESTION_READY = "QUESTION_READY"
    QUESTION_REQUIRES_SCROLL = "QUESTION_REQUIRES_SCROLL"
    ANSWER_SELECTED = "ANSWER_SELECTED"
    SUBMIT_AVAILABLE = "SUBMIT_AVAILABLE"
    ANSWER_SUBMITTED = "ANSWER_SUBMITTED"
    NEXT_AVAILABLE = "NEXT_AVAILABLE"
    NUMBER_NAVIGATION_AVAILABLE = "NUMBER_NAVIGATION_AVAILABLE"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    LOADING = "LOADING"
    ERROR = "ERROR"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    TEST_COMPLETE = "TEST_COMPLETE"


class QuestionType(str, Enum):
    # Supported in the initial version
    SINGLE_CHOICE = "single_choice"
    TRUE_FALSE = "true_false"
    YES_NO = "yes_no"
    MULTI_SELECT = "multi_select"
    SHORT_TEXT = "short_text"
    # Architecture allows these later
    NUMERICAL = "numerical"
    MATCHING = "matching"
    DROPDOWN = "dropdown"
    ORDERING = "ordering"
    IMAGE = "image"
    CHART = "chart"
    TABLE = "table"
    DRAG_AND_DROP = "drag_and_drop"
    MULTI_PART = "multi_part"
    OTHER = "other"
    NONE = "none"


class ElementKind(str, Enum):
    ANSWER_OPTION = "answer_option"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXT_FIELD = "text_field"
    BUTTON_SUBMIT = "button_submit"
    BUTTON_NEXT = "button_next"
    BUTTON_PREVIOUS = "button_previous"
    BUTTON_CONTINUE = "button_continue"
    BUTTON_FINISH = "button_finish"
    BUTTON_SAVE = "button_save"
    BUTTON_CONFIRM = "button_confirm"
    BUTTON_CANCEL = "button_cancel"
    BUTTON_CLOSE = "button_close"
    QUESTION_NAV_NUMBER = "question_nav_number"
    SCROLLBAR = "scrollbar"
    DROPDOWN = "dropdown"
    LINK = "link"
    IMAGE = "image"
    TABLE = "table"
    OTHER = "other"


class FailureCategory(str, Enum):
    PERCEPTION = "PERCEPTION ERROR"
    REASONING = "REASONING ERROR"
    KNOWLEDGE = "KNOWLEDGE ERROR"
    NAVIGATION = "NAVIGATION ERROR"
    INTERACTION = "INTERACTION ERROR"
    VERIFICATION = "VERIFICATION ERROR"
    UNKNOWN = "UNKNOWN"


OPTION_KINDS = {ElementKind.ANSWER_OPTION, ElementKind.CHECKBOX, ElementKind.RADIO}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def text_similarity(a: str, b: str) -> float:
    a, b = normalize_text(a), normalize_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class UIElement:
    """One element found on the CURRENT screen. Coordinates are screen pixels
    computed fresh from this screenshot; they are never reused across screens."""
    id: str
    kind: ElementKind
    label: str
    bbox: tuple[int, int, int, int]            # x0, y0, x1, y1 (screen pixels)
    click_point: tuple[int, int]               # where a human would click
    selected: bool = False
    disabled: bool = False
    nav_number: Optional[int] = None
    option_letter: str = ""
    value: str = ""

    @property
    def center(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.bbox
        return (x0 + x1) // 2, (y0 + y1) // 2

    def describe(self) -> str:
        return f"{self.kind.value} '{self.label}'"


@dataclass
class ScreenAnalysis:
    """Everything perception extracted from one screenshot."""
    screen_purpose: str = ""
    is_question_screen: bool = False
    question_number: Optional[int] = None
    total_questions: Optional[int] = None
    question_text: str = ""
    instructions: str = ""
    question_type: QuestionType = QuestionType.NONE
    has_image_or_diagram: bool = False
    has_table: bool = False
    content_continues_below: bool = False
    content_continues_above: bool = False
    is_loading: bool = False
    has_error_message: bool = False
    error_text: str = ""
    has_confirmation_dialog: bool = False
    dialog_text: str = ""
    has_popup: bool = False
    is_results_screen: bool = False
    results_summary: str = ""
    is_test_complete: bool = False
    answer_submitted_indicator: bool = False
    is_os_security_dialog: bool = False
    elements: list[UIElement] = field(default_factory=list)
    parse_ok: bool = True
    raw: dict = field(default_factory=dict)

    # ---- element queries -------------------------------------------------
    def of_kind(self, *kinds: ElementKind, enabled_only: bool = False) -> list[UIElement]:
        out = [e for e in self.elements if e.kind in kinds]
        if enabled_only:
            out = [e for e in out if not e.disabled]
        return out

    def options(self) -> list[UIElement]:
        return self.of_kind(*OPTION_KINDS)

    def selected_options(self) -> list[UIElement]:
        return [e for e in self.options() if e.selected]

    def find_option(self, label: str, letter: str = "") -> Optional[UIElement]:
        """Locate an answer option by what it says, not where it was."""
        best, best_score = None, 0.0
        for e in self.options():
            score = text_similarity(e.label, label)
            if letter and e.option_letter and normalize_text(e.option_letter) == normalize_text(letter):
                score = max(score, 0.9)
            if score > best_score:
                best, best_score = e, score
        return best if best_score >= 0.6 else None

    def find_by_kind_and_label(self, kind: ElementKind, label: str = "") -> Optional[UIElement]:
        candidates = self.of_kind(kind)
        if not candidates:
            return None
        if not label:
            return candidates[0]
        return max(candidates, key=lambda e: text_similarity(e.label, label))

    def nav_number_element(self, number: int) -> Optional[UIElement]:
        for e in self.of_kind(ElementKind.QUESTION_NAV_NUMBER, enabled_only=True):
            if e.nav_number == number:
                return e
        return None

    def question_key(self) -> str:
        """Identity of the question shown, used to tell whether navigation
        advanced. Combines the visible number and text; compare keys with
        same_question(), never with ==."""
        number = "" if self.question_number is None else str(self.question_number)
        text = normalize_text(self.question_text)[:200]
        if not text:
            text = "|".join(normalize_text(e.label) for e in self.options())[:200]
        if not number and not text:
            return ""
        return f"n{number}#{text}"


def same_question(key_a: str, key_b: str) -> bool:
    """True when two question keys refer to the same question. Numbers decide
    when both screens show one; otherwise the question text must match closely."""
    if not key_a or not key_b:
        return False
    num_a, _, text_a = key_a.partition("#")
    num_b, _, text_b = key_b.partition("#")
    if num_a != "n" and num_b != "n":
        return num_a == num_b
    return text_similarity(text_a, text_b) >= 0.85


@dataclass
class Screenshot:
    image: "object"                 # PIL.Image (full resolution)
    left: int                       # monitor origin in virtual-screen pixels
    top: int
    taken_at: float
    path: str = ""

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


@dataclass
class Observation:
    screenshot: Screenshot
    analysis: ScreenAnalysis
    states: set[ScreenState]


@dataclass
class Action:
    """A semantic action. `target` names WHAT to act on; the location is
    resolved from the current screen at execution time."""
    kind: str                                  # click | type | scroll | key | wait
    purpose: str                               # select_answer | submit | next | ...
    target_kind: Optional[ElementKind] = None
    target_label: str = ""
    target_letter: str = ""
    nav_number: Optional[int] = None
    text: str = ""
    key: str = ""
    scroll_clicks: int = 0
    point: Optional[tuple[int, int]] = None   # scroll/key only; computed from the current screen
    description: str = ""


@dataclass
class ActionResult:
    action: Action
    success: bool
    attempts: int
    verified: bool
    observation: Optional[Observation] = None
    message: str = ""
    failure_category: Optional[FailureCategory] = None
