"""Screen perception: screenshot -> ScreenAnalysis with fresh screen coordinates."""
from __future__ import annotations

from ..core import ElementKind, QuestionType, ScreenAnalysis, Screenshot, UIElement
from ..reasoning.base import ModelImage, ReasoningModel
from .capture import encode_for_model
from .ocr import OcrEngine

_GROUNDED_KINDS = {
    ElementKind.BUTTON_SUBMIT, ElementKind.BUTTON_NEXT, ElementKind.BUTTON_PREVIOUS,
    ElementKind.BUTTON_CONTINUE, ElementKind.BUTTON_FINISH, ElementKind.BUTTON_SAVE,
    ElementKind.BUTTON_CONFIRM, ElementKind.BUTTON_CANCEL, ElementKind.BUTTON_CLOSE,
    ElementKind.QUESTION_NAV_NUMBER,
}


class Perceiver:
    def __init__(self, model: ReasoningModel, max_edge: int, effort: str, ocr: OcrEngine | None = None):
        self.model = model
        self.max_edge = max_edge
        self.effort = effort
        self.ocr = ocr or OcrEngine()

    def model_image(self, shot: Screenshot, caption: str = "") -> tuple[ModelImage, float]:
        png, scale = encode_for_model(shot.image, self.max_edge)
        w, h = shot.image.size
        return ModelImage(png=png, width=round(w / scale), height=round(h / scale), caption=caption), scale

    def analyze(self, shot: Screenshot) -> ScreenAnalysis:
        image, scale = self.model_image(shot)
        try:
            data = self.model.analyze_screen(image, self.effort)
        except Exception as exc:  # perception failure is data, not a crash
            return ScreenAnalysis(parse_ok=False, screen_purpose=f"perception failed: {exc}")
        return self._to_analysis(data, shot, scale)

    # ------------------------------------------------------------------
    def _to_analysis(self, data: dict, shot: Screenshot, scale: float) -> ScreenAnalysis:
        def to_screen_xy(x, y):
            return round(shot.left + x * scale), round(shot.top + y * scale)

        elements = []
        for raw in data.get("elements", []):
            bbox = raw.get("bbox") or []
            if len(bbox) != 4:
                continue
            x0, y0 = to_screen_xy(bbox[0], bbox[1])
            x1, y1 = to_screen_xy(bbox[2], bbox[3])
            cp = raw.get("click_point") or []
            click = to_screen_xy(cp[0], cp[1]) if len(cp) == 2 else ((x0 + x1) // 2, (y0 + y1) // 2)
            try:
                kind = ElementKind(raw.get("kind", "other"))
            except ValueError:
                kind = ElementKind.OTHER
            elements.append(UIElement(
                id=raw.get("id", ""), kind=kind, label=raw.get("label", ""),
                bbox=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), click_point=click,
                selected=bool(raw.get("selected")), disabled=bool(raw.get("disabled")),
                nav_number=raw.get("nav_number"), option_letter=raw.get("option_letter", ""),
                value=raw.get("value", ""),
            ))
        self._ground_with_ocr(elements, shot)

        try:
            qtype = QuestionType(data.get("question_type", "none"))
        except ValueError:
            qtype = QuestionType.OTHER

        return ScreenAnalysis(
            screen_purpose=data.get("screen_purpose", ""),
            is_question_screen=bool(data.get("is_question_screen")),
            question_number=data.get("question_number"),
            total_questions=data.get("total_questions"),
            question_text=data.get("question_text", ""),
            instructions=data.get("instructions", ""),
            question_type=qtype,
            has_image_or_diagram=bool(data.get("has_image_or_diagram")),
            has_table=bool(data.get("has_table")),
            content_continues_below=bool(data.get("content_continues_below")),
            content_continues_above=bool(data.get("content_continues_above")),
            is_loading=bool(data.get("is_loading")),
            has_error_message=bool(data.get("has_error_message")),
            error_text=data.get("error_text", ""),
            has_confirmation_dialog=bool(data.get("has_confirmation_dialog")),
            dialog_text=data.get("dialog_text", ""),
            has_popup=bool(data.get("has_popup")),
            is_results_screen=bool(data.get("is_results_screen")),
            results_summary=data.get("results_summary", ""),
            is_test_complete=bool(data.get("is_test_complete")),
            answer_submitted_indicator=bool(data.get("answer_submitted_indicator")),
            is_os_security_dialog=bool(data.get("is_os_security_dialog")),
            elements=elements,
            raw=data,
        )

    def _ground_with_ocr(self, elements: list[UIElement], shot: Screenshot) -> None:
        """Refine button/nav click points to the centre of their visible label text."""
        if not self.ocr.available:
            return
        for e in elements:
            if e.kind not in _GROUNDED_KINDS or not e.label:
                continue
            local = (e.bbox[0] - shot.left, e.bbox[1] - shot.top, e.bbox[2] - shot.left, e.bbox[3] - shot.top)
            found = self.ocr.locate_label(shot.image, e.label, local)
            if found:
                cx = (found[0] + found[2]) // 2 + shot.left
                cy = (found[1] + found[3]) // 2 + shot.top
                e.click_point = (cx, cy)
