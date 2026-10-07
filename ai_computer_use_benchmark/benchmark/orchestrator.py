"""Orchestrator: the question workflow (spec section 6), navigation (7),
timing (8), recovery (11), unknown states (12), scrolling (14) and the
locked Benchmark Mode (18)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from . import state_engine
from .config import RunConfig, format_seconds
from .controller.base import ComputerController
from .controller.safety import EmergencyStop, ResumedAfterSafetyPause, SafetyGuard, SafetyViolation
from .core import (Action, FailureCategory, Observation, QuestionType, ScreenState,
                   normalize_text, same_question)
from .executor import ActionExecutor
from .logger import BenchmarkLogger, QuestionRecord, RunStats
from .perception.capture import ScreenCapture
from .perception.vision import Perceiver
from .planner import NavigationFlow, content_scroll_point, plan_dialog, plan_navigation
from .question_types import Answer, handler_for
from .reasoning import prompts
from .reasoning.base import ModelRefusal, ReasoningModel
from .recovery import RecoveryManager
from .timer import QuestionTimer
from .verification import Expectation, Verifier

MAX_CONTEXT_SCROLLS = 8
MAX_NAV_STEPS = 8
MAX_CONTEXT_IMAGES = 4
SETTLE_SECONDS = 0.6
MAX_LOADING_WAITS = 10


class RunStopped(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class Orchestrator:
    def __init__(self, config: RunConfig, model: ReasoningModel, controller: ComputerController,
                 capture: Optional[ScreenCapture] = None):
        config.validate()
        self.config = config                      # frozen dataclass: cannot change mid-run
        self.model = model
        self.controller = controller
        self.capture = capture or ScreenCapture(config.monitor_index)
        self.run_id = f"{config.run_name}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.logger = BenchmarkLogger(config, self.run_id)
        self.stats = RunStats()
        self.perceiver = Perceiver(model, config.perception_max_edge, config.perception_effort)
        self.verifier = Verifier(self.perceiver, config.perception_effort)
        self.guard = SafetyGuard(controller, config.target_window_title,
                                 config.max_consecutive_actions, config.pause_on_focus_loss)
        self.guard.on_emergency_stop = self._on_emergency_stop
        self.recovery = RecoveryManager(self._observe_after_action, self.verifier, self.wait_for_settle)
        self.executor = ActionExecutor(controller, self._guard_check, self.verifier, self.recovery,
                                       self._observe_after_action, self.wait_for_settle, self.logger, self.stats,
                                       config.max_recovery_attempts, self.checkpoint)
        self.timer = QuestionTimer(config.min_question_seconds, config.max_question_seconds)

        self._pause = threading.Event()
        self._pause_reason = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._run_started = 0.0
        self._seq = 0
        self._pending: Optional[Observation] = None
        self._completed: list[str] = []
        self._revisits: dict[str, int] = {}
        self._unknown_streak = 0
        self._unresolved_cycles = 0
        self._calls_logged = 0
        self.current_question: Optional[QuestionRecord] = None
        self.questions: list[QuestionRecord] = []
        self.status = {"run_status": "IDLE", "state": "--", "message": "", "confidence": None,
                       "question_number": None, "run_dir": self.logger.run_dir, "report": ""}

    # ================================================================== control
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="benchmark-run", daemon=True)
        self._thread.start()

    def pause(self, reason: str = "operator") -> None:
        if self._pause.is_set():
            return
        self._pause_reason = reason
        self._pause.set()
        self.timer.pause()
        self.logger.event("PAUSED", self._qseq(), important=True, reason=reason)
        self._set(run_status="PAUSED", message=f"Paused: {reason}")

    def resume(self) -> None:
        if not self._pause.is_set():
            return
        # Every resume is a human action and is logged as an intervention.
        self.stats.interventions += 1
        self.logger.event("RESUMED", self._qseq(), important=True, after=self._pause_reason,
                          intervention=True)
        self._pause_reason = ""
        self.timer.resume()
        self.guard.reset_action_count()
        if self.config.target_window_title:
            self.controller.activate_window(self.config.target_window_title)
        self._pause.clear()
        self._set(run_status="RUNNING", message="")

    def stop(self) -> None:
        self.logger.event("STOP_REQUESTED", self._qseq(), important=True, intervention=True)
        self._stop.set()
        self._pause.clear()

    def emergency_stop(self) -> None:
        self.guard.emergency_stop()

    def _on_emergency_stop(self) -> None:
        self.stats.interventions += 1
        self.logger.event("EMERGENCY_STOP", self._qseq(), important=True, intervention=True)
        self._stop.set()
        self._pause.clear()
        self._set(run_status="EMERGENCY STOP", message="All automated input halted.")

    def checkpoint(self) -> None:
        """Called between steps: honours stop and blocks while paused."""
        while True:
            if self.guard.stop_event.is_set():
                raise RunStopped("emergency_stop")
            if self._stop.is_set():
                raise RunStopped("stopped")
            if not self._pause.is_set():
                return
            time.sleep(0.2)

    def _guard_check(self, point) -> None:
        """Safety check before every OS input. A violation other than the
        emergency stop pauses the run; once a human resumes, the caller must
        re-observe (ResumedAfterSafetyPause)."""
        try:
            self.guard.before_action(point)
        except EmergencyStop:
            raise
        except SafetyViolation as violation:
            self.logger.event(f"SAFETY_{violation.reason.upper()}", self._qseq(), important=True,
                              detail=str(violation))
            self.pause(f"Safety: {violation}")
            self.checkpoint()
            raise ResumedAfterSafetyPause() from violation

    def snapshot(self) -> dict:
        """Live values for the dashboard (spec section 9)."""
        with self._lock:
            status = dict(self.status)
        q = self.current_question
        status.update({
            "run_name": self.config.run_name,
            "question_number": q.number if q else status.get("question_number"),
            "total_questions": self.stats.total_questions_reported,
            "question_elapsed": format_seconds(self.timer.elapsed()) if self.timer.running else "--",
            "minimum_time": format_seconds(self.config.min_question_seconds),
            "answered": self.stats.answered,
            "skipped": self.stats.skipped,
            "navigation_errors": self.stats.navigation_failures,
            "recovery_attempts": self.stats.recovery_attempts,
            "overall_accuracy": "--",   # graded after the run against the answer key
            "total_run_time": format_seconds(time.monotonic() - self._run_started) if self._run_started else "--",
        })
        return status

    def _set(self, **values) -> None:
        with self._lock:
            self.status.update(values)

    def _qseq(self) -> Optional[int]:
        return self.current_question.seq if self.current_question else None

    # ================================================================== perception
    def observe(self, label: str, keep: bool = False) -> Observation:
        shot = self.capture.capture()
        analysis = self.perceiver.analyze(shot)
        states = state_engine.classify(analysis)
        obs = Observation(shot, analysis, states)
        self.stats.perception_cycles += 1
        if not analysis.parse_ok:
            self.stats.perception_failures += 1
            self.logger.event("perception_failed", self._qseq(), category=FailureCategory.PERCEPTION,
                              detail=analysis.screen_purpose)
            keep = True
        if analysis.total_questions:
            self.stats.total_questions_reported = analysis.total_questions
        self.logger.screen(obs, label, self._qseq(), keep_image=keep)
        self._set(state=state_engine.describe(states))
        return obs

    def wait_for_settle(self, obs: Observation) -> Observation:
        waits = 0
        while ScreenState.LOADING in obs.states and waits < MAX_LOADING_WAITS:
            self.checkpoint()
            time.sleep(self.config.loading_wait_seconds)
            obs = self.observe("loading")
            waits += 1
        return obs

    def _observe_after_action(self, label: str, keep: bool = False) -> Observation:
        time.sleep(SETTLE_SECONDS)
        return self.wait_for_settle(self.observe(label, keep))

    # ================================================================== main loop
    def _run(self) -> None:
        status = "complete"
        self._run_started = time.monotonic()
        self._set(run_status="RUNNING")
        try:
            identity = self.model.identity()
            self.logger.start_run(self.config.fingerprint(), prompts.prompt_fingerprint(), identity)
            self.logger.event("RUN_STARTED", important=True, benchmark_mode=self.config.benchmark_mode,
                              strict_mode=self.config.strict_mode, model=identity.get("model_id"))
            if not self.guard.start_hotkey():
                self.logger.event("hotkey_unavailable", important=True,
                                  detail="Emergency stop hotkey listener could not start; use the dashboard button.")
            if self.config.target_window_title:
                activated = self.controller.activate_window(self.config.target_window_title)
                self.logger.event("target_window_activated", important=True, ok=activated)
                time.sleep(1.0)
            self._loop()
        except RunStopped as stop:
            status = stop.status
        except EmergencyStop:
            status = "emergency_stop"
        except Exception as exc:
            status = "error"
            self.logger.event("RUN_ERROR", self._qseq(), important=True, error=repr(exc),
                              trace=traceback.format_exc())
            self._set(message=f"Error: {exc}")
        finally:
            self._finish_run(status)

    def _loop(self) -> None:
        while True:
            self.checkpoint()
            obs = self._pending or self.wait_for_settle(self.observe("cycle", keep=True))
            self._pending = None
            states = obs.states

            if ScreenState.TEST_COMPLETE in states:
                self.stats.reported_results = obs.analysis.results_summary
                self.logger.save_screenshot(obs, "results", None)
                self.logger.event("TEST_COMPLETE", important=True, results=obs.analysis.results_summary)
                return

            if obs.analysis.is_os_security_dialog:
                self.logger.event("os_security_dialog", important=True, detail=obs.analysis.screen_purpose)
                self.pause("OS security dialog detected - human intervention required")
                continue

            if ScreenState.QUESTION_READY in states:
                key = obs.analysis.question_key()
                done = next((k for k in self._completed if same_question(k, key)), None)
                if done is not None:
                    self._handle_revisit(obs, done)
                else:
                    self._process_question(obs)
                continue

            if ScreenState.CONFIRMATION_REQUIRED in states or obs.analysis.has_popup:
                step = plan_dialog(obs)
                if step:
                    result = self.executor.execute(step[0], step[1], obs, None)
                    if result.success:
                        self._pending = result.observation
                        continue
                    obs = result.observation or obs

            self._handle_unknown(obs)

    # ================================================================== question
    def _process_question(self, obs: Observation) -> None:
        self._seq += 1
        a = obs.analysis
        q = QuestionRecord(seq=self._seq, key=a.question_key(), number=a.question_number,
                           started_ts=time.time())
        self.current_question = q
        self.questions.append(q)
        self.timer.start()                         # starts when the question is recognized
        q.mark("question_detected")
        self.guard.reset_action_count()
        self._unknown_streak = 0
        self._unresolved_cycles = 0
        self.stats.attempted += 1
        self.logger.event("question_detected", q.seq, important=True, number=a.question_number,
                          key=q.key[:80])
        self._set(confidence=None, message="")

        try:
            current, context, images = self._build_context(obs, q)
            q.mark("question_understood")
            qtype = QuestionType(context["question_type"])
            q.question_type, q.question_text = qtype.value, context["question_text"]
            q.instructions, q.options = context["instructions"], context["option_list"]
            handler = handler_for(qtype, current)
            if handler is None:
                self.logger.event("unsupported_question_type", q.seq, category=FailureCategory.UNKNOWN,
                                  important=True, question_type=qtype.value)
                q.failure_categories.append(FailureCategory.UNKNOWN.value)
                self._skip_or_fail(q, "unsupported question type")
                self._wait_minimum(q)
                self._navigate(q)
                return

            answer, confidence, reasoning = self._reason(context, images, q)
            if answer is None:
                self._skip_or_fail(q, "reasoning failed")
                self._wait_minimum(q)
                self._navigate(q)
                return

            # Low confidence: spend dwell time re-checking before committing.
            if confidence < self.config.confidence_threshold:
                self.logger.event("low_confidence", q.seq, confidence=confidence,
                                  threshold=self.config.confidence_threshold)
                answer, confidence, current = self._review(q, context, answer, confidence, reasoning,
                                                            current, selected=False)
                if confidence < self.config.confidence_threshold and self.config.allow_skipping:
                    self._skip(q, f"confidence {confidence}% below threshold")
                    self._wait_minimum(q)
                    self._navigate(q)
                    return

            if self.timer.maximum_exceeded() and self.config.allow_skipping:
                self._skip(q, "maximum question time exceeded before selection")
                self._navigate(q)
                return

            current, ok = self._apply_answer(q, handler, answer, current)
            if not ok and q.outcome == "skipped":
                self._wait_minimum(q)
                self._navigate(q)
                return

            # Minimum dwell: recheck question, choices, instructions, reasoning, selection.
            answer, confidence, current = self._review(q, context, answer, confidence, reasoning,
                                                        current, selected=True, handler=handler)
            if q.outcome == "in_progress":
                q.outcome = "answered" if q.selected_labels or q.selected_text else "failed"
                if q.outcome == "answered":
                    self.stats.answered += 1
                    if self.timer.maximum_exceeded():
                        self.stats.timed_out += 1
                        self.logger.event("maximum_question_time_exceeded", q.seq)
                else:
                    self.stats.failed += 1
            self._navigate(q)
        finally:
            q.duration_s = self.timer.stop()
            if q.max_attempts > 1:
                self.stats.multiple_attempt_questions += 1
            self._completed.append(q.key)
            self.logger.question(q)
            self._flush_model_calls()
            self.current_question = None

    def _build_context(self, obs: Observation, q: QuestionRecord):
        """Read -> scroll -> read more -> complete question context (spec 14)."""
        pages = [obs]
        current = obs
        scrolled = 0
        if ScreenState.QUESTION_REQUIRES_SCROLL in obs.states and obs.analysis.content_continues_above:
            current = self._scroll_to_top(current, q)
            pages = [current]
        while (ScreenState.QUESTION_REQUIRES_SCROLL in current.states and current.analysis.content_continues_below
               and scrolled < MAX_CONTEXT_SCROLLS):
            moved, nxt = self._scroll(current, -5, q)
            if not moved:
                break
            if nxt.analysis.question_key() and not same_question(nxt.analysis.question_key(), q.key) \
                    and nxt.analysis.question_number not in (None, q.number):
                # Scrolling must never be mistaken for advancing.
                self.logger.event("scroll_changed_question", q.seq, category=FailureCategory.NAVIGATION,
                                  seen=nxt.analysis.question_number)
                break
            pages.append(nxt)
            current = nxt
            scrolled += 1
        if scrolled:
            self.logger.event("context_scrolled", q.seq, screens=len(pages))
            current = self._scroll_to_top(current, q)

        texts, instructions, options, seen = [], [], [], set()
        qtype = QuestionType.NONE
        for page in pages:
            a = page.analysis
            if a.question_text and normalize_text(a.question_text) not in {normalize_text(t) for t in texts}:
                texts.append(a.question_text)
            if a.instructions and a.instructions not in instructions:
                instructions.append(a.instructions)
            if qtype in (QuestionType.NONE, QuestionType.OTHER):
                qtype = a.question_type
            for e in a.options():
                norm = normalize_text(e.label)
                if norm and norm not in seen:
                    seen.add(norm)
                    options.append({"letter": e.option_letter, "label": e.label})
        if qtype in (QuestionType.NONE,) and options:
            qtype = QuestionType.OTHER
        # Prefer the longest reading of the question text, then any extra fragments.
        texts.sort(key=len, reverse=True)
        question_text = texts[0] if texts else ""
        for extra in texts[1:]:
            if normalize_text(extra) not in normalize_text(question_text):
                question_text += "\n" + extra
        option_lines = "\n".join(f"{o['letter'] + '. ' if o['letter'] else '- '}{o['label']}" for o in options) \
            or "(no answer options visible; answer is typed)"
        context = {"question_type": qtype.value, "instructions": " ".join(instructions) or "(none)",
                   "question_text": question_text or "(not extracted)", "options": option_lines,
                   "option_list": options}
        images = [self.perceiver.model_image(p.screenshot, f"(part {i + 1})")[0]
                  for i, p in enumerate(pages[:MAX_CONTEXT_IMAGES])]
        self.logger.save_screenshot(current, f"q{q.seq}_context", q.seq)
        return current, context, images

    def _scroll(self, current: Observation, clicks: int, q: QuestionRecord) -> tuple[bool, Observation]:
        self.checkpoint()
        point = content_scroll_point(current)
        try:
            self._guard_check(point)
        except ResumedAfterSafetyPause:
            return False, self.wait_for_settle(self.observe("after_safety_pause"))
        self.controller.scroll(point[0], point[1], clicks)
        nxt = self._observe_after_action("scroll")
        moved, _ = self.verifier.verify(current, nxt, Expectation(
            "scrolled", "content scrolled", previous_question_key=q.key))
        return moved, nxt

    def _scroll_to_top(self, current: Observation, q: QuestionRecord) -> Observation:
        for _ in range(MAX_CONTEXT_SCROLLS + 2):
            moved, nxt = self._scroll(current, 5, q)
            current = nxt
            if not moved or not nxt.analysis.content_continues_above:
                break
        return current

    def _reason(self, context: dict, images, q: QuestionRecord):
        self._set(message="Reasoning about the answer")
        try:
            data = self.model.answer_question(context, images, self.config.reasoning_effort)
        except ModelRefusal as exc:
            self.logger.event("model_refusal", q.seq, category=FailureCategory.REASONING, detail=str(exc))
            q.failure_categories.append(FailureCategory.REASONING.value)
            return None, 0, ""
        except Exception as exc:
            self.logger.event("reasoning_failed", q.seq, category=FailureCategory.REASONING, detail=repr(exc))
            q.failure_categories.append(FailureCategory.REASONING.value)
            return None, 0, ""
        answer = Answer(labels=data.get("answer_labels", []), letters=data.get("answer_letters", []),
                        text=data.get("answer_text", ""))
        confidence = max(0, min(100, int(data.get("confidence", 0))))
        q.mark("initial_answer")
        q.mark("confidence", confidence)
        q.intended_labels, q.intended_letters, q.intended_text = answer.labels, answer.letters, answer.text
        q.confidence = confidence
        q.reasoning = data.get("reasoning_summary", "")
        self.stats.confidences.append(confidence)
        self._set(confidence=confidence, message=f"Answer: {answer.short()}")
        self.logger.event("answer_generated", q.seq, answer=answer.display(), confidence=confidence,
                          understanding=data.get("question_understanding", "")[:300])
        return answer, confidence, q.reasoning

    def _apply_answer(self, q: QuestionRecord, handler, answer: Answer, current: Observation):
        while True:
            result = handler.apply(answer, current, self.executor, q.seq)
            q.max_attempts = max(q.max_attempts, result.max_attempts)
            current = result.observation or current
            if result.success:
                q.selected_labels, q.selected_text = result.selected_labels, result.selected_text
                q.mark("answer_selected", answer.short())
                q.mark("selection_verified", True)
                return current, True
            q.mark("selection_verified", False)
            category = result.failure_category or FailureCategory.INTERACTION
            q.failure_categories.append(category.value)
            decision = self._recovery_failed(q, f"answer selection failed: {result.message}")
            if decision == "retry":
                current = self.wait_for_settle(self.observe("after_intervention", keep=True))
                continue
            return current, False

    def _review(self, q, context, answer: Answer, confidence: int, reasoning: str, current: Observation,
                selected: bool, handler=None):
        """Use the minimum dwell time to recheck. Before selection (low
        confidence) a single pass runs; after selection, passes run until the
        minimum time is met."""
        passes, last = 0, 0.0
        while True:
            self.checkpoint()
            if self.timer.maximum_exceeded():
                break
            if selected and self.timer.minimum_met():
                break
            if not selected and passes >= 1:
                break
            due = passes == 0 or time.monotonic() - last >= self.config.review_interval_seconds
            if passes < self.config.max_review_passes and due:
                passes += 1
                last = time.monotonic()
                current = self.observe("review")
                image, _ = self.perceiver.model_image(current.screenshot)
                try:
                    rv = self.model.review_answer(context, {"display": answer.display(), "reasoning_summary": reasoning},
                                                  image, self.config.reasoning_effort)
                except Exception as exc:
                    self.logger.event("review_failed", q.seq, detail=repr(exc))
                    continue
                new_conf = max(0, min(100, int(rv.get("confidence", confidence))))
                q.reviews.append({"pass": passes, "confirm": rv.get("confirm_answer"), "confidence": new_conf,
                                  "overlooked": rv.get("overlooked_instructions", ""), "notes": rv.get("notes", "")})
                self.logger.event("review", q.seq, pass_no=passes, confirm=rv.get("confirm_answer"),
                                  confidence=new_conf, overlooked=rv.get("overlooked_instructions", "")[:200])
                revised = Answer(labels=rv.get("revised_answer_labels", []),
                                 letters=rv.get("revised_answer_letters", []),
                                 text=rv.get("revised_answer_text", ""))
                confidence = new_conf
                q.confidence = confidence
                self._set(confidence=confidence)
                if not rv.get("confirm_answer") and (revised.labels or revised.text):
                    self.logger.event("answer_revised", q.seq, before=answer.display(), after=revised.display())
                    answer = revised
                    q.intended_labels, q.intended_letters, q.intended_text = revised.labels, revised.letters, revised.text
                    if selected and handler:
                        current, _ = self._apply_answer(q, handler, answer, current)
                elif selected and handler and not rv.get("selection_visible_on_screen", True):
                    # The intended selection is not visible: re-verify and repair it.
                    self.logger.event("selection_not_visible", q.seq, category=FailureCategory.VERIFICATION)
                    current, _ = self._apply_answer(q, handler, answer, current)
                continue
            time.sleep(min(1.0, max(0.1, self.timer.minimum_remaining())))
        if self.stats.confidences:
            self.stats.confidences[-1] = confidence
        return answer, confidence, current

    def _wait_minimum(self, q: QuestionRecord) -> None:
        while not self.timer.minimum_met() and not self.timer.maximum_exceeded():
            self.checkpoint()
            time.sleep(min(1.0, max(0.1, self.timer.minimum_remaining())))

    def _skip(self, q: QuestionRecord, reason: str) -> None:
        q.outcome = "skipped"
        self.stats.skipped += 1
        self.logger.event("question_skipped", q.seq, important=True, reason=reason)

    def _skip_or_fail(self, q: QuestionRecord, reason: str) -> None:
        if self.config.allow_skipping:
            self._skip(q, reason)
        else:
            q.outcome = "failed"
            self.stats.failed += 1
            self.logger.event("question_failed", q.seq, important=True, reason=reason)

    # ================================================================== navigation
    def _navigate(self, q: QuestionRecord) -> None:
        q.mark("min_dwell", self.config.min_question_seconds)
        flow = NavigationFlow(question_key=q.key, question_number=q.number)
        current = self.observe("navigation", keep=True)
        steps = 0
        while steps < MAX_NAV_STEPS:
            self.checkpoint()
            steps += 1
            if ScreenState.TEST_COMPLETE in current.states:
                self._pending = current
                return
            key = current.analysis.question_key()
            if ScreenState.QUESTION_READY in current.states and key and not same_question(key, q.key):
                q.mark("new_question_verified", True)
                q.mark("navigation_retries", q.navigation_retries)
                self._pending = current
                return
            step = plan_navigation(current, flow)
            if step is None:
                self.logger.event("no_navigation_control", q.seq, category=FailureCategory.NAVIGATION)
                if self._handle_unknown(current, q):
                    current = self._pending or self.observe("navigation")
                    self._pending = None
                    continue
                break
            action, exp = step
            if action.purpose in ("submit", "save"):
                q.mark("submit_detected", True)
            elif action.purpose in ("next", "number_nav", "finish"):
                q.mark("next_detected", True)
            clicked_at = time.time()
            result = self.executor.execute(action, exp, current, q.seq)
            q.navigation_retries += max(0, result.attempts - 1)
            q.max_attempts = max(q.max_attempts, result.attempts)
            if action.purpose in ("submit", "save"):
                q.mark("submit_clicked", clicked_at)
                q.mark("submission_verified", result.success)
                if result.success:
                    flow.submitted = flow.saved = True
            elif action.purpose in ("next", "number_nav", "finish"):
                q.mark("next_clicked", clicked_at)
            flow.used.append(action.purpose)
            current = result.observation or self.observe("navigation")
            if not result.success:
                q.failure_categories.append((result.failure_category or FailureCategory.NAVIGATION).value)
                decision = self._recovery_failed(q, f"navigation failed: {result.message}")
                if decision != "retry":
                    break
                current = self.observe("after_intervention", keep=True)
        q.mark("new_question_verified", False)
        q.mark("navigation_retries", q.navigation_retries)
        self._pending = current

    def _handle_revisit(self, obs: Observation, done_key: str) -> None:
        """The screen still shows a question already handled: navigation did
        not advance. Try to move on without re-answering."""
        count = self._revisits.get(done_key, 0) + 1
        self._revisits[done_key] = count
        self.stats.navigation_failures += 1
        self.logger.event("question_not_advanced", category=FailureCategory.NAVIGATION, important=True,
                          key=done_key[:80], occurrence=count)
        if count > self.config.max_recovery_attempts:
            decision = self._recovery_failed(None, "navigation is stuck on an answered question")
            if decision != "retry":
                raise RunStopped("terminated")
            self._revisits[done_key] = 0
        flow = NavigationFlow(question_key=done_key, question_number=obs.analysis.question_number,
                              submitted=obs.analysis.answer_submitted_indicator)
        step = plan_navigation(obs, flow)
        if step is None:
            self._handle_unknown(obs)
            return
        result = self.executor.execute(step[0], step[1], obs, None)
        self._pending = result.observation

    # ================================================================== unknown state
    def _handle_unknown(self, obs: Observation, q: Optional[QuestionRecord] = None) -> bool:
        """Spec section 12: infer the screen's purpose and take the safest
        appropriate action only when confident enough."""
        seq = q.seq if q else self._qseq()
        self.stats.unknown_states += 1
        self._unknown_streak += 1
        self.logger.save_screenshot(obs, "unknown_state", seq)
        a = obs.analysis
        summary_lines = [f"Purpose guess from perception: {a.screen_purpose or '(none)'}"]
        if a.error_text:
            summary_lines.append(f"Error text: {a.error_text}")
        if a.dialog_text:
            summary_lines.append(f"Dialog text: {a.dialog_text}")
        if a.question_text:
            summary_lines.append(f"Text: {a.question_text}")
        for e in a.elements:
            flags = (" (selected)" if e.selected else "") + (" (disabled)" if e.disabled else "")
            summary_lines.append(f"{e.id}: {e.kind.value} '{e.label}'{flags}")
        image, _ = self.perceiver.model_image(obs.screenshot)
        try:
            rv = self.model.infer_unknown_screen("\n".join(summary_lines), image, self.config.reasoning_effort)
        except Exception as exc:
            self.logger.event("UNKNOWN_STATE", seq, category=FailureCategory.PERCEPTION, important=True,
                              error=repr(exc))
            return self._unknown_unresolved(seq)
        candidates = rv.get("candidate_actions", [])
        idx = rv.get("chosen_index", -1)
        chosen = candidates[idx] if isinstance(idx, int) and 0 <= idx < len(candidates) else None
        confidence = min(int(rv.get("confidence", 0)), int(chosen.get("confidence", 0)) if chosen else 0)
        self.logger.event("UNKNOWN_STATE", seq, important=True, purpose=rv.get("inferred_purpose", ""),
                          candidates=candidates, chosen=chosen, confidence=confidence)
        if (chosen is None or chosen.get("action") == "none" or chosen.get("risk") == "high"
                or confidence < self.config.confidence_threshold):
            time.sleep(self.config.loading_wait_seconds)
            return self._unknown_unresolved(seq)

        kind = chosen.get("action")
        if kind == "wait":
            time.sleep(max(2.0, self.config.loading_wait_seconds))
            self._unknown_streak = 0
            self._unresolved_cycles = 0
            self.stats.unknown_states_resolved += 1
            return True
        if kind == "click":
            el = next((e for e in a.elements if e.id == chosen.get("element_id")), None)
            if el is None:
                return self._unknown_unresolved(seq)
            action = Action("click", "unknown_state_action", el.kind, el.label, el.option_letter,
                            nav_number=el.nav_number, description=chosen.get("description", ""))
        elif kind == "press_key" and chosen.get("key"):
            action = Action("key", "unknown_state_action", key=chosen["key"], description=chosen.get("description", ""))
        elif kind in ("scroll_down", "scroll_up"):
            action = Action("scroll", "unknown_state_action", scroll_clicks=-5 if kind == "scroll_down" else 5,
                            point=content_scroll_point(obs), description=kind)
        else:
            return self._unknown_unresolved(seq)
        result = self.executor.execute(action, Expectation("screen_changed", chosen.get("description", "screen changes")),
                                       obs, seq)
        self.logger.event("unknown_state_outcome", seq, verified=result.success, detail=result.message)
        if result.success:
            self._unknown_streak = 0
            self._unresolved_cycles = 0
            self.stats.unknown_states_resolved += 1
            self._pending = result.observation
            return True
        return self._unknown_unresolved(seq)

    def _unknown_unresolved(self, seq) -> bool:
        self._unresolved_cycles += 1
        if self._unresolved_cycles > 3 * self.config.max_recovery_attempts + 3:
            self.logger.event("RUN_STUCK", seq, category=FailureCategory.UNKNOWN, important=True,
                              detail="unrecognized screens could not be resolved")
            raise RunStopped("stuck")
        if self._unknown_streak > self.config.max_recovery_attempts:
            self._unknown_streak = 0
            decision = self._recovery_failed(self.current_question, "unrecognized screen could not be resolved")
            if decision == "terminate":
                raise RunStopped("terminated")
        return False

    # ================================================================== policy
    def _recovery_failed(self, q: Optional[QuestionRecord], reason: str) -> str:
        """RECOVERY FAILED: skip, pause for human intervention, or terminate,
        according to the dashboard setting. Returns 'skip' | 'retry'."""
        policy = self.config.recovery_failure_policy
        self.logger.event("RECOVERY_FAILED_POLICY", q.seq if q else None, important=True,
                          reason=reason, policy=policy)
        if policy == "terminate":
            raise RunStopped("terminated")
        if policy == "pause":
            self.pause(f"Recovery failed ({reason}) - waiting for human intervention")
            self.checkpoint()
            return "retry"
        if q is not None and q.outcome == "in_progress":
            q.outcome = "skipped"
            self.stats.skipped += 1
            self.logger.event("question_skipped", q.seq, important=True, reason=reason)
        return "skip"

    # ================================================================== finish
    def _flush_model_calls(self) -> None:
        calls = self.model.calls[self._calls_logged:]
        self._calls_logged += len(calls)
        self.logger.model_calls(calls)

    def _finish_run(self, status: str) -> None:
        self.guard.stop_hotkey()
        if self.current_question is not None:
            q = self.current_question
            if q.outcome == "in_progress":
                q.outcome = "incomplete"
            q.duration_s = self.timer.stop()
            self.logger.question(q)
            self.current_question = None
        self._flush_model_calls()
        try:
            identity = self.model.identity()
        except Exception:
            identity = {"model_id": getattr(self.model, "model_id", "")}
        self.logger.event("RUN_ENDED", important=True, status=status,
                          total_time=format_seconds(time.monotonic() - self._run_started))
        self.logger.end_run(status, identity)
        report_path = ""
        try:
            from .report import generate_report
            report_path = generate_report(self.logger.run_dir, self.logger.db, self.run_id)
        except Exception as exc:
            self.logger.event("report_failed", important=True, error=repr(exc), trace=traceback.format_exc())
        self.logger.close()
        self._set(run_status={"complete": "COMPLETE"}.get(status, status.upper()), report=report_path,
                  message=f"Report: {report_path}" if report_path else self.status.get("message", ""))
