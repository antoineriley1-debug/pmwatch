"""THE PHRASE LIST: other ways to say each spoken call, in Twiney's words, and only the ones Twiney approved.

Each call the voice says has its built-in line (the desk's own words, always allowed) with the numbers as
{placeholders}. The DESK AI writes versions of a line (WRITE VERSIONS); they wait as PENDING until Twiney approves
one (APPROVE) or throws it out (REJECT). Twiney can also type a line of his own: his are approved as he writes them.

When the desk speaks a call it rotates through the built-in line and the APPROVED versions only, the numbers filled
in. A version that is missing a number, names one the call does not have, or uses a word off the language list is
refused before it is ever shown. The list lives in recordings/phrases.json.
"""

import json
import os
import re
import string
import threading
import time

# the calls the voice says, the numbers each one carries, and the desk's own line
KINDS = {
    "level.took": {"name": "A LEVEL TAKEN (held 5 minutes)",
                   "fields": ("who", "level", "price", "ago", "last"),
                   "default": "{who} took {level} at {price} {ago} and they're holding it. Price {last}"},
    "level.strong": {"name": "10 MINUTES LATER: STRONG",
                     "fields": ("who", "level", "price", "ago", "last", "away", "side"),
                     "default": "{who} took {level} at {price} {ago} and it's strong: it never came back to it. Price {last}, {away} {side} it"},
    "level.holding": {"name": "10 MINUTES LATER: HOLDING",
                      "fields": ("who", "level", "price", "ago", "last", "away", "side"),
                      "default": "{who} took {level} at {price} {ago} and they're holding it: price came back to test it and held. Price {last}, {away} {side} it"},
    "level.not_strong": {"name": "10 MINUTES LATER: NOT STRONG",
                         "fields": ("who", "level", "price", "ago", "last", "side", "back", "times"),
                         "default": "{who} took {level} at {price} {ago}. Still {side} it, but not strong: it dipped back {back} it {times}. Price {last}"},
    "level.lost": {"name": "10 MINUTES LATER: LOST",
                   "fields": ("who", "level", "price", "ago", "last", "back"),
                   "default": "{who} took {level} at {price} {ago} and lost it: price is back {back} it. Price {last}"},
    "level.rejected": {"name": "REJECTED AT A LEVEL",
                       "fields": ("level", "price"),
                       "default": "Rejected at {level}, {price}. Sellers defending it, pulling off"},
    "level.bounced": {"name": "BOUNCED OFF A LEVEL",
                      "fields": ("level", "price"),
                      "default": "Bounced off {level}, {price}. Buyers defending it, pulling off"},
    "flow.hit": {"name": "ONE OPTION PRINT JUST HIT",
                 "fields": ("premium", "symbol", "strike", "what", "expiring"),
                 "default": "{premium} just hit {symbol} {strike} {what}{expiring}, buyers paid up"},
    "flow.again": {"name": "THE SAME STRIKE AGAIN",
                   "fields": ("premium", "symbol", "strike", "what", "expiring", "count", "minutes"),
                   "default": "{premium} just hit {symbol} {strike} {what}{expiring} again, {count} times on this strike in {minutes} minutes"},
    "flow.hammered": {"name": "CALLS / PUTS GETTING HAMMERED",
                      "fields": ("what", "count", "minutes", "premium", "strike"),
                      "default": "{what} getting hammered, {count} prints in {minutes} minutes, buyers paid up on all of them. This one, {premium} at the {strike} strike"},
}

# the words that never go on the screen or in the voice (THE LANGUAGE RULE and Twiney's own words)
FORBIDDEN = [r"\bresistance\b", r"\bsupport\b(?! the)", r"\btrigger", r"\biceberg", r"\bdark[ -]?pool", r"\bstack(s|ed|ing)?\b",
             r"\bdoor\b", r"\bbox\b", r"\bzones?\b", r"\bribbon\b", r"\bfading\b", r"\bstale\b", r"\bgone\b",
             r"\bfailed break", r"\border blocks?\b", r"\bfair value gap", r"\bliquidity sweep", r"\bsmart money\b",
             r"\brsi\b", r"\bmacd\b", r"\bfibonacci\b", r"\bfib\b", r"\b(have|has|own|owns) the tape\b",
             r"\blift(ing|ed)? the offer\b", r"\bhit(ting)? the bid\b", r"\bat the ask\b", r"\bat the bid\b"]
_FORBID = [re.compile(x, re.I) for x in FORBIDDEN]

RULES = """TWINEY'S WORDS (use them, never anything else):
- Buyers / sellers first; "the bulls" / "the bears" only now and then.
- Who leads: "buyers are in control", "sellers are in control", "neither side is in control". Never "have the tape".
- "buyers are paying higher prices to get in", "sellers are accepting lower prices to get out"; on the tape: "buyers paid
  up", "sellers sold down". Never "at the ask", "at the bid", "lifting the offer", "hitting the bid".
- PS60 words only: supply, demand, pivot, confirmation, second entry, build, measured potential, runner, reload buyer,
  reload seller, the levels by their names. Never: resistance, support, trigger, zone, box, stack, door, ribbon, fading,
  stale, gone, failed breakout (say "price hit supply"), RSI, MACD, Fibonacci, order blocks, dark pool (say large orders).
- Option flow names the one print that hit, never a total.
- Short, spoken, plain: one or two sentences a trader can hear in three seconds."""


def placeholders(text):
    try:
        return {f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f}
    except ValueError:
        return None


def check(kind, text):
    """None when the line can be spoken, else why not."""
    k = KINDS.get(kind)
    if not k:
        return "no such call"
    text = str(text or "").strip()
    if not text or len(text) > 300:
        return "empty or too long"
    ph = placeholders(text)
    if ph is None:
        return "a { or } that is not a number's place"
    need = placeholders(k["default"])
    extra = ph - set(k["fields"])
    if extra:
        return "names a number this call does not have: " + ", ".join("{" + x + "}" for x in sorted(extra))
    miss = need - ph
    if miss:
        return "leaves out " + ", ".join("{" + x + "}" for x in sorted(miss))
    for rx in _FORBID:
        m = rx.search(text)
        if m:
            return f'uses "{m.group(0)}" (not one of Twiney\'s words)'
    return None


class Phrases:
    def __init__(self, path=None, cfg=None):
        self.path = path
        self.cfg = cfg or {}
        self.lock = threading.Lock()
        self.data = {}              # kind -> [{"id", "text", "status", "by", "t"}]
        self.turn = {}              # kind -> rotation counter
        self.n = 0
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.data = {k: v for k, v in (json.load(fh) or {}).items() if k in KINDS and isinstance(v, list)}
                self.n = max([int(x.get("id", 0)) for v in self.data.values() for x in v] + [0])
            except (OSError, ValueError):
                self.data = {}

    @property
    def on(self):
        return (self.cfg.get("phrases") or {}).get("use_approved", True)

    def _save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def add(self, kind, text, by="twiney", status=None):
        """A new line: Twiney's own are approved as written, the AI's wait as PENDING. Returns (line, why_not)."""
        text = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip()
        why = check(kind, text)
        if why:
            return None, why
        with self.lock:
            rows = self.data.setdefault(kind, [])
            if any(r["text"].lower() == text.lower() for r in rows) or text.lower() == KINDS[kind]["default"].lower():
                return None, "already on the list"
            self.n += 1
            row = {"id": self.n, "text": text, "status": status or ("approved" if by == "twiney" else "pending"), "by": by,
                   "t": round(time.time())}
            rows.append(row)
            self._save()
        return row, None

    def add_ai(self, kind, answer):
        """The AI's answer: one version per line (numbering and bullets taken off). Returns (added, refused)."""
        added, refused = [], []
        for ln in str(answer or "").splitlines():
            ln = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip()
            if not ln or "{" not in ln:
                continue
            row, why = self.add(kind, ln, by="ai")
            (added if row else refused).append(row or {"text": ln, "why": why})
        return added, refused

    def set_status(self, kind, lid, status):
        if status not in ("approved", "rejected", "pending", "removed"):
            return False
        with self.lock:
            rows = self.data.get(kind) or []
            for r in rows:
                if r["id"] == int(lid):
                    if status == "removed":
                        rows.remove(r)
                    else:
                        r["status"] = status
                    self._save()
                    return True
        return False

    def approved(self, kind):
        return [r["text"] for r in self.data.get(kind) or [] if r["status"] == "approved"]

    def pick(self, kind, fields, default):
        """The line to speak: the built-in one and the APPROVED versions, in turn, the numbers filled in."""
        if not self.on:
            return default
        lines = self.approved(kind)
        if not lines:
            return default
        i = self.turn.get(kind, 0)
        self.turn[kind] = i + 1
        choice = ([None] + lines)[i % (len(lines) + 1)]
        if choice is None:
            return default
        try:
            out = choice.format(**{k: fields.get(k, "") for k in KINDS[kind]["fields"]})
        except (KeyError, IndexError, ValueError):
            return default
        return out[:1].upper() + out[1:]

    def view(self):
        with self.lock:
            return {"use_approved": self.on, "rules": RULES,
                    "kinds": [{"kind": k, "name": v["name"], "fields": list(v["fields"]), "default": v["default"],
                               "lines": [dict(r) for r in self.data.get(k) or [] if r["status"] != "rejected"],
                               "rejected": sum(1 for r in self.data.get(k) or [] if r["status"] == "rejected")}
                              for k, v in KINDS.items()]}
