#!/usr/bin/env python3
"""Tune the reload thresholds against the calls you graded.

    python tune.py recordings/twiney-20261001-093000.jsonl

Replays the recording with a grid of reload settings and reports, for each
setting, how many of your GOOD calls it still makes and how many BAD calls it
avoids. Grades come from the 👍 / 👎 buttons on the dashboard (saved to
recordings/grades.jsonl and inside the recording itself).
"""

import itertools
import json
import os
import sys

from twiney.recorder import read_events
from twiney.replay import replay

GRID = {
    "min_refreshes": [2, 3, 4],
    "min_absorbed_shares": [1000, 2000, 4000],
    "absorbed_multiple": [1.5, 2.0, 3.0],
}


def load_grades(rec_path):
    grades = {}
    for ev in read_events(rec_path):
        if ev.get("ev") == "grade":
            if ev.get("verdict"):
                grades[ev["key"]] = ev["verdict"]
            else:
                grades.pop(ev["key"], None)
    gp = os.path.join(os.path.dirname(rec_path) or ".", "grades.jsonl")
    if os.path.exists(gp):
        for ev in read_events(gp):
            if ev.get("verdict"):
                grades[ev["key"]] = ev["verdict"]
            else:
                grades.pop(ev["key"], None)
    return grades


def loose_key(key):
    """Match a call by symbol + label + price, within 2 minutes (thresholds move the exact time)."""
    t, sym, label, price = key.split("|")
    return sym, label, price, float(t)


def main(path):
    grades = load_grades(path)
    good = [loose_key(k) for k, v in grades.items() if v == "good"]
    bad = [loose_key(k) for k, v in grades.items() if v == "bad"]
    if not good and not bad:
        print("No graded calls in this recording yet. Use 👍 / 👎 on the dashboard first.")
        return 1
    header = next(ev for ev in read_events(path) if ev.get("ev") == "session")
    base_cfg, plays = header["config"], header["plays"]
    print(f"{len(good)} good / {len(bad)} bad graded calls. Trying {len(list(itertools.product(*GRID.values())))} settings…\n")
    rows = []
    for combo in itertools.product(*GRID.values()):
        cfg = json.loads(json.dumps(base_cfg))
        cfg["reload"].update(dict(zip(GRID.keys(), combo)))
        engine, _ = replay(path, plays=plays, cfg=cfg)
        made = [(a["symbol"], a["label"], str(a["price"]), a["t"]) for a in engine.alerts]

        def hit(g):
            return any(m[0] == g[0] and m[1] == g[1] and m[2] == g[2] and abs(m[3] - g[3]) <= 120 for m in made)
        kept = sum(1 for g in good if hit(g))
        avoided = sum(1 for g in bad if not hit(g))
        rows.append((kept, avoided, len(made), combo))
    rows.sort(key=lambda r: (-(r[0] + r[1]), r[2]))
    print(f"{'refills':>8} {'shares':>7} {'x shown':>8} | {'good kept':>9} {'bad avoided':>11} {'total calls':>11}")
    for kept, avoided, n, combo in rows[:12]:
        print(f"{combo[0]:>8} {combo[1]:>7} {combo[2]:>8} | {kept:>4}/{len(good):<4} {avoided:>5}/{len(bad):<5} {n:>11}")
    best = rows[0][3]
    print(f"\nBest: min_refreshes={best[0]}, min_absorbed_shares={best[1]}, absorbed_multiple={best[2]}"
          f"  → put these under \"reload\" in config.json")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
