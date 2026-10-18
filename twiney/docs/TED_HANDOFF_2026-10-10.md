# TED — Twiney's Execution Desk. Complete handoff, 2026-10-10

For the next AI agent working with Twiney on this system. Read all of it before touching anything. The first thing to
read after this file is `CLAUDE.md` at the repo root and `.claude/skills/ps60-language/SKILL.md`: the language rule
there is absolute.

Branch: `claude/twiney-v1-complete-gdn0ws` on `antoineriley1-debug/pmwatch`. Last commit at the time of writing:
`255654a` (DESK AI: MY TRADES). Version `3.3.0`, build stamp `20261010-0151`. 325 commits, 55 test files, 769 tests,
all passing. About 34,700 lines across Python and the page.

---

## 1. What TED is, in one paragraph

A local trading desk for one trader, Twiney, who trades Dan Shapiro's PS60 method (Access A Trader) with options on
beta names (AMD, TSLA, NVDA, AAPL, SOFI, PLTR and the like). It runs on his Windows laptop as one Python program
(`run_twiney.py`) serving one browser page at `http://127.0.0.1:8765`. Market data and orders go through Interactive
Brokers Trader Workstation (TWS API, paper port 7497). Option flow comes from Quant Data's REST API. The voice is
ElevenLabs or the browser. A local Ollama model (DESK AI) reads the desk's records after the fact. Nothing is hosted
and nothing leaves the laptop except the calls to IBKR, Quant Data and ElevenLabs.

Everything on the desk is structured around PS60: Daily room → 60-minute pivot (or sneaky pivot) → confirmation →
second entry → build → pay yourself → runner to measured potential. Option flow supports a pivot thesis and never
replaces it.

---

## 2. The rules Twiney has set (never break these)

1. **THE LANGUAGE RULE.** Every word about stocks or the market, in chat, code, names, comments, docs, the voice, the
   alerts and the DESK AI, is a PS60 word. Allowed and forbidden lists are in `CLAUDE.md`. Twiney's own words on
   wording override everything. When you find a wrong word, replace it everywhere, rebuild, test, tell him it was
   there, never defend it. He has thrown out "iceberg", "trigger", "stale", "fading", "gone", "support",
   "resistance", "dark pool" and "zone"-style inventions already. "Rising 60-minute support" is the one allowed
   use of support.
2. **Do not incorporate your own method into his strategy.** No new indicators, no renamed concepts, no modules
   Dan did not teach. If PS60 has no word for a thing, say it in plain English with the PS60 words around it.
3. **All settings live in SETTINGS** on the desk (the gear). Nothing is tuned by editing files.
4. **Paper first.** The desk refuses live order entry unless `trading.allow_live` is on; keep it off.
5. **Secrets never go into git.** The Quant Data key and the ElevenLabs key live only in his private
   `config.json`, which is added to the private zip after `git archive`. Never commit it, never print it.
6. **Never put a model identifier** in a commit message, PR, code or doc.
7. **Test everything as implemented**, visually and functionally: unit tests, then a Playwright probe against the
   running practice desk, then a screenshot he can see. Report outcomes plainly, failures included.
8. **Deliver as a zip** (`TWINEY.zip` = `git archive` of `twiney/` + his `config.json`) after each change, and tell
   him the BUILD stamp on the status bar so he can confirm he is on it.
9. Commit footer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and the session link. Commit and push
   to the branch above. Never open a PR unless he asks.

---

## 3. How to run, build, test, ship

```
cd twiney
python3 run_twiney.py                       # live / paper: TWS running with the API enabled
python3 run_twiney.py --demo                # practice: synthetic market, simulator fills, no IBKR
python3 run_twiney.py --replay recordings/<file>.jsonl --speed 5   # a recorded day, with training questions
python3 page_src/build_page.py              # page sources -> twiney/static/dashboard.html (BUILD stamp = UTC time)
python3 -m unittest discover -s tests       # 769 tests
```

The page is built from `page_src/dashboard_old.html` (the chart and the older core), `desk_core.js` (layout, docking,
panels), `desk_panels.js` (every panel's renderer), `desk_pool.js` (panel names, presets), `desk_body.html` (panel
markup), `desk.css`, `skin.css`. Edit the sources, never `static/dashboard.html`. The page reloads itself when the
server's BUILD is newer than its own.

Practice desk for probes: `python3 run_twiney.py --demo --config <cfg> --plays <plays> --port 8799 --no-browser`,
then a Playwright script (Chromium at `/opt/pw-browsers/chromium` in the cloud container). Twiney's zip:
`git archive --format=zip --prefix=TWINEY/ -o TWINEY.zip HEAD twiney` then `zip TWINEY.zip TWINEY/twiney/config.json`
from the folder that holds his private config.

Windows launchers: `start_twiney.bat` (paper / live), `start_demo.bat` (practice).

---

## 4. Architecture

```
IBKR TWS  ──TWS API──▶  ibkr.py (MarketDataSession)  ──▶  engine.py (Engine)  ──▶  dashboard.py (HTTP + SSE)  ──▶ the page
Quant Data ─REST─────▶  flow.py (QuantDataFeed)      ──▶  engine.flow (FlowBook)        │
sim.py (DemoFeed) ───▶  engine (practice)            ◀──  trading.py (Trader, gates) ◀──┘ orders from the page
ElevenLabs ◀─tts.py──  the voice                        recorder.py / replay.py / desk.py (journal) / ai.py (DESK AI)
```

**engine.py (5,690 lines)** is the heart. One `Engine` holds a `SymbolState` per ticker (`st`): the Level 1 quote,
the book (`book.py`, IBKR depth operations INSERT / UPDATE / DELETE per row), the tape (`tape.py`, tick-by-tick
prints), minute bars, daily bars from IBKR, the play (Twiney's lines), the story book, the reload trackers
(`levels.py`), pace, institutional footprints, large orders, and the per-price memory ladder rows. `tick(t)` runs
once a second: the clock, pace, levels, the story, THE DESK SCORE, the DESK AI's minute tick, slot rotation.
`snapshot(t)` builds the JSON the page polls (about four times a second) and `_pane(sym)` the per-ticker slice.
A lock (`engine.lock`, RLock) guards state; studies and the story compute off the lock.

**Key engine pieces:**
- `aggressor()`: a print at the offer is a lift, at the bid a hit; a print outside the market is read against the
  quote in force in the last second, else by the tick rule. IBKR prints carry no side, so every "bought / sold" is
  inferred. Unreadable prints count only in TRADED.
- `PullBook` (`conviction.py`): a drop in displayed size is judged on the next quarter-second read against the
  prints that landed there: the traded part is FILLED, the rest waits one second for a re-quote, then PULLED.
  Never an execution from a depth drop alone.
- `PrintGuard`: prints keyed by IBKR time + price + size + exchange + ordinal; a re-delivery after a reconnect is
  ignored (`new_connection()` on CONNECTED).
- Reload trackers (`levels.py`): a buyer on the bid or seller on the offer who keeps refilling while size prints
  into him. Stages: RELOADING → STILL THERE → NOT RELOADING → CLEANED UP or PULLED; BACK ×N when he returns.
  Conviction floors in SETTINGS › Reload detection.
- `key_levels(st, t)`: PDO / PDH / PDL / PDC, PMH / PML / PMC, AHH / AHL / AHC, OPEN, VWAP, D50, HOD / LOD, the
  daily REJECT / BOUNCE lines (AIRSPACE), prior highs and lows not revisited. One registry for the chart, the
  ladder rail and the story.
- Depth slots: IBKR allows 3 simultaneous books per login (more with four or more Quote Booster packs). The desk
  uses `depth.slots` (3), the on-screen ticker always gets one, the option Level II takes one when on. A refused
  book is said with IBKR's code (309 too many lines, 10092 no SMART depth) on the ladder header, in MESSAGES and
  in `recordings/desk.log`.

**story.py (2,139 lines)** is the PS60 read of one stock as one running story: `daily_context` (above / below the
50-day, the objective = prior-day high or low), the places price can react (`ps60_points`, zones, confluence), the
attention band (on / near / approaching a place), the lean of the tape (`tape_lean`: sellers have the tape / buyers
have the tape / neutral, with the reasons: levels taken, new low or high of day, lower highs and lows, under PDL /
over PDH, puts or calls at the ask; holds `lean_hold_minutes`), the day's regime (`day_regime`: down / up / chop,
judged 45 minutes in against ATR), the attempts (`attempts`: buyers or sellers trying to take a level back, outcome
TOOK or FAILED), the option flow state (NOT YET CONFIRMED / DEVELOPING / CONFIRMED / CONFLICTING), the play-by-play
and the coach lines ("stay patient", "be careful, he is still there"). Every turn of the storyline goes to
`recordings/storylines.jsonl` on live days for the cross-day study.

**pace.py**: shares per second against the stock's own last 20 minutes (SURGE / FAST / NORMAL / SLOW / DRYING UP),
buy %, drift and `control` over the 15-second window, `bp_suspect` (a raw buy % that disagrees with price drifting
the other way: the fix for "buyers stepping up" in a sell-off), the calls at the levels: STALLING INTO, PRESSING,
BREAKOUT / BREAKDOWN WITH SPEED, BREAK WITHOUT SPEED, + FLOW.

**ps60.py**: the second-entry engine (break pivot → new extreme → retrace → back through it, always on a new candle;
1- or 5-minute trigger candle), MP against ATR (CLEAR / THIN), sneaky pivots (≥ 2 candles, inset, tight vs ATR, with
MP), grade READY / WATCH / PASS. **board.py / conviction.py**: the conviction board, lanes L0 Daily MP … L7
correlation, chart gate AND flow gate, READY only when both are green. **studies.py**: GAS + ATR, AIRSPACE,
UNVISITED HIGHS / LOWS (Pine-exact), session levels, the New York clock helpers (`ny`, `day_key`, `ny_secs`).

**flow.py**: Quant Data option prints (symbol, premium, expiry, strike, C / P, spot, side, sweep / block, OTM %),
the FlowBook, SOMEBODY KNOWS SOMETHING (short-dated OTM at the ask, again and again), urgency, equity prints,
`SimFlow` for practice. **bigmoney.py**: 30-day memory of prints over the premium floor, judged against spot now.
**dark.py**: large off-exchange orders (FINRA / TRF / ADF), called LARGE ORDERS. **inst.py**: a fund's sliced order
(VWAP / % of volume programs, fund-style reloaders, a side walking the price). **breaktrap.py / levelverdict.py /
levelwatch.py**: level breaks and comebacks, who got caught, BUYERS TOOK / SELLERS TOOK / BOUNCED / REJECTED /
DEFENDED / RECLAIMED / LOST with a follow-up call.

**trading.py (3,265 lines)**: `TradingGate` (paper-only lock, caps per order and per day, rate limit, ARM, the day
loss lock), `Trader` (limit-only tickets, brackets, OCA, the scale plan MP / CASH FLOW / BUILD / custom rungs,
auto second entry = stop-limit entry with stop and target when the 2nd entry line is drawn, option orders with a
backup stop at IBKR, breakeven after cash flow, the 5-minute max-pain stop for contracts), `SimBroker` for
practice. Three audit rounds of order defects are recorded in the commit history; `tests/test_order_audit.py`,
`test_orders_safety.py`, `test_scale_plan.py` guard them.

**options.py / optbook.py**: the chain from IBKR (expiries, strikes, quotes, Greeks), the option Level II and T&S,
the practice chain after hours (SIM light), `fits_side` (a contract must match the play's side), `practice_expiries`
rolls to next week from Friday noon ET.

**scorecard.py**: THE DESK SCORE. Every call with a direction (second entry live, CLEANED UP, a level taken on a
close, breakout with speed, a program, calls / puts pounded, the open read) is judged 5 and 15 minutes later: HIT
(moved ≥ `score.hit_atr` × ATR the call's way), MISS, FLAT. `recordings/score.jsonl`. **training.py**: replay
training: the replay pauses on a call, asks you long / short / wait (keys L / S / W), grades you against what
happened. `recordings/training.jsonl`.

**desk.py**: the journal. Round trips built from fills (each execution counted once), the plan the trade was taken
against (pivot, 2nd entry, stop, target), result WIN / LOSS / SCRATCH, R against the planned stop, the plan's R:R,
the trade log, mic transcript, marks and screenshots; `recordings/trades.jsonl`, one markdown file per trade under
`recordings/journal/`, CSV export; session journals `*.journal.md`; ★ flags on good sessions; clips.

**recorder.py / replay.py**: every event (quotes, depth ops, prints, alerts, ticks, notes, marks, trades) as JSON
lines, one file per session; replay rebuilds the engine from them at any speed with a scrubber, clips, markers.

**ai.py + knowledge/ps60.md**: DESK AI (section 7).

**dashboard.py**: `ThreadingHTTPServer`, local-only (Host / Origin checks against DNS rebinding), `/api/state`
(cached snapshot, per-ticker `full` history on demand), `/api/stream` (SSE frames for the on-screen ticker),
`/api/settings` (schema + apply + restart), `/api/trade/*`, `/api/play`, `/api/level`, `/api/ladder`, `/api/replay`,
`/api/desk/*` (recording, marks, mic audio, journal, clips), `/api/tts`, `/api/ai/*`, `/healthz`.

**settings.py**: every leaf of `config.DEFAULTS` becomes a field; the help text is read from the comments in
`config.py` so it cannot drift; sections, labels, choices, secrets (masked), restart-only keys, the VOICE section
that gathers every "say it" switch. **config.py (1,062 lines)**: DEFAULTS with the comments that are the help,
validation (`_check_values`, POSITIVE), plays validation, `_opt_link_ok`.

**sim.py**: the practice market: a random walk with day types (trend up / down, chop, capitulation, squeeze), a
book with participants of different styles (fund-style large size that shows the same small amount every refill,
blocks, a VWAP algo, large off-exchange prints), prints, the simulated option chain. Its numbers test the
plumbing, never the market.

**tts.py**: ElevenLabs (key + voice ID, cached phrases on disk) or the browser's voice; `names.py` says company
names, never tickers.

---

## 5. The page

Docking layout: four columns × two rows of zones (TL TC TR TX / BL BC BR BX), panels dock, float, split, resize
with grips; named layouts and presets ("PS60 Execution", "Stock + Options", "Scalping", "Tape Focus", "Chart Focus",
"Options Desk", "Laptop"). A new panel docks itself once (`NEW_PANELS` in `desk_core.js`).

Panels: CHART (×3), OPTION CHART, LEVEL II (the DOM), OPTION LEVEL II, TIME & SALES, OPTION T&S, BIG TAPE, OPTION BIG
TAPE, FOOTPRINT 5m, OPTION CHAIN, PLAY SETUP, PS60, CONVICTION, PS60 STORY, DESK SCORE, DESK AI, RELOADS, ORDER ENTRY,
POSITIONS, ORDERS, WATCHLIST, CALLS, OPTION FLOW, EQUITY FLOW, URGENT FLOW, BIG MONEY 30D, ALERTS, DESK, JOURNAL,
MESSAGES. The TRAPS box floats small. The status bar carries ARM / PRACTICE, REC, MARK / SNAP / MIC / CLIP, TRAIN,
the LEDs (FEED / DATA / ORDERS), LADDERS n/3, DAY LOSS LIMIT, MKT / OPT lights, BUILD, latency, the ET clock.

**The LEVEL II (Twiney's Precision Level 2, the DOM)**: WAITING BUYERS · ACTUAL SELLING · LEVELS rail · PRICE ·
ACTUAL BUYING · WAITING SELLERS · TRADED, optional $ HERE. Bars ease to size in 160 ms, a cell pulses once when a
print lands, a print drops its dollars (or shares) into the row, the reload cluster ↻N sits in the rail, the data
header says LIVE / DELAYED / PRACTICE / REPLAY / DISCONNECTED and SMART DEPTH / ONE EXCHANGE'S BOOK / NO BOOK with
ages, FEED OLD and REFUSED. Nothing sits above the rows but that header unless COLS › "strips above the rows" is on.
The footer strip reads the inside quote in words ("ASK 615.01 · 1,200 sitting · +700 came in · 2,400 bought from it
· 2,700 pulled"). Modes DOM / CANDLE / CLEAN / PRO; the basket and pot ladders are retired from the cycle.
Report: `docs/PRECISION_LEVEL2.md`.

**The chart**: Dan's moving averages and Bollinger with his hex colours (`docs` and the Pine locks), the Daily-only
34 / 65 / 89 EMAs, VWAP, GAS + ATR (hidden automatically on Daily and weekly), AIRSPACE, UNVISITED HIGHS / LOWS, the
key levels, the play's lines drawn by MARK or right-click and dragged, working orders, fills, the option flow marks
(the strikes the money bought, at the stock price where each print hit, with how far the contract moved: Twiney
likes these, keep them), candle hand-off across timeframes.

---

## 6. What is on disk (the data folder)

`config.json` (private), `plays.json` (the tickers and their lines), `alerts.json`, `layout.json` / `layouts.json`,
`history/` (IBKR bar cache), `voice_cache/`, `recordings/`: `twiney-*.jsonl` and `demo-*.jsonl` sessions,
`*.journal.md`, `*.marks.jsonl`, `shots/`, `clips.jsonl`, `grades.jsonl`, `trades.jsonl`, `journal/`,
`score.jsonl`, `training.jsonl`, `storylines.jsonl`, `inst_calib.jsonl`, `big_money.jsonl`, `desk.log` (JSON lines:
connections, orders, fills, errors, refused / reset / rotated books), `ai/` (every DESK AI answer with what it was
given).

---

## 7. DESK AI (Ollama), the newest piece

`twiney/ai.py`, `twiney/knowledge/ps60.md`, `docs/DESK_AI.md`. A local Ollama model (default `llama3.1:8b`, `llama3.2:3b`
quicker on a laptop), off by default, SETTINGS › AI (Ollama). Never in the live read: nothing it writes becomes a
call, a voice line or a trade. Before it reads a number it is given the knowledge file: PS60 the way Dan teaches
it plus the desk's own words. Jobs, one at a time off the desk's threads, every answer saved under `recordings/ai/`
with everything the model was given, the language lock applied to its words:

- RECAP + TOMORROW: the day per stock (Daily context, levels taken, reloads, 60-minute candles, flow, THE DESK
  SCORE, notes, fills, P&L) and tomorrow's plan per stock (bias, the levels in order, the long and short pivot with
  what confirms it, the second-entry structure to wait for, MP vs ATR, max pain, what makes it a PASS). Runs on its
  own at 16:05 ET on a connected day.
- EXPLAIN: why the desk said what it said on the ticker on screen.
- CLEAN NOTES: typed and mic notes into a clean journal.
- STUDY DAYS: the storyline and the score over the recorded days.
- MY TRADES: every closed round trip graded against PS60 (setup, entry type, management, verdict), the patterns,
  three rules to carry.
- ASK: a question about today.

Status line: READY / WRITING / OFF / OLLAMA NOT ANSWERING / MODEL MISSING (with the pull command). Tested against a
stand-in Ollama only: **no real model has written a recap yet** (the cloud container cannot run one).

---

## 8. Honest state of each subsystem

| piece | state | confidence |
|---|---|---|
| IBKR connection, quotes, tick-by-tick tape, depth, history | built, three audit rounds on the adapter, verified on paper by Twiney in September / early October | high |
| Order entry, brackets, scale plan, option orders, safety gates | built, 13 + 13 audited defects fixed, 100+ tests | high on paper; live never exercised |
| The DOM (Level II) and its truth layer | built to the handoff spec, 9 scenario tests, 4-viewport probes | high on plumbing; aggressor side is inferred |
| Reload buyer / seller detection | built, tuned on practice and a few live complaints | medium: thresholds are first guesses |
| The story: lean, regime, attempts, attention, play-by-play | built after Twiney's complaints (false "buyers stepping in", "sitting on PDL" when well below, flip-flopping sides) | medium: never graded on real days |
| Pace and level calls | built | medium |
| Option flow, conviction board, NO FLOW NO DOUGH | built against the board SoT; depends on Quant Data's endpoint | medium-high |
| THE DESK SCORE, replay training | built, small | medium |
| Journal, recordings, replay, clips, mic notes | built, used by Twiney | high |
| Chart studies (GAS + ATR, AIRSPACE, UNVISITED) | Pine-exact, tested against reference values | high |
| Voice (ElevenLabs) | built; browser fallback | high |
| DESK AI | built, tested against a stand-in | medium: untested with a real model |
| Practice market | rich, but synthetic | n/a |

Overall I rated the framework 7 / 10 to Twiney: strong bones, one theory throughout, server-side accounting,
honest about what it does not know; held back by readings never graded on real recorded days, inferred print
sides, no cross-day storyline yet, and a Level II that can show a lot at once.

---

## 9. What needs improvement, in priority order

1. **Grade the readings on real days.** Nothing in the story, the lean, the regime, the attempts or the reload
   thresholds has been judged against a real recorded session. Plan: two weeks of paper with recording on every day,
   then DESK SCORE by call type, then cut or retune anything under about 55 % hit rate. The thresholds are in
   SETTINGS › PS60 story (`lean_min`, `lean_hold_minutes`, `lean_neutral_minutes`, `lean_flow_min`,
   `attempt_minutes`, `regime_trend_atr` 0.45, `regime_chop_atr` 0.35) and SETTINGS › Reload detection.
2. **The cross-day storyline study** needs 10 to 20 recorded live days in `storylines.jsonl`; STUDY DAYS and the
   bias-carrying logic were written before any real day existed.
3. **Aggressor side.** IBKR prints carry no side; on a fast tape the quote-in-force read misclassifies some
   prints. The `bp_suspect` guard hides the worst of it. A better read would use the IBKR `tickByTickAllLast`
   past-limit flags and the exchange field; worth a study against recorded days.
4. **DESK AI with a real model.** First real recap on Twiney's laptop will show whether 8B writes well enough and
   how long it takes; the asks may need tightening; the packet is sized for an 8k context with six stocks.
5. **Level II optimisation** (on Twiney's list, his words): the DOM is dense for a beginner. Ideas he has not
   decided on: hide the ×N visit superscripts behind hover, fewer columns by default for the first week, a larger
   text preset. Do nothing here without asking him.
6. **Depth slots.** With 3 books per login the desk rotates; if he buys four Quote Booster packs, raise
   `depth.slots`. Slot allocation should be checked the next time he sees NO BOOK on the on-screen ticker (get the
   code from `desk.log`).
7. **Reload thresholds on real names.** `real_min_shares` 2000, `requote_seconds` 1.0, the conviction floors: all
   practice-tuned.
8. **The PS60 handoff documents in his uploads** (`PS60_HANDOFF_FOR_CLAUDE_COLE.md`, the option flow board, the
   chart colour lock) were used for the AI's knowledge and the board; a line-by-line audit of the desk against the
   handoff's acceptance tests (§16) has not been done.
9. **Language sweep.** The forbidden words were swept out of source on 2026-10-10. The compiled page
   `static/dashboard.html` is rebuilt from the sources, so it is clean too, but every future change must be grepped
   before it ships (`grep -rniE "resistance|iceberg|dark pool|trigger"` across `twiney/`, `page_src/`, `docs/`,
   `tests/`; "trigger" survives only as the play's internal key `trigger` for the pivot line, which is data, not
   words on screen; renaming that key would touch plays.json and the recordings, so it was left). The feed-health
   status value `STALE` in the engine (`health.l1_stale_seconds`) is a data word, not a market word; it is no longer
   shown on the DOM header (FEED OLD), but the LEDs' status code still carries it internally.
10. **Lag.** IBKR → TWS → desk → browser is about a quarter to half a second on the on-screen ticker (SSE) and up to
    a quarter second more for the other panels (polling). Fine for PS60; not for racing the spread.
11. **Tests are slow-ish** (the launch test starts a desk in a subprocess); the full suite is about two minutes.

---

## 10. Things Twiney has said that shape every decision

- "Everything must be structured around the PS60 theory."
- "You need to make this flawless so that this doesn't happen" (a persisted contract link flipped a play's side;
  fixed: a contract must fit the play's side, a new pivot clears the link, no link survives a restart).
- "It has to take a side, or say neutral" and "hold that tone until something changes it within the data":
  the lean holds for `lean_hold_minutes` and only the data flips it.
- "After the levels have been lost, say that the other side is trying": `buyers are trying` / `sellers are trying`.
- "Put on your list to optimize the Level II. Don't do it right now."
- "I don't use icebergs. That is not the PS60 strategy. Do not incorporate your own bullshit into my strategy."
- "You're forbidden to speak about anything pertaining to stocks or the market with any other kind of terminology
  outside of PS60 theory." (now `CLAUDE.md` + the skill)
- He likes: the option flow marks on the stock chart with the contract's move, the DOM's footer line in words,
  the dollar drops into $ HERE, the clean black desk.

---

## 11. First things to do in a new session

1. Read `CLAUDE.md`, the ps60-language skill, this file, `docs/PRECISION_LEVEL2.md`, `docs/DESK_AI.md`,
   `docs/PS60_OPTION_FLOW_CONVICTION_BOARD.md`.
2. `python3 -m unittest discover -s tests` must be green before and after your change.
3. Ask Twiney for the BUILD stamp on his status bar before diagnosing anything he sees; he is often on an older zip.
4. When he reports a wrong reading, ask for the recording file name and the ET time; the answer is in the
   recording, not in guesses.
5. Ship: tests → page build → practice-desk probe with a screenshot → commit → push → zip with his config → tell
   him the BUILD.
