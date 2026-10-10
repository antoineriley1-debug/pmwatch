# TED — Twiney's desk. Rules that never change.

## THE LANGUAGE RULE (utmost importance, no exceptions)

Anything said, written, coded, named, commented, documented, spoken by the voice, or taught to the DESK AI about
stocks or the market is said in **PS60 words only**, the way Dan Shapiro (Access A Trader) teaches it. Nothing from
any other school, book, indicator set or trading vocabulary is ever added. Read `.claude/skills/ps60-language/SKILL.md`
before touching anything that talks about the market. This holds for chat replies to Twiney too.

- Allowed: supply, demand, pivot, confirmation, second entry, build, measured potential (MP), ATR, cash flow, runner,
  max pain, remount, bounce, rejection, sneaky pivot, macro channel, micro channel, option flow, reload buyer,
  reload seller, RELOADING, STILL THERE, NOT RELOADING, CLEANED UP, PULLED, large orders, large size, the 50-day,
  VWAP, prior-day high / low / close, premarket and after-hours high / low, high / low of day, the open.
- Forbidden, ever: resistance, support (one allowed phrase: "rising 60-minute support"), trigger (say pivot),
  iceberg, dark pool (say large orders), stack, door, box, zone, ribbon, fading, stale, gone, "into supply is not
  MP", order blocks, fair value gaps, liquidity sweeps, smart money concepts, RSI / MACD / Fibonacci, any invented
  module name. A failed breakout is "price hit supply" (or demand).
- If a thing has no PS60 word, describe it in plain English with the PS60 words around it. Never borrow a word.
- Twiney's own instructions on wording override everything else, always.

## Other standing rules

- Everything is structured around the PS60 theory: Daily room → 60-minute pivot (or sneaky) → confirm → second
  entry → build → pay yourself → runner to MP. Flow supports, never replaces.
- All settings live in SETTINGS. Paper first. Verify visually and functionally; test everything as implemented.
- The Quant Data key and the ElevenLabs key go only into the private zip, never into git.
- Never put a model identifier in a commit, a PR, code or a doc.
- Build the page with `python3 page_src/build_page.py`; tests with `python3 -m unittest discover -s tests`.
