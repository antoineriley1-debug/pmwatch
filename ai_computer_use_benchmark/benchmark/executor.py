"""Executes one semantic action: locate on the current screen -> act ->
re-capture -> verify -> recover. Coordinates are always computed fresh."""
from __future__ import annotations

from .controller.safety import ResumedAfterSafetyPause
from .core import Action, ActionResult, FailureCategory, Observation
from .recovery import RecoveryManager, choose_point, locate
from .verification import Expectation, Verifier

_NAV_PURPOSES = {"submit", "save", "next", "number_nav", "finish", "confirm"}


class ActionExecutor:
    def __init__(self, controller, guard_check, verifier: Verifier, recovery: RecoveryManager,
                 observe, wait_for_settle, logger, stats, max_recovery_attempts: int, checkpoint):
        self.controller = controller
        self.guard_check = guard_check      # safety check before every OS input
        self._last_obs = None
        self.verifier = verifier
        self.recovery = recovery
        self.observe = observe
        self.wait_for_settle = wait_for_settle
        self.logger = logger
        self.stats = stats
        self.max_recovery_attempts = max_recovery_attempts
        self.checkpoint = checkpoint

    # ------------------------------------------------------------------
    def execute(self, action: Action, exp: Expectation, before: Observation, question_seq=None) -> ActionResult:
        is_nav = action.purpose in _NAV_PURPOSES
        if is_nav:
            self.stats.navigation_attempts += 1
        self.stats.interactions += 1

        tried: list[tuple[int, int]] = []
        current = before
        element = None if action.kind in ("scroll", "key", "wait") else locate(action, current.analysis)
        if action.kind in ("click", "type") and element is None:
            element = self._find_with_scroll(action, current, question_seq)
            if element is not None:
                current = self._last_obs
        attempts = 0
        max_attempts = 1 + self.max_recovery_attempts
        notes = []
        in_recovery = False

        while attempts < max_attempts:
            self.checkpoint()
            attempts += 1
            if action.kind in ("click", "type"):
                if element is None:
                    notes.append("target not found")
                    break
                point = choose_point(element, tried)
                if point is None:
                    notes.append("no untried location remains for this control")
                    break
                tried.append(point)
            else:
                point = action.point

            try:
                self._perform(action, point)
            except ResumedAfterSafetyPause:
                # A human resumed after a safety pause: re-read the screen and
                # relocate; this does not count as an attempt.
                attempts -= 1
                current = self.wait_for_settle(self.observe("after_safety_pause"))
                if action.kind in ("click", "type"):
                    element, tried = locate(action, current.analysis), []
                continue
            after = self.wait_for_settle(self.observe(action.purpose))
            ok, msg = self.verifier.verify(current, after, exp)
            self.logger.event("action", question_seq, purpose=action.purpose,
                              target=action.target_label or action.key or action.kind,
                              point=point, attempt=attempts, verified=ok, detail=msg)
            if ok:
                return self._finish(action, exp, attempts, True, after, notes + [msg], tried,
                                    question_seq, is_nav, in_recovery)
            notes.append(msg)

            if attempts >= max_attempts:
                break
            # ---- recovery -------------------------------------------------
            in_recovery = True
            self.stats.recovery_attempts += 1
            if attempts == 1:
                self.stats.recovery_episodes += 1
            outcome = self.recovery.recover(action, exp, current)
            self.logger.event("recovery_attempt", question_seq, purpose=action.purpose,
                              attempt=attempts, status=outcome.status, detail=outcome.note)
            if outcome.status == "late_success":
                return self._finish(action, exp, attempts, True, outcome.observation,
                                    notes + [outcome.note], tried, question_seq, is_nav, in_recovery)
            if outcome.status == "page_changed":
                notes.append(outcome.note)
                return self._finish(action, exp, attempts, False, outcome.observation, notes, tried,
                                    question_seq, is_nav, in_recovery, category=FailureCategory.NAVIGATION
                                    if is_nav else FailureCategory.INTERACTION)
            current = outcome.observation
            element = outcome.element
            if outcome.status == "not_found" and action.kind in ("click", "type"):
                element = self._find_with_scroll(action, current, question_seq)
                if element is not None:
                    current = self._last_obs

        category = self._category_for(action, element, is_nav)
        return self._finish(action, exp, attempts, False, current, notes, tried, question_seq,
                            is_nav, in_recovery, category=category)

    # ------------------------------------------------------------------
    def _perform(self, action: Action, point) -> None:
        self.guard_check(point)
        if action.kind == "click":
            self.controller.click(*point)
        elif action.kind == "type":
            self.controller.click(*point)
            self.guard_check(point)
            self.controller.select_all()
            self.controller.type_text(action.text)
        elif action.kind == "scroll":
            self.controller.scroll(point[0], point[1], action.scroll_clicks)
        elif action.kind == "key":
            self.controller.press_key(action.key)
        elif action.kind == "wait":
            pass

    def _find_with_scroll(self, action: Action, obs: Observation, question_seq):
        """The control may be outside the viewport: scroll to look for it,
        down first, then back up. Returns the element or None."""
        from .planner import content_scroll_point
        self._last_obs = obs
        current = obs
        for clicks, limit in ((-5, 4), (5, 8)):
            for _ in range(limit):
                self.checkpoint()
                point = content_scroll_point(current)
                try:
                    self.guard_check(point)
                except ResumedAfterSafetyPause:
                    current = self.wait_for_settle(self.observe("after_safety_pause"))
                    continue
                self.controller.scroll(point[0], point[1], clicks)
                nxt = self.wait_for_settle(self.observe("scroll_search"))
                ok, _ = self.verifier.verify(current, nxt, Expectation(
                    "scrolled", "content scrolled", previous_question_key=current.analysis.question_key()))
                current = nxt
                self._last_obs = current
                el = locate(action, current.analysis)
                if el is not None:
                    self.logger.event("located_after_scroll", question_seq, target=action.target_label)
                    return el
                if not ok:
                    break   # reached the end in this direction
        return None

    def _category_for(self, action: Action, element, is_nav: bool) -> FailureCategory:
        if element is None:
            return FailureCategory.PERCEPTION
        if is_nav:
            return FailureCategory.NAVIGATION
        return FailureCategory.INTERACTION

    def _finish(self, action, exp, attempts, success, obs, notes, tried, question_seq, is_nav,
                in_recovery, category=None) -> ActionResult:
        if success:
            if attempts == 1 and not in_recovery:
                self.stats.first_attempt_successes += 1
            if in_recovery:
                self.stats.successful_recoveries += 1
            if is_nav:
                self.stats.navigation_successes += 1
        else:
            self.stats.failed_interactions += 1
            if is_nav:
                self.stats.navigation_failures += 1
            if in_recovery or attempts > 1:
                self.stats.recoveries_failed += 1
                self.logger.event("RECOVERY_FAILED", question_seq, category=category, important=True,
                                  purpose=action.purpose, attempts=attempts, notes=notes[-3:])
            else:
                self.logger.event("action_failed", question_seq, category=category,
                                  purpose=action.purpose, notes=notes[-3:])
        self.logger.interaction(question_seq, action.purpose, action.target_label or action.key,
                                attempts, success, in_recovery, tried, "; ".join(notes[-3:]))
        return ActionResult(action=action, success=success, attempts=attempts, verified=success,
                            observation=obs, message="; ".join(notes[-3:]), failure_category=category)
