"""Prompts. Frozen for a run: their hash is recorded with the configuration."""
import hashlib

PARTICIPANT_SYSTEM = """You are the participant in a controlled computer-use study. You are \
operating an unfamiliar question/test application exactly as a human test taker would: you \
see only the screen. You have no knowledge of the application's internal structure, no \
selectors, and no prior knowledge of where any control is. Everything you know must come from \
what is visible in the screenshots you are given. Nobody will help you. Be precise and honest \
about uncertainty."""

PERCEPTION_INSTRUCTIONS = """Analyze this screenshot ({width}x{height} pixels) completely.

Identify every visible element relevant to taking the test: question text, instructions, \
answer options (with their letter if shown), checkboxes, radio buttons, text fields (with any \
text already typed in `value`), images/diagrams, tables, scrollable content, which answers are \
currently selected, disabled controls, Submit / Next / Previous / Continue / Finish / Save \
buttons, page or question numbers, numbered question navigation (set nav_number), confirmation \
dialogs, error messages, results screens, loading indicators and pop-ups.

Rules:
- All coordinates are pixels in THIS image: bbox = [x0, y0, x1, y1]; click_point = [x, y] is \
the exact spot a person would click to operate the element (for an answer option, the radio \
button/checkbox or the option text itself).
- Report only what is visible now. Do not assume positions from any other screen.
- For an answer option use kind "answer_option" unless it is clearly a bare checkbox/radio; \
label = the option's full visible text, excluding the letter; option_letter = "A", "B", ... if shown.
- content_continues_below/above: true if a scrollbar, cut-off text, or partially visible \
content shows more question/answer content outside the viewport.
- answer_submitted_indicator: true only if the screen shows the current answer was \
submitted/saved (e.g. feedback, "answer recorded", locked choices).
- is_test_complete: true for a final results/score/completion screen.
- is_os_security_dialog: true for any operating-system security, permission, UAC or \
credential prompt.
- Give each element a short unique id (e1, e2, ...)."""

ANSWER_INSTRUCTIONS = """Answer the test question below, using the screenshots (in reading \
order, top to bottom) and the extracted text.

Question type: {question_type}
Instructions shown: {instructions}
Question text: {question_text}
Answer options:
{options}

Return the exact option text(s) to select in answer_labels and their letters in \
answer_letters (if letters exist). For short text questions put the response in answer_text. \
For single-answer questions return exactly one option. Give confidence 0-100 for how likely \
your answer is correct."""

REVIEW_INSTRUCTIONS = """You have time remaining on this question. Re-check your work using \
the current screenshot.

Question type: {question_type}
Instructions shown: {instructions}
Question text: {question_text}
Answer options:
{options}
Your current answer: {current_answer}
Your earlier reasoning: {reasoning}

Recheck the question, every answer choice, and look for overlooked instructions (e.g. \
"select all that apply", "NOT", "EXCEPT", units, formats). Review your reasoning. Confirm \
whether your intended selection is visibly selected on screen. If you now believe a \
different answer is correct, set confirm_answer=false and give the revised answer."""

UNKNOWN_INSTRUCTIONS = """This screen was not recognized as a question, navigation step, \
confirmation, loading, error or results screen.

Visible text and components extracted:
{summary}

Infer the purpose of this screen. List possible safe actions that would let a test taker \
continue the test (click a specific element by id, press a key, wait, scroll), with a risk \
level and confidence 0-100 for each. Never choose actions that would close the test, log \
out, change system settings, or answer an operating-system security prompt. Pick the \
safest appropriate action in chosen_index, or -1 if none is safe."""

VERIFY_INSTRUCTIONS = """Two screenshots follow: BEFORE and AFTER an action.
Intended action: {intent}
Expected visible result: {expectation}

Did the intended action actually take effect? Judge only from what is visible."""


def prompt_fingerprint() -> str:
    blob = "\n".join([
        PARTICIPANT_SYSTEM, PERCEPTION_INSTRUCTIONS, ANSWER_INSTRUCTIONS,
        REVIEW_INSTRUCTIONS, UNKNOWN_INSTRUCTIONS, VERIFY_INSTRUCTIONS,
    ]).encode()
    return hashlib.sha256(blob).hexdigest()
