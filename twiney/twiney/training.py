"""REPLAY TRAINING: the desk makes a call, the replay pauses, you answer LONG / SHORT / WAIT, and five minutes of the
recording later you find out which way it went. Every answer and its outcome goes to recordings/training.jsonl; the
replay bar keeps the score. Only the spoken calls with a direction in them are asked (the same calls THE DESK SCORE
judges): the second entry live, a reload buyer / seller, CLEANED UP, a level taken on a close, a breakout with speed,
a program, calls / puts pounded, the open read."""

import json
import threading
from collections import deque

from .scorecard import classify

ANSWERS = ("long", "short", "wait")


class Trainer:
    HORIZON = 300.0

    def __init__(self, path=None, cfg=None):
        self.path = path
        self.cfg = cfg or {}
        self.on = False
        self.quiz = None            # the call waiting for your answer
        self.pending = []           # answered, waiting for their five minutes
        self.results = deque(maxlen=60)
        self.n = 0
        self.right = 0
        self.last_t = {}            # symbol -> time of its last question (one question a minute per stock)
        self.last_any = -1e9        # the last question on any stock: a breath between questions
        self.lock = threading.Lock()

    def ask(self, alert, t, price, atr):
        """A spoken call with a direction in it becomes the question. Returns it, or None."""
        label = str(alert.get("label") or "")
        spoken = bool(alert.get("words")) or label == "CLEANED UP" or label.startswith("RELOAD")   # reload calls speak through the voice queue
        if not self.on or self.quiz is not None or not spoken or not price:
            return None
        c = classify(alert)
        if not c or not c[1]:
            return None
        sym = alert.get("symbol")
        if t - self.last_t.get(sym, -1e9) < float(self.cfg.get("gap_seconds", 60)) or t - self.last_any < float(self.cfg.get("any_gap_seconds", 20)):
            return None
        self.last_t[sym] = t
        self.last_any = t
        q = {"t": float(t), "symbol": sym, "kind": c[0], "dir": c[1], "p0": float(price), "atr": float(atr or 0) or None,
             "text": str(alert.get("text") or "")[:200]}
        with self.lock:
            self.quiz = q
        return q

    def answer(self, a):
        a = str(a or "").lower()
        if a not in ANSWERS:
            return False
        with self.lock:
            q = self.quiz
            if q is None:
                return False
            self.quiz = None
            self.pending.append(dict(q, answer=a))
        return True

    def skip(self):
        with self.lock:
            self.quiz = None

    def tick(self, t, prices):
        """prices: {symbol: last}. Judges the answers whose five minutes have passed. Returns the judged ones."""
        out = []
        with self.lock:
            keep = []
            for q in self.pending:
                px = prices.get(q["symbol"])
                if t >= q["t"] + self.HORIZON and px:
                    thr = float(self.cfg.get("hit_atr", 0.1)) * (q["atr"] or q["p0"] * 0.018)
                    move = px - q["p0"]
                    went = "long" if move >= thr else "short" if move <= -thr else "wait"
                    q.update(move=round(move, 4), pct=round(move / q["p0"] * 100, 2) if q["p0"] else None, went=went,
                             right=q["answer"] == went, desk="long" if q["dir"] > 0 else "short", judged=float(t))
                    q["desk_right"] = q["desk"] == went
                    self.n += 1
                    self.right += 1 if q["right"] else 0
                    self.results.appendleft(q)
                    out.append(q)
                    if self.path:
                        try:
                            with open(self.path, "a", encoding="utf-8") as f:
                                f.write(json.dumps(q) + "\n")
                        except OSError:
                            pass
                elif t < q["t"] + self.HORIZON + 1800:
                    keep.append(q)            # a jump far past it with no price: dropped
            self.pending = keep
        return out

    def view(self):
        with self.lock:
            return {"on": self.on, "quiz": dict(self.quiz) if self.quiz else None, "n": self.n, "right": self.right,
                    "pct": round(100.0 * self.right / self.n) if self.n else None, "pending": len(self.pending),
                    "recent": [dict(r) for r in list(self.results)[:12]]}
