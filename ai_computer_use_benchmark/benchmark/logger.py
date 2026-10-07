"""Benchmark Logger (spec section 15): per-run event log, database rows and
screenshots around important events."""
from __future__ import annotations

import json
import os
import platform
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from .config import RunConfig
from .core import FailureCategory, Observation
from .database import Database
from .state_engine import describe


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]


@dataclass
class RunStats:
    total_questions_reported: Optional[int] = None
    attempted: int = 0
    answered: int = 0
    skipped: int = 0
    timed_out: int = 0
    failed: int = 0
    navigation_attempts: int = 0
    navigation_successes: int = 0
    navigation_failures: int = 0
    interactions: int = 0
    first_attempt_successes: int = 0
    failed_interactions: int = 0
    recovery_attempts: int = 0
    recovery_episodes: int = 0
    successful_recoveries: int = 0
    recoveries_failed: int = 0
    unknown_states: int = 0
    unknown_states_resolved: int = 0
    perception_cycles: int = 0
    perception_failures: int = 0
    multiple_attempt_questions: int = 0
    interventions: int = 0
    confidences: list = field(default_factory=list)
    reported_results: str = ""


@dataclass
class QuestionRecord:
    seq: int
    key: str
    number: Optional[int]
    question_type: str = ""
    question_text: str = ""
    instructions: str = ""
    options: list = field(default_factory=list)
    intended_labels: list = field(default_factory=list)
    intended_letters: list = field(default_factory=list)
    intended_text: str = ""
    selected_labels: list = field(default_factory=list)
    selected_text: str = ""
    confidence: Optional[int] = None
    reasoning: str = ""
    outcome: str = "in_progress"      # answered | skipped | timeout | failed
    started_ts: float = 0.0
    duration_s: float = 0.0
    max_attempts: int = 0
    navigation_retries: int = 0
    failure_categories: list = field(default_factory=list)
    milestones: dict = field(default_factory=dict)
    reviews: list = field(default_factory=list)

    def mark(self, name: str, value=None) -> None:
        self.milestones[name] = value if value is not None else time.time()


# Order and wording of the per-question block in event_log.txt
_MILESTONE_LINES = [
    ("question_detected", "Question detected"),
    ("question_understood", "Question understood"),
    ("initial_answer", "Initial answer generated"),
    ("confidence", "Confidence"),
    ("answer_selected", "Answer selected"),
    ("selection_verified", "Selection verified"),
    ("min_dwell", "Minimum dwell"),
    ("submit_detected", "Submit detected"),
    ("submit_clicked", "Submit clicked"),
    ("submission_verified", "Submission verified"),
    ("next_detected", "Next detected"),
    ("next_clicked", "Next clicked"),
    ("new_question_verified", "New question verified"),
    ("navigation_retries", "Navigation retries"),
]


class BenchmarkLogger:
    def __init__(self, config: RunConfig, run_id: str):
        self.config = config
        self.run_id = run_id
        self.run_dir = os.path.join(config.output_dir, run_id)
        self.shot_dir = os.path.join(self.run_dir, "screenshots")
        os.makedirs(self.shot_dir, exist_ok=True)
        self.db = Database(os.path.join(self.run_dir, "benchmark.db"))
        self._text = open(os.path.join(self.run_dir, "event_log.txt"), "a", encoding="utf-8")
        self._jsonl = open(os.path.join(self.run_dir, "events.jsonl"), "a", encoding="utf-8")
        self._lock = threading.Lock()
        self._shot_counter = 0
        self.listeners = []   # callables(event_type, data) for the dashboard

    # ------------------------------------------------------------------
    def start_run(self, config_hash: str, prompt_hash: str, model_identity: dict) -> None:
        env = {"platform": platform.platform(), "python": platform.python_version(),
               "machine": platform.machine()}
        self.db.insert("runs", {
            "run_id": self.run_id, "run_name": self.config.run_name, "started_at": now_iso(),
            "status": "running", "config_json": self.config.to_dict(), "config_hash": config_hash,
            "prompt_hash": prompt_hash, "model_identity_json": model_identity, "environment_json": env,
        })
        self._write_text(f"RUN: {self.config.run_name}  (id {self.run_id})\n"
                         f"Started:        {now_iso()}\n"
                         f"Model:          {json.dumps(model_identity, default=str)}\n"
                         f"Config hash:    {config_hash}\n"
                         f"Prompt hash:    {prompt_hash}\n"
                         f"Benchmark mode: {'LOCKED' if self.config.benchmark_mode else 'off'}\n\n")
        with open(os.path.join(self.run_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"config": self.config.to_dict(), "config_hash": config_hash,
                       "prompt_hash": prompt_hash, "model_identity": model_identity,
                       "environment": env}, f, indent=2, default=str)

    def end_run(self, status: str, model_identity: dict) -> None:
        self.db.finish_run(self.run_id, now_iso(), status, model_identity)
        self._write_text(f"\nRUN ENDED: {now_iso()}  status={status}\n")

    # ------------------------------------------------------------------
    def event(self, event_type: str, question_seq: Optional[int] = None,
              category: Optional[FailureCategory] = None, important: bool = False, **data) -> None:
        record = {"ts": now_iso(), "event": event_type, "question_seq": question_seq,
                  "category": category.value if category else None, **data}
        self.db.insert("events", {
            "run_id": self.run_id, "ts": record["ts"], "event_type": event_type,
            "question_seq": question_seq, "category": record["category"], "data_json": data,
        })
        with self._lock:
            self._jsonl.write(json.dumps(record, default=str) + "\n")
            self._jsonl.flush()
        if self.config.detailed_event_logging or important or category:
            detail = ", ".join(f"{k}={v}" for k, v in data.items() if v not in (None, "", [], {}))
            cat = f" [{category.value}]" if category else ""
            self._write_text(f"  {record['ts'][11:]}  {event_type}{cat}  {detail}\n")
        for listener in list(self.listeners):
            try:
                listener(event_type, record)
            except Exception:
                pass

    def interaction(self, question_seq, purpose, target, attempts, success, recovery_used, points,
                    notes="") -> None:
        self.db.insert("interactions", {
            "run_id": self.run_id, "ts": now_iso(), "question_seq": question_seq, "purpose": purpose,
            "target": target, "attempts": attempts, "success": int(success),
            "first_attempt_success": int(success and attempts == 1 and not recovery_used),
            "recovery_used": int(recovery_used), "points_json": points, "notes": notes,
        })

    def screen(self, obs: Observation, label: str, question_seq: Optional[int], keep_image: bool) -> str:
        path = ""
        if keep_image and self.config.screenshot_logging:
            self._shot_counter += 1
            path = os.path.join(self.shot_dir, f"{self._shot_counter:05d}_{label}.png")
            obs.screenshot.image.save(path, optimize=True)
            obs.screenshot.path = path
        self.db.insert("screens", {
            "run_id": self.run_id, "ts": now_iso(), "label": label, "question_seq": question_seq,
            "states": describe(obs.states), "parse_ok": int(obs.analysis.parse_ok),
            "screenshot_path": path, "analysis_json": obs.analysis.raw,
        })
        return path

    def save_screenshot(self, obs: Observation, label: str, question_seq: Optional[int]) -> str:
        """Preserve a screenshot around an important event (no new perception row)."""
        if not self.config.screenshot_logging:
            return ""
        if obs.screenshot.path:
            return obs.screenshot.path
        self._shot_counter += 1
        path = os.path.join(self.shot_dir, f"{self._shot_counter:05d}_{label}.png")
        obs.screenshot.image.save(path, optimize=True)
        obs.screenshot.path = path
        self.event("screenshot_saved", question_seq, label=label, path=path)
        return path

    def model_calls(self, calls) -> None:
        for c in calls:
            self.db.insert("model_calls", {
                "run_id": self.run_id, "ts": now_iso(), "purpose": c.purpose,
                "model_requested": c.model_requested, "model_served": c.model_served,
                "latency_s": c.latency_s, "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens, "stop_reason": c.stop_reason, "error": c.error,
            })

    def question(self, q: QuestionRecord) -> None:
        row = asdict(q)
        self.db.insert("questions", {
            "run_id": self.run_id, "seq": q.seq, "question_key": q.key, "question_number": q.number,
            "question_type": q.question_type, "question_text": q.question_text,
            "options_json": q.options,
            "intended_answer_json": {"labels": q.intended_labels, "letters": q.intended_letters,
                                     "text": q.intended_text},
            "selected_answer_json": {"labels": q.selected_labels, "text": q.selected_text},
            "confidence": q.confidence, "reasoning": q.reasoning, "outcome": q.outcome,
            "duration_s": q.duration_s, "max_attempts": q.max_attempts,
            "multiple_attempts": int(q.max_attempts > 1), "navigation_retries": q.navigation_retries,
            "failure_categories_json": q.failure_categories, "milestones_json": row["milestones"],
            "reviews_json": q.reviews,
        })
        self._write_text(self._question_block(q))

    def _question_block(self, q: QuestionRecord) -> str:
        label = f"Q{q.number}" if q.number is not None else f"Q(seq {q.seq})"
        lines = [f"\nRUN: {self.config.run_name}", label]
        for key, title in _MILESTONE_LINES:
            if key not in q.milestones:
                continue
            value = q.milestones[key]
            if key in ("question_detected", "question_understood", "initial_answer", "answer_selected_at",
                       "submit_clicked", "next_clicked") and isinstance(value, float):
                value = clock(value)
            elif key == "confidence" and value is not None:
                value = f"{value}%"
            elif key == "min_dwell":
                value = f"{value} sec"
            elif isinstance(value, bool):
                value = "YES" if value else "NO"
            lines.append(f"{title + ':':<25}{value}")
        lines.append(f"{'Outcome:':<25}{q.outcome.upper()}")
        lines.append(f"{'Question time:':<25}{q.duration_s:.1f} sec")
        if q.failure_categories:
            lines.append(f"{'Failure categories:':<25}{', '.join(q.failure_categories)}")
        return "\n".join(lines) + "\n"

    def _write_text(self, text: str) -> None:
        with self._lock:
            self._text.write(text)
            self._text.flush()

    def close(self) -> None:
        with self._lock:
            self._text.close()
            self._jsonl.close()
        self.db.close()
