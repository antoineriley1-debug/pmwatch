"""JSON schemas for every structured model response. Shared by all model
adapters so different AI models answer under identical conditions."""
from ..core import ElementKind, QuestionType

_NULLABLE_INT = {"type": ["integer", "null"]}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


ELEMENT_SCHEMA = _obj({
    "id": {"type": "string"},
    "kind": {"type": "string", "enum": [k.value for k in ElementKind]},
    "label": {"type": "string"},
    "bbox": {"type": "array", "items": {"type": "integer"},
             "description": "[x0, y0, x1, y1] in pixels of the provided image"},
    "click_point": {"type": "array", "items": {"type": "integer"},
                    "description": "[x, y] where a person would click to operate this element"},
    "selected": {"type": "boolean"},
    "disabled": {"type": "boolean"},
    "nav_number": _NULLABLE_INT,
    "option_letter": {"type": "string"},
    "value": {"type": "string"},
})

SCREEN_SCHEMA = _obj({
    "screen_purpose": {"type": "string"},
    "is_question_screen": {"type": "boolean"},
    "question_number": _NULLABLE_INT,
    "total_questions": _NULLABLE_INT,
    "question_text": {"type": "string"},
    "instructions": {"type": "string"},
    "question_type": {"type": "string", "enum": [q.value for q in QuestionType]},
    "has_image_or_diagram": {"type": "boolean"},
    "has_table": {"type": "boolean"},
    "content_continues_below": {"type": "boolean"},
    "content_continues_above": {"type": "boolean"},
    "is_loading": {"type": "boolean"},
    "has_error_message": {"type": "boolean"},
    "error_text": {"type": "string"},
    "has_confirmation_dialog": {"type": "boolean"},
    "dialog_text": {"type": "string"},
    "has_popup": {"type": "boolean"},
    "is_results_screen": {"type": "boolean"},
    "results_summary": {"type": "string"},
    "is_test_complete": {"type": "boolean"},
    "answer_submitted_indicator": {"type": "boolean"},
    "is_os_security_dialog": {"type": "boolean"},
    "elements": {"type": "array", "items": ELEMENT_SCHEMA},
})

ANSWER_SCHEMA = _obj({
    "question_understanding": {"type": "string"},
    "answer_labels": {"type": "array", "items": {"type": "string"},
                      "description": "Exact text of each option to select (empty for short text)"},
    "answer_letters": {"type": "array", "items": {"type": "string"}},
    "answer_text": {"type": "string", "description": "Text to type for short-text questions"},
    "reasoning_summary": {"type": "string"},
    "confidence": {"type": "integer", "description": "0-100"},
})

REVIEW_SCHEMA = _obj({
    "confirm_answer": {"type": "boolean"},
    "overlooked_instructions": {"type": "string"},
    "revised_answer_labels": {"type": "array", "items": {"type": "string"}},
    "revised_answer_letters": {"type": "array", "items": {"type": "string"}},
    "revised_answer_text": {"type": "string"},
    "selection_visible_on_screen": {"type": "boolean"},
    "notes": {"type": "string"},
    "confidence": {"type": "integer"},
})

UNKNOWN_SCHEMA = _obj({
    "inferred_purpose": {"type": "string"},
    "candidate_actions": {"type": "array", "items": _obj({
        "action": {"type": "string", "enum": ["click", "press_key", "wait", "scroll_down", "scroll_up", "none"]},
        "element_id": {"type": "string"},
        "key": {"type": "string", "enum": ["", "enter", "escape", "tab", "space", "pagedown", "pageup"]},
        "description": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "confidence": {"type": "integer"},
    })},
    "chosen_index": {"type": "integer", "description": "-1 when no action is safe"},
    "confidence": {"type": "integer"},
})

VERIFY_SCHEMA = _obj({
    "action_succeeded": {"type": "boolean"},
    "observation": {"type": "string"},
    "confidence": {"type": "integer"},
})
