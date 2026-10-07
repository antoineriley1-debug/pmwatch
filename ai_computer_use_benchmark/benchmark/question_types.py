"""Question-type handlers (spec section 13). The initial version supports
single-answer multiple choice, true/false, yes/no, multiple-select and short
text. New types (numerical, matching, dropdown, ordering, drag-and-drop,
multi-part...) are added by registering another handler."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .core import Action, ElementKind, FailureCategory, Observation, QuestionType, normalize_text
from .verification import Expectation


@dataclass
class Answer:
    labels: list[str] = field(default_factory=list)
    letters: list[str] = field(default_factory=list)
    text: str = ""

    def display(self) -> str:
        if self.text:
            return repr(self.text)
        parts = []
        for i, label in enumerate(self.labels):
            letter = self.letters[i] if i < len(self.letters) else ""
            parts.append(f"{letter}. {label}" if letter else label)
        return " | ".join(parts) or "(none)"

    def short(self) -> str:
        if self.text:
            return self.text[:60]
        return ", ".join(self.letters) if self.letters and all(self.letters) else ", ".join(self.labels)


@dataclass
class ApplyResult:
    success: bool
    selected_labels: list[str]
    selected_text: str
    max_attempts: int
    observation: Observation
    failure_category: Optional[FailureCategory] = None
    message: str = ""


class AnswerHandler(ABC):
    types: tuple[QuestionType, ...] = ()

    @abstractmethod
    def apply(self, answer: Answer, obs: Observation, executor, question_seq) -> ApplyResult: ...


def _pairs(answer: Answer):
    for i, label in enumerate(answer.labels):
        yield label, (answer.letters[i] if i < len(answer.letters) else "")


class SingleChoiceHandler(AnswerHandler):
    types = (QuestionType.SINGLE_CHOICE, QuestionType.TRUE_FALSE, QuestionType.YES_NO)

    def apply(self, answer, obs, executor, question_seq):
        if not answer.labels:
            return ApplyResult(False, [], "", 0, obs, FailureCategory.REASONING, "no option chosen")
        label, letter = next(_pairs(answer))
        el = obs.analysis.find_option(label, letter)
        if el is not None and el.selected:
            return ApplyResult(True, [el.label], "", 0, obs, message="already selected")
        action = Action("click", "select_answer", ElementKind.ANSWER_OPTION, label, letter,
                        description=f"select answer '{letter + '. ' if letter else ''}{label}'")
        exp = Expectation("option_selected", f"answer '{label}' is visibly selected", label=label,
                          letter=letter, region=el.bbox if el else None)
        result = executor.execute(action, exp, obs, question_seq)
        return ApplyResult(result.success, [label] if result.success else [], "", result.attempts,
                           result.observation, result.failure_category, result.message)


class MultiSelectHandler(AnswerHandler):
    types = (QuestionType.MULTI_SELECT,)

    def apply(self, answer, obs, executor, question_seq):
        wanted = list(_pairs(answer))
        current = obs
        selected, max_attempts = [], 0
        # Deselect anything selected that is not part of the answer.
        wanted_norm = {normalize_text(l) for l, _ in wanted}
        for el in list(current.analysis.selected_options()):
            if normalize_text(el.label) in wanted_norm:
                continue
            match = any(current.analysis.find_option(l, lt) is el for l, lt in wanted)
            if match:
                continue
            action = Action("click", "deselect_answer", ElementKind.ANSWER_OPTION, el.label, el.option_letter,
                            description=f"deselect '{el.label}'")
            exp = Expectation("option_deselected", f"'{el.label}' is no longer selected", label=el.label,
                              letter=el.option_letter, region=el.bbox)
            res = executor.execute(action, exp, current, question_seq)
            max_attempts = max(max_attempts, res.attempts)
            current = res.observation or current
            if not res.success:
                return ApplyResult(False, selected, "", max_attempts, current, res.failure_category, res.message)
        for label, letter in wanted:
            el = current.analysis.find_option(label, letter)
            if el is not None and el.selected:
                selected.append(label)
                continue
            action = Action("click", "select_answer", ElementKind.ANSWER_OPTION, label, letter,
                            description=f"select '{label}'")
            exp = Expectation("option_selected", f"'{label}' is visibly selected", label=label, letter=letter,
                              region=el.bbox if el else None)
            res = executor.execute(action, exp, current, question_seq)
            max_attempts = max(max_attempts, res.attempts)
            current = res.observation or current
            if not res.success:
                return ApplyResult(False, selected, "", max_attempts, current, res.failure_category, res.message)
            selected.append(label)
        return ApplyResult(True, selected, "", max_attempts, current)


class ShortTextHandler(AnswerHandler):
    types = (QuestionType.SHORT_TEXT,)

    def apply(self, answer, obs, executor, question_seq):
        if not answer.text:
            return ApplyResult(False, [], "", 0, obs, FailureCategory.REASONING, "no text answer produced")
        field_el = next(iter(obs.analysis.of_kind(ElementKind.TEXT_FIELD, enabled_only=True)), None)
        action = Action("type", "enter_text", ElementKind.TEXT_FIELD, field_el.label if field_el else "",
                        text=answer.text, description="type the short-text answer")
        exp = Expectation("text_entered", f"the field shows '{answer.text[:60]}'", text=answer.text,
                          region=field_el.bbox if field_el else None)
        res = executor.execute(action, exp, obs, question_seq)
        return ApplyResult(res.success, [], answer.text if res.success else "", res.attempts,
                           res.observation, res.failure_category, res.message)


HANDLERS: dict[QuestionType, AnswerHandler] = {}
for _handler in (SingleChoiceHandler(), MultiSelectHandler(), ShortTextHandler()):
    for _t in _handler.types:
        HANDLERS[_t] = _handler


_INFER_FROM_CONTROLS = {QuestionType.OTHER, QuestionType.NONE, QuestionType.IMAGE,
                        QuestionType.CHART, QuestionType.TABLE}


def handler_for(qtype: QuestionType, obs: Observation) -> Optional[AnswerHandler]:
    if qtype in HANDLERS:
        return HANDLERS[qtype]
    if qtype not in _INFER_FROM_CONTROLS:
        return None   # e.g. matching, ordering, drag-and-drop: not supported in this version
    # "other", or content-based types (image/chart/table) answered through
    # ordinary controls: infer the interaction from what is on screen.
    if obs.analysis.of_kind(ElementKind.CHECKBOX):
        return HANDLERS[QuestionType.MULTI_SELECT]
    if obs.analysis.options():
        return HANDLERS[QuestionType.SINGLE_CHOICE]
    if obs.analysis.of_kind(ElementKind.TEXT_FIELD):
        return HANDLERS[QuestionType.SHORT_TEXT]
    return None
