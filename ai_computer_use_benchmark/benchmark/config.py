"""Run configuration. Frozen once a Benchmark Mode run begins (spec section 18)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

# Section 8: minimum time per question. Range 45 s - 5 min, default 2:45.
MIN_DWELL_SECONDS = 45
MAX_DWELL_SECONDS = 300
DEFAULT_MIN_DWELL_SECONDS = 165
DWELL_PRESETS = [
    ("45 sec", 45),
    ("1:00", 60),
    ("1:30", 90),
    ("2:00", 120),
    ("2:45", 165),
    ("3:00", 180),
    ("4:00", 240),
    ("5:00", 300),
]

RECOVERY_FAILURE_POLICIES = ("skip", "pause", "terminate")

EMERGENCY_STOP_HOTKEY = "<ctrl>+<shift>+<f12>"
EMERGENCY_STOP_LABEL = "Ctrl + Shift + F12"


@dataclass(frozen=True)
class RunConfig:
    run_name: str = "CASE-STUDY-001"
    model_id: str = "claude-opus-5-5"

    # Timing
    min_question_seconds: int = DEFAULT_MIN_DWELL_SECONDS
    max_question_seconds: int = 600

    # Decision policy
    confidence_threshold: int = 60          # 0-100
    allow_skipping: bool = False
    max_recovery_attempts: int = 3
    recovery_failure_policy: str = "pause"  # skip | pause | terminate

    # Logging
    screenshot_logging: bool = True
    detailed_event_logging: bool = True

    # Research / fair-test mode
    benchmark_mode: bool = True             # locked mode: config frozen, no assistance
    strict_mode: bool = True                # no selectors, no fixed coordinates, no app knowledge

    # Safety
    target_window_title: str = ""           # allowed application/window (substring match)
    pause_on_focus_loss: bool = True
    max_consecutive_actions: int = 60

    # Perception
    monitor_index: int = 1                  # mss monitor index (1 = primary)
    perception_max_edge: int = 1568         # longest edge of the image sent to the model
    loading_wait_seconds: float = 1.5

    # Reasoning
    reasoning_effort: str = "high"
    perception_effort: str = "low"
    review_interval_seconds: int = 30       # how often the dwell-time review runs
    max_review_passes: int = 4

    output_dir: str = "runs"

    def validate(self) -> None:
        if not MIN_DWELL_SECONDS <= self.min_question_seconds <= MAX_DWELL_SECONDS:
            raise ValueError(
                f"Minimum time per question must be between {MIN_DWELL_SECONDS} and "
                f"{MAX_DWELL_SECONDS} seconds."
            )
        if self.max_question_seconds < self.min_question_seconds:
            raise ValueError("Maximum question time must be >= minimum time per question.")
        if not 0 <= self.confidence_threshold <= 100:
            raise ValueError("Confidence threshold must be 0-100.")
        if self.max_recovery_attempts < 1:
            raise ValueError("Maximum recovery attempts must be at least 1.")
        if self.recovery_failure_policy not in RECOVERY_FAILURE_POLICIES:
            raise ValueError(f"Recovery failure policy must be one of {RECOVERY_FAILURE_POLICIES}.")
        if not self.run_name.strip():
            raise ValueError("Test/run name is required.")

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        """Stable hash of the configuration, recorded with every run."""
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()

    def with_changes(self, **changes) -> "RunConfig":
        return replace(self, **changes)


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_duration(text: str) -> int:
    """Parse '2:45', '165', '45 sec' into seconds."""
    text = text.strip().lower().replace("sec", "").replace("s", "").strip()
    if ":" in text:
        minutes, secs = text.split(":", 1)
        return int(minutes) * 60 + int(secs)
    return int(float(text))
