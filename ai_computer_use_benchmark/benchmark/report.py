"""Final case-study report (spec section 16), generated automatically when a
run ends. Re-grade later against an answer key with:

    python -m benchmark.report runs/<run_id> --answer-key key.csv
"""
from __future__ import annotations

import argparse
import html
import json
import os
from typing import Optional

from .config import format_seconds
from .database import Database
from .scoring import METHODOLOGY, grade, load_answer_key, measurements, scores


def _load_rows(db: Database, run_id: str) -> dict:
    runs = db.rows("runs", run_id)
    return {
        "run": runs[0] if runs else {},
        "questions": sorted(db.rows("questions", run_id), key=lambda r: r["seq"]),
        "interactions": db.rows("interactions", run_id),
        "events": db.rows("events", run_id),
        "screens": db.rows("screens", run_id),
        "model_calls": db.rows("model_calls", run_id),
    }


def generate_report(run_dir: str, db: Optional[Database] = None, run_id: Optional[str] = None,
                    answer_key_path: Optional[str] = None) -> str:
    own_db = db is None
    if own_db:
        db = Database(os.path.join(run_dir, "benchmark.db"))
    run_id = run_id or os.path.basename(os.path.normpath(run_dir))
    try:
        rows = _load_rows(db, run_id)
    finally:
        if own_db:
            db.close()

    answer_key = load_answer_key(answer_key_path) if answer_key_path else None
    graded = grade(rows["questions"], answer_key)
    m = measurements(rows, graded)
    s = scores(m, graded)
    run = rows["run"]
    report = {
        "run_id": run_id,
        "run": {k: run.get(k) for k in ("run_name", "started_at", "ended_at", "status", "config_hash", "prompt_hash")},
        "configuration": json.loads(run.get("config_json") or "{}"),
        "model_identity": json.loads(run.get("model_identity_json") or "{}"),
        "environment": json.loads(run.get("environment_json") or "{}"),
        "answer_key": os.path.abspath(answer_key_path) if answer_key_path else None,
        "measurements": m,
        "scores": s,
        "methodology": METHODOLOGY,
        "questions": [_question_summary(q) for q in graded],
        "model_usage": _model_usage(rows["model_calls"]),
    }
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    path = os.path.join(run_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_html(report))
    return os.path.abspath(path)


def _question_summary(q: dict) -> dict:
    intended = json.loads(q.get("intended_answer_json") or "{}")
    selected = json.loads(q.get("selected_answer_json") or "{}")
    return {
        "seq": q["seq"], "number": q.get("question_number"), "type": q.get("question_type"),
        "question": (q.get("question_text") or "")[:300],
        "intended": intended, "selected": selected, "confidence": q.get("confidence"),
        "outcome": q.get("outcome"), "grade": q.get("grade"), "correct_answer": q.get("correct_answer"),
        "failure_category": q.get("failure_category"), "duration_s": q.get("duration_s"),
        "multiple_attempts": bool(q.get("multiple_attempts")), "navigation_retries": q.get("navigation_retries"),
    }


def _model_usage(calls: list[dict]) -> dict:
    served = sorted({c["model_served"] for c in calls if c.get("model_served")})
    return {
        "calls": len(calls),
        "errors": sum(1 for c in calls if c.get("error")),
        "refusals": sum(1 for c in calls if c.get("error") == "refusal"),
        "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
        "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
        "models_served": served,
    }


# ---------------------------------------------------------------- HTML
def _fmt(v, suffix="") -> str:
    if v is None or v == "":
        return "--"
    return f"{v}{suffix}"


def _secs(v) -> str:
    return "--" if v is None else f"{format_seconds(v)} ({v} s)"


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in pairs)


def _html(r: dict) -> str:
    m, s = r["measurements"], r["scores"]
    p, sp, cu = m["performance"], m["speed"], m["computer_use"]
    model = r["model_identity"]
    score_rows = [
        ("Question Accuracy", _fmt(s["question_accuracy"])),
        ("Visual Perception", _fmt(s["visual_perception"])),
        ("Navigation Reliability", _fmt(s["navigation_reliability"])),
        ("Interaction Reliability", _fmt(s["interaction_reliability"])),
        ("Recovery Ability", _fmt(s["recovery_ability"])),
        ("Completion Rate", _fmt(s["completion_rate"])),
    ]
    failure_rows = "".join(
        f"<tr><th>{html.escape(cat)}</th><td>{v['questions']}</td><td>{v['events']}</td></tr>"
        for cat, v in m["failure_analysis"].items())
    q_rows = []
    for q in r["questions"]:
        answer = q["selected"].get("text") or "; ".join(q["selected"].get("labels") or []) or "--"
        intended = q["intended"].get("text") or "; ".join(q["intended"].get("labels") or []) or "--"
        q_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in (
                q["number"] if q["number"] is not None else f"seq {q['seq']}", q["type"] or "--",
                q["question"][:120], intended, answer, _fmt(q["confidence"], "%"), q["outcome"], q["grade"],
                q["correct_answer"] or "--", q["failure_category"] or "--",
                _fmt(round(q["duration_s"], 1) if q["duration_s"] is not None else None, " s"),
                "yes" if q["multiple_attempts"] else "no")) + "</tr>")
    usage = r["model_usage"]
    note = "" if r["configuration"].get("benchmark_mode", True) else (
        "<p class='note'>Development run: Benchmark Mode was off. Not a locked, fair-test result.</p>")
    note += "" if r["answer_key"] else (
        "<p class='note'>No answer key supplied: correct/incorrect and Question Accuracy are not graded. "
        "Re-grade with <code>python -m benchmark.report &lt;run dir&gt; --answer-key key.csv</code>.</p>")
    methodology = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>" for k, v in r["methodology"].items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmark Report - {html.escape(r['run']['run_name'] or '')}</title>
<style>
:root {{ --bg:#fff; --fg:#1b1f24; --muted:#5b6470; --line:#d8dde3; --accent:#1f4e79; --card:#f5f7fa; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171b; --fg:#e6e9ed; --muted:#9aa4b0; --line:#2c333b;
  --accent:#7fb2e5; --card:#1c2127; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,Segoe UI,sans-serif; margin:0; padding:24px 16px; }}
main {{ max-width:1100px; margin:auto; }}
h1 {{ margin:0 0 4px; }} h2 {{ color:var(--accent); border-bottom:1px solid var(--line); padding-bottom:4px; margin-top:32px; }}
.sub {{ color:var(--muted); }} .note {{ background:var(--card); padding:10px 12px; border-left:3px solid var(--accent); }}
table {{ border-collapse:collapse; width:100%; margin:8px 0; }} th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font-weight:600; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }}
.score {{ font-size:40px; font-weight:700; color:var(--accent); }} .wrap {{ overflow-x:auto; }}
</style></head><body><main>
<h1>AI Computer-Use Intelligence Benchmark</h1>
<div class="sub">Run {html.escape(r['run']['run_name'] or '')} &middot; id {html.escape(r['run_id'])} &middot; status {html.escape(str(r['run']['status']))}
 &middot; {html.escape(str(r['run']['started_at']))} &rarr; {html.escape(str(r['run']['ended_at']))}</div>
{note}
<h2>Case-Study Scores</h2>
<div class="grid"><div><table>{_rows(score_rows)}</table></div>
<div><div class="sub">AI Computer Intelligence Benchmark Score (optional composite)</div>
<div class="score">{_fmt(s['ai_computer_intelligence_benchmark_score'])}</div>
<div class="sub">Components used: {html.escape(', '.join(s['composite_components_used']) or 'none')}</div></div></div>
<div class="grid">
<div><h2>Performance</h2><table>{_rows([
    ("Total questions", p['total_questions']), ("Correct", p['correct']), ("Incorrect", p['incorrect']),
    ("Skipped", p['skipped']), ("Ungraded", p['ungraded']), ("Accuracy", _fmt(p['accuracy_pct'], '%')),
    ("Completion", _fmt(p['completion_pct'], '%')), ("Average confidence", _fmt(p['average_confidence'], '%')),
    ("Results screen", p['results_screen_text'] or '--')])}</table></div>
<div><h2>Speed</h2><table>{_rows([
    ("Total completion time", _secs(sp['total_completion_time_s'])),
    ("Average time / question", _secs(sp['average_time_per_question_s'])),
    ("Fastest question", _secs(sp['fastest_question_s'])), ("Slowest question", _secs(sp['slowest_question_s'])),
    ("Median question time", _secs(sp['median_question_time_s']))])}</table></div>
<div><h2>Computer-Use Performance</h2><table>{_rows([
    ("Successful first-attempt interactions", f"{cu['successful_first_attempt_interactions']} / {cu['interactions']}"),
    ("Failed clicks / interactions", cu['failed_interactions']), ("Recovery attempts", cu['recovery_attempts']),
    ("Successful recoveries", f"{cu['successful_recoveries']} / {cu['recovery_episodes']}"),
    ("Unknown states", f"{cu['unknown_states']} ({cu['unknown_states_resolved']} resolved)"),
    ("Navigation failures", f"{cu['navigation_failures']} / {cu['navigation_attempts']} attempts"),
    ("Questions requiring multiple attempts", cu['questions_requiring_multiple_attempts']),
    ("Perception cycles (failed)", f"{cu['perception_cycles']} ({cu['perception_failures']})"),
    ("Human interventions", cu['human_interventions'])])}</table></div>
</div>
<h2>Intelligence Analysis - Failure Categories</h2>
<p class="sub">A wrong answer from misunderstanding the question is a different failure from knowing the answer but
not operating the control. "Questions" counts graded questions by cause; "Events" counts failures logged during the run.</p>
<table><tr><th>Category</th><th>Questions</th><th>Events</th></tr>{failure_rows}</table>
<h2>Questions</h2><div class="wrap"><table>
<tr><th>Q</th><th>Type</th><th>Question</th><th>Intended</th><th>Selected</th><th>Conf.</th><th>Outcome</th>
<th>Grade</th><th>Key</th><th>Failure</th><th>Time</th><th>Multi-attempt</th></tr>
{''.join(q_rows)}</table></div>
<h2>Fair-Test Record</h2><table>{_rows([
    ("Model", json.dumps(model, default=str)),
    ("Benchmark mode (locked)", r['configuration'].get('benchmark_mode')),
    ("Strict mode", r['configuration'].get('strict_mode')),
    ("Configuration hash", r['run']['config_hash']), ("Prompt hash", r['run']['prompt_hash']),
    ("Model calls / errors / refusals", f"{usage['calls']} / {usage['errors']} / {usage['refusals']}"),
    ("Tokens in / out", f"{usage['input_tokens']} / {usage['output_tokens']}"),
    ("Models that served responses", ', '.join(usage['models_served']) or '--'),
    ("Environment", json.dumps(r['environment']))])}</table>
<h2>Configuration</h2><table>{_rows(sorted(r['configuration'].items()))}</table>
<h2>Methodology</h2><ul>{methodology}</ul>
<p class="sub">Raw data: report.json, benchmark.db, events.jsonl, event_log.txt, screenshots/.</p>
</main></body></html>"""


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Generate or re-grade a benchmark report.")
    parser.add_argument("run_dir")
    parser.add_argument("--answer-key", help="CSV: question,correct_answer[,failure_category][,notes]")
    args = parser.parse_args(argv)
    print(generate_report(args.run_dir, answer_key_path=args.answer_key))


if __name__ == "__main__":
    main()
