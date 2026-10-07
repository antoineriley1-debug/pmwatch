# AI Computer-Use Intelligence Benchmark

A Windows-first desktop application for a controlled case study. It measures how well an AI can operate an unfamiliar computer-based question system on its own, the way a human test participant would:

**see screen → understand screen → identify question → determine answer → interact → verify → navigate → repeat**

The AI gets the screen and has to figure out the rest. It uses no site-specific selectors, no fixed coordinates, and no knowledge of the test application's internals. Every click location is computed fresh from the current screenshot.

## Setup (Windows)

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set ANTHROPIC_API_KEY=...
python run_benchmark.py
```

OCR grounding is optional. To use it, install the [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) binary. Without it, perception uses the vision model's own coordinates.

## Running a case study

1. Open the question interface you are testing.
2. In the dashboard, set the run name, AI model, and minimum time per question (default **2:45**). Also set the allowed application window title (a substring of the target window's title) and the other options.
3. Press **START**, then take your hands off the computer. The dashboard minimizes and the target window is brought to the front.
4. **Emergency stop:** `Ctrl + Shift + F12`, or the red button. All automated mouse and keyboard input stops immediately. Slamming the mouse into a screen corner also aborts (pyautogui fail-safe).

The run finishes when the AI reaches the results or completion screen. The report is generated automatically.

## Architecture

```
Desktop UI (ui/dashboard.py)
    ↓
Orchestrator (orchestrator.py)
    ├── Screen Capture        perception/capture.py
    ├── Vision/Perception     perception/vision.py, perception/ocr.py
    ├── State Classifier      state_engine.py
    ├── Question Reasoner     reasoning/ (swappable model interface + Claude adapter)
    ├── Action Planner        planner.py, question_types.py
    ├── Computer Controller   controller/base.py, controller/windows.py, controller/safety.py
    ├── Verification Engine   verification.py
    ├── Recovery Manager      recovery.py, executor.py
    ├── Timer                 timer.py
    └── Benchmark Logger      logger.py
            ↓
         Database             database.py (SQLite, append-only)
            ↓
      Report Generator        report.py, scoring.py
```

* **Swappable AI model:** `reasoning/base.py` defines `ReasoningModel`. To benchmark another model under identical conditions (same prompts, same JSON schemas), add an adapter and register it in `reasoning/registry.py`.
* **Platform independence:** the reasoning layer never imports the Windows controller. To port to Linux or macOS, implement `controller/base.py:ComputerController`.

## Spec coverage

| Spec section | Where |
|---|---|
| 3 Full-screen perception | `perception/vision.py`. Every element listed in the spec is extracted from each screenshot. |
| 4 Semantic interaction | `core.Action` names *what* to act on. `recovery.locate()` finds it on the current screen. |
| 5 Screen state engine | `state_engine.classify()` returns a *set* of states, since several can hold at once. |
| 6 Question workflow | `Orchestrator._process_question()` runs steps 1–18. A click is never assumed to have worked. |
| 7 Navigation intelligence | `planner.plan_navigation()`: Next / Submit→Next / Submit→Continue / numbered / Save→Next / confirmation→Continue / Finish |
| 8 Question timing | `timer.py` starts when the question is recognized. Spare dwell time goes to review passes: recheck the question, choices, instructions, reasoning and the selection. |
| 9 Dashboard | `ui/dashboard.py` |
| 10 Verification | `verification.py` compares BEFORE and AFTER screenshots. Ambiguous pixel evidence goes to the model. |
| 11 Recovery | `executor.py` + `recovery.py`: fresh screen → reclassify → relocate → page-changed check → corrected interaction at a *different* point → verify → RECOVERY FAILED → skip, pause or terminate |
| 12 Unknown states | `Orchestrator._handle_unknown()`. Infers purpose and safe actions with confidence, acts only above the threshold, verifies, and logs everything. |
| 13 Question types | `question_types.py`: single choice, true/false, yes/no, multi-select, short text. New types plug in as handlers. |
| 14 Scrolling | `Orchestrator._build_context()` reads → scrolls → reads more. A question change during scrolling is flagged, not treated as advancing. |
| 15 Logging | `runs/<run>/event_log.txt`, `events.jsonl`, `benchmark.db`, `screenshots/` |
| 16 Report | `runs/<run>/report.html` + `report.json` |
| 17 Scoring | `scoring.py`: separate 0–100 scores plus an optional composite. Raw measurements and methodology are included. |
| 18 Fair-test mode | Config is a frozen dataclass. Config and prompt hashes, model identity, environment, every pause, resume and intervention are recorded. The database has no delete path. |
| 19 Safety | `controller/safety.py`: emergency stop hotkey, allowed-window restriction, max consecutive actions, max recovery attempts, pause on focus loss, OS security dialogs blocked |

## Grading against an answer key

Correct and incorrect answers need an answer key. It is used **only after the run** and is never shown to the AI.

```csv
question,correct_answer,failure_category,notes
1,B,,
2,Paris;Rome,,multiple correct options separated by ;
3,42,knowledge,reviewer annotation
```

```bat
python -m benchmark.report runs\<run id> --answer-key key.csv
```

`question` is the question number shown on screen, or the run sequence number if the test shows none. `correct_answer` takes letters, option text, or the typed answer. The optional `failure_category` column (perception, reasoning, knowledge, navigation, interaction, verification, unknown) records a reviewer's judgment of why a question was missed.

Wrong answers are categorized automatically when the run itself shows the cause. If the selected answer differs from the AI's intended answer, it is an INTERACTION error. Reasoning vs. knowledge vs. perception can't be told apart from the screen, so those stay UNKNOWN until a reviewer annotates them.

## Configuration

These dashboard fields map to `config.RunConfig`. Other fields keep their defaults:

| Setting | Default |
|---|---|
| Minimum time / question | 2:45 (range 45 s – 5 min; presets 45 s, 1:00, 1:30, 2:00, 2:45, 3:00, 4:00, 5:00, Custom) |
| Maximum question time | 10:00 |
| Confidence threshold | 60 % |
| Allow skipping | off |
| Maximum recovery attempts | 3 |
| On recovery failure | pause (skip / pause / terminate) |
| Screenshot logging / detailed event logging | on / on |
| Benchmark Mode (locked) | on |
| Max consecutive actions | 60 |
