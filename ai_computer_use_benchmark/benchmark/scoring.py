"""Grading and case-study scoring (spec sections 16 and 17).

Every score is derived from raw measurements that stay in the report so the
methodology can be examined independently. The answer key is used only
here, after the run; it is never shown to the AI."""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter
from typing import Optional

from .core import FailureCategory, normalize_text

NAV_PURPOSES = {"submit", "save", "next", "number_nav", "finish", "confirm"}

# Optional composite weights (spec: "Then optionally calculate").
COMPOSITE_WEIGHTS = {
    "question_accuracy": 0.40,
    "visual_perception": 0.15,
    "navigation_reliability": 0.15,
    "interaction_reliability": 0.10,
    "recovery_ability": 0.10,
    "completion_rate": 0.10,
}

_CATEGORY_ALIASES = {c.name.lower(): c.value for c in FailureCategory}
_CATEGORY_ALIASES.update({c.value.lower(): c.value for c in FailureCategory})


# ---------------------------------------------------------------- answer key
def load_answer_key(path: str) -> dict[str, dict]:
    """CSV columns: question, correct_answer[, failure_category][, notes].
    `question` is the question number shown on screen (or the run sequence
    number if the test shows none). Multiple correct options: separate with ';'."""
    key = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            q = (row.get("question") or "").strip()
            if not q:
                continue
            category = (row.get("failure_category") or "").strip().lower()
            key[q] = {
                "correct_answer": (row.get("correct_answer") or "").strip(),
                "failure_category": _CATEGORY_ALIASES.get(category, ""),
                "notes": (row.get("notes") or "").strip(),
            }
    return key


def _answer_parts(text: str) -> set[str]:
    return {normalize_text(p) for p in re.split(r"[;|]", text) if normalize_text(p)}


def is_correct(question: dict, correct_answer: str) -> bool:
    selected = json.loads(question.get("selected_answer_json") or "{}")
    intended = json.loads(question.get("intended_answer_json") or "{}")
    expected = _answer_parts(correct_answer)
    if not expected:
        return False
    if selected.get("text"):
        given = normalize_text(selected["text"])
        if given in expected:
            return True
        try:
            return any(abs(float(given) - float(e)) < 1e-9 for e in expected)
        except ValueError:
            return False
    labels = selected.get("labels") or []
    if not labels:
        return False
    # Letters are matched only when the key is written as letters.
    if all(len(e) == 1 and e.isalpha() for e in expected):
        letter_by_label = {normalize_text(l): normalize_text(lt) for l, lt in
                           zip(intended.get("labels", []), intended.get("letters", []))}
        letters = {letter_by_label.get(normalize_text(l), "") for l in labels}
        return letters == expected
    return {normalize_text(l) for l in labels} == expected


def grade(questions: list[dict], answer_key: Optional[dict]) -> list[dict]:
    """Attach correct/incorrect/skipped and a failure category to each question."""
    graded = []
    for q in questions:
        item = dict(q)
        k = None
        if answer_key:
            k = answer_key.get(str(q.get("question_number"))) if q.get("question_number") is not None else None
            k = k or answer_key.get(str(q.get("seq")))
        outcome = q.get("outcome")
        if outcome in ("skipped",):
            item["grade"] = "skipped"
        elif k is None:
            item["grade"] = "ungraded"
        elif outcome in ("answered",) and is_correct(q, k["correct_answer"]):
            item["grade"] = "correct"
        else:
            item["grade"] = "incorrect"
        item["correct_answer"] = k["correct_answer"] if k else ""
        if item["grade"] == "incorrect":
            item["failure_category"] = _wrong_answer_category(item, k)
        elif item["grade"] == "skipped":
            recorded = json.loads(q.get("failure_categories_json") or "[]")
            item["failure_category"] = (k or {}).get("failure_category") or (recorded[0] if recorded else "")
        else:
            item["failure_category"] = ""
        graded.append(item)
    return graded


def _wrong_answer_category(q: dict, k: Optional[dict]) -> str:
    if k and k.get("failure_category"):
        return k["failure_category"]          # reviewer annotation wins
    recorded = json.loads(q.get("failure_categories_json") or "[]")
    selected = json.loads(q.get("selected_answer_json") or "{}")
    intended = json.loads(q.get("intended_answer_json") or "{}")
    if (intended.get("labels") or intended.get("text")) and not (selected.get("labels") or selected.get("text")):
        return FailureCategory.INTERACTION.value  # knew what to answer, failed to enter it
    if {normalize_text(x) for x in selected.get("labels") or []} != \
            {normalize_text(x) for x in intended.get("labels") or []}:
        return FailureCategory.INTERACTION.value
    if recorded:
        return recorded[0]
    # The AI answered as intended and was wrong: reasoning vs knowledge vs
    # perception needs a reviewer's annotation in the answer key.
    return FailureCategory.UNKNOWN.value


# ---------------------------------------------------------------- measurements
def measurements(rows: dict, graded: list[dict]) -> dict:
    questions, interactions, events, screens = rows["questions"], rows["interactions"], rows["events"], rows["screens"]
    run = rows["run"]

    def events_of(*types):
        return [e for e in events if e["event_type"] in types]

    durations = [q["duration_s"] for q in questions if q.get("duration_s") is not None]
    confidences = [q["confidence"] for q in questions if q.get("confidence") is not None]
    grades = Counter(q["grade"] for q in graded)
    nav = [i for i in interactions if i["purpose"] in NAV_PURPOSES]
    not_advanced = len(events_of("question_not_advanced"))
    recovery_used = [i for i in interactions if i.get("recovery_used")]
    unknown = events_of("UNKNOWN_STATE")
    unknown_resolved = [e for e in events_of("unknown_state_outcome")
                        if json.loads(e["data_json"] or "{}").get("verified")]
    interventions = [e for e in events if json.loads(e["data_json"] or "{}").get("intervention")]
    perception_failed = len(events_of("perception_failed"))
    total_reported = max([json.loads(s["analysis_json"] or "{}").get("total_questions") or 0 for s in screens] or [0])
    results_text = ""
    for e in events_of("TEST_COMPLETE"):
        results_text = json.loads(e["data_json"] or "{}").get("results", "")

    total_questions = total_reported or len(questions)
    answered = sum(1 for q in questions if q["outcome"] == "answered")
    skipped = sum(1 for q in questions if q["outcome"] == "skipped")

    m = {
        "run_name": run.get("run_name"),
        "run_status": run.get("status"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "performance": {
            "total_questions": total_questions,
            "questions_attempted": len(questions),
            "answered": answered,
            "correct": grades.get("correct", 0),
            "incorrect": grades.get("incorrect", 0),
            "skipped": skipped,
            "ungraded": grades.get("ungraded", 0),
            "accuracy_pct": _pct(grades.get("correct", 0),
                                 grades.get("correct", 0) + grades.get("incorrect", 0) + grades.get("skipped", 0)),
            "completion_pct": _pct(answered, total_questions),
            "average_confidence": round(statistics.mean(confidences), 1) if confidences else None,
            "results_screen_text": results_text,
        },
        "speed": {
            "total_completion_time_s": _run_seconds(run),
            "average_time_per_question_s": round(statistics.mean(durations), 1) if durations else None,
            "fastest_question_s": round(min(durations), 1) if durations else None,
            "slowest_question_s": round(max(durations), 1) if durations else None,
            "median_question_time_s": round(statistics.median(durations), 1) if durations else None,
        },
        "computer_use": {
            "interactions": len(interactions),
            "successful_first_attempt_interactions": sum(i["first_attempt_success"] for i in interactions),
            "failed_interactions": sum(1 for i in interactions if not i["success"]),
            "recovery_attempts": len(events_of("recovery_attempt")),
            "recovery_episodes": len(recovery_used),
            "successful_recoveries": sum(1 for i in recovery_used if i["success"]),
            "unknown_states": len(unknown),
            "unknown_states_resolved": len(unknown_resolved),
            "navigation_attempts": len(nav) + not_advanced,
            "navigation_successes": sum(1 for i in nav if i["success"]),
            "navigation_failures": sum(1 for i in nav if not i["success"]) + not_advanced,
            "questions_requiring_multiple_attempts": sum(1 for q in questions if q.get("multiple_attempts")),
            "perception_cycles": len(screens),
            "perception_failures": perception_failed,
            "human_interventions": len(interventions),
        },
        "failure_analysis": failure_breakdown(graded, events),
    }
    return m


def failure_breakdown(graded: list[dict], events: list[dict]) -> dict:
    by_question = Counter(q["failure_category"] for q in graded if q.get("failure_category"))
    by_event = Counter(e["category"] for e in events if e.get("category"))
    return {c.value: {"questions": by_question.get(c.value, 0), "events": by_event.get(c.value, 0)}
            for c in FailureCategory}


def scores(m: dict, graded: list[dict]) -> dict:
    perf, cu = m["performance"], m["computer_use"]
    graded_total = perf["correct"] + perf["incorrect"] + perf["skipped"]
    perception_errors = (cu["perception_failures"]
                         + (cu["unknown_states"] - cu["unknown_states_resolved"])
                         + m["failure_analysis"][FailureCategory.PERCEPTION.value]["questions"])
    s = {
        "question_accuracy": _pct(perf["correct"], graded_total) if perf["ungraded"] < len(graded) else None,
        "visual_perception": _clamp(100 * (1 - perception_errors / cu["perception_cycles"]))
        if cu["perception_cycles"] else None,
        "navigation_reliability": _pct(cu["navigation_successes"], cu["navigation_attempts"]),
        "interaction_reliability": _pct(cu["successful_first_attempt_interactions"], cu["interactions"]),
        "recovery_ability": _pct(cu["successful_recoveries"], cu["recovery_episodes"]),
        "completion_rate": perf["completion_pct"],
    }
    available = {k: v for k, v in s.items() if v is not None}
    if available:
        weight = sum(COMPOSITE_WEIGHTS[k] for k in available)
        s["ai_computer_intelligence_benchmark_score"] = round(
            sum(v * COMPOSITE_WEIGHTS[k] for k, v in available.items()) / weight, 1)
        s["composite_components_used"] = sorted(available)
    else:
        s["ai_computer_intelligence_benchmark_score"] = None
        s["composite_components_used"] = []
    return s


METHODOLOGY = {
    "question_accuracy": "correct / (correct + incorrect + skipped) over questions in the answer key. "
                         "Null without an answer key.",
    "visual_perception": "100 x (1 - (failed perception calls + unresolved unknown screens + questions "
                         "annotated PERCEPTION ERROR) / perception cycles).",
    "navigation_reliability": "successful navigation actions / navigation attempts (Submit, Save, Next, "
                              "Continue, numbered navigation, Finish, Confirm). A question that failed to "
                              "advance counts as a failed attempt.",
    "interaction_reliability": "interactions verified on the first attempt without recovery / all interactions.",
    "recovery_ability": "interactions that succeeded after entering recovery / interactions that entered "
                        "recovery. Null when recovery was never needed.",
    "completion_rate": "questions answered / total questions (total from the screen's 'of N' if shown, else "
                       "questions encountered).",
    "ai_computer_intelligence_benchmark_score": "weighted mean of available component scores; weights: "
                                                + json.dumps(COMPOSITE_WEIGHTS),
    "wrong_answer_categories": "INTERACTION when the selected answer differs from the AI's intended answer; "
                               "otherwise the category recorded during the run; otherwise UNKNOWN until a "
                               "reviewer annotates REASONING / KNOWLEDGE / PERCEPTION in the answer key's "
                               "failure_category column.",
}


def _pct(num, den) -> Optional[float]:
    return round(100.0 * num / den, 1) if den else None


def _clamp(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


def _run_seconds(run: dict) -> Optional[float]:
    from datetime import datetime
    try:
        start = datetime.fromisoformat(run["started_at"])
        end = datetime.fromisoformat(run["ended_at"])
        return round((end - start).total_seconds(), 1)
    except (KeyError, TypeError, ValueError):
        return None
