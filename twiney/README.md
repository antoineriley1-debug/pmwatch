# TWINEY v1.7

An IBKR order-flow workstation built around PS60 levels, with ladder trading that is
**locked to paper accounts** until you deliberately unlock it.

## Trading from the ladder (paper only)
- **ARM** in the header. TWINEY starts DISARMED every launch; nothing can be sent until you arm it.
- Click **BUY** on any ladder row to place a limit buy at that price; **SELL** likewise. Or use the
  trade bar: **BUY bid** / **SELL ask** at the current quote, **Flatten**, **Cancel all**.
- A confirmation box shows size, price, dollar value and the stop/target legs (Enter sends, Esc cancels).
  Tick **one-click** to skip it.
- **stop+target** (on by default) attaches the play's `stop` and `target` from `plays.json` as a bracket:
  when the entry fills the exits go live; when one exit fills the other is cancelled.
- Your working orders show as chips on the ladder rows (click a chip to cancel), as lines on the chart,
  and in the orders panel below.
- **Locks (config.json → trading):** `allow_live` is false, so a live account (id not starting with `DU`)
  can never receive an order; `max_shares_per_order` (500), `max_dollars_per_order` ($25,000) and
  `max_orders_per_minute` (10) reject anything bigger; only LIMIT entries are possible.
- **Practice without IBKR:** `start_demo` runs a built-in simulator that fills your orders against the
  demo book, so you can learn the ladder today.
- **Paper account with real data:** log TWS into your paper account (`DU…`), untick "Read-Only API" in
  TWS API settings, and run `start_twiney`. The header shows **PAPER account**.

## Quick start (double-click)
- **Windows:** `start_demo.bat` to try the demo, `start_twiney.bat` to connect to TWS.
- **Mac:** `start_demo.command` / `start_twiney.command` (first time: right-click → Open).

The launchers create `config.json` and `plays.json` from the examples if they are missing. You still need Python and IBKR's `ibapi` package (steps 3–4 below).

## Workflow
All commands run from this `twiney/` folder.

1. `cp plays.example.json plays.json`, then put in your PS60 plays. The example prices are placeholders. `pivot` is the
   60-minute pivot (the old `trigger` key still works); `second_entry` is optional and sits **beyond** the pivot (the new high after a long break, the new low after
   a short break) — leave it out and TWINEY finds it once the pivot breaks. `mp` and `atr` are your numbers from the chart.
2. `cp config.example.json config.json`, then set the port: 7497 for TWS paper, 7496 for TWS live, 4002 for Gateway paper, 4001 for Gateway live.
3. Install IBKR's official TWS API Python package so `ibapi` is available. Download the TWS API from IBKR, then run `python -m pip install .` inside `source/pythonclient`. The `ibapi` package on PyPI is an old 9.x build, so don't use it.
4. Start TWS or IB Gateway. In the API settings, enable socket clients. Leave "Read-Only API" ticked
   unless you want to trade from the ladder (paper account). Make sure your account has market-data permissions, including depth.
5. `python run_twiney.py`
6. The dashboard opens at `http://127.0.0.1:8765` and only binds to loopback.

Other modes:

| Command | What it does |
|---|---|
| `python run_twiney.py --demo` | Synthetic feed with no IBKR connection. It is labelled DEMO everywhere and records to `recordings/demo-*.jsonl`. |
| `python tune.py recordings/X.jsonl` | Fits the reload thresholds to the calls you graded 👍 / 👎 |
| `python run_twiney.py --replay recordings/X.jsonl` | Re-runs a recording and compares its calls with the ones made live |
| `... --replay X.jsonl --speed 5` | Paced replay (5x) with the dashboard |
| `... --replay X.jsonl --override` | Replays using the current `config.json`/`plays.json` so you can tune thresholds |

## What it does
- **L1 on every play** (`reqMktData`).
- **Ranks every symbol** by fractional distance to its PS60 **pivot and second entry**, whichever is closer.
- **Three full-depth slots** go to the closest symbols. Each slot gets Smart Depth (`reqMktDepth`, 10 rows requested, 5 shown) plus tick-by-tick prints (`reqTickByTickData AllLast`).
- **Slot rotation uses hysteresis.** A challenger must be 15% closer than the worst incumbent, and that incumbent must have held its slot for at least 20 s. If IBKR rejects a depth request (309/10092), that symbol is skipped for 30 s.
- **Watched levels.** The pivot, second entry and any `extra_levels` are watched on both bid and ask. TWINEY also auto-tracks big inside levels (≥ 2,000 shares). Many levels are tracked at once.
- **Records every raw event** to `recordings/*.jsonl` (L1, depth ops, prints, resets, slot changes, errors and alerts) for replay or audit.
- **One dashboard**, with one pane per ladder:
  - **Plain-English headline.** For example: "Price is approaching your pivot 128.40 — 6¢ above it", "A SELLER keeps reloading at 128.40 (your pivot): 6,200 shares traded into it, refilled 5x", "The SELLER at 128.40 got CLEANED UP". It also says what that means for the PS60 play.
  - **Chart:** 1-minute candles with 5 days of IBKR history at startup, a 1m / 5m / 15m / 60m toggle (60-minute
    candles start at 9:30 like every other chart), a session **VWAP** line (toggle), and buy/sell volume. Your pivot, 2nd entry, extra levels, target and stop are drawn as labelled lines with a band. Green/red bubbles show shares absorbed into resting buyers/sellers at watched levels. R/C/P markers show reload, cleaned-up and pulled calls. Your working orders are drawn as lines too.
  - **Level-memory ladder.** Every price row remembers the last 15 minutes: shares sold into the bid and bought from the ask there, how many times the size came back after being hit (●), and a glowing **BUYER ×n / SELLER ×n** tag when a reload is confirmed. Your levels and your orders are tagged on their rows. The ladder stays centered on price.
  - **Time & sales** with prints at your levels tagged.
- **Build your own screen.** Every window is one view with a type and a link. **Windows ▾ → + Chart / + Footprint /
  + Ladder / + Time & sales / + Quote & trade** adds a window; the dropdown in its title bar links it to **Ladder 1 / 2 / 3**
  (follows whatever play holds that ladder) or to a **symbol** (always that stock; a symbol outside the three ladders
  gets its chart and quote, but no depth or tape). Windows move (Layout: FREE, drag the title bar), resize from any edge
  or corner, fold (▾) and hide or remove (✕). The default screen is five windows per ladder: QUOTE & TRADE, CHART,
  LADDER, TIME & SALES, FOOTPRINT 5m, plus CALLS, WHAT'S HAPPENING, DESK, JOURNAL, plays, orders and feed messages.
- **💾 Save layout** writes the whole screen (windows, links, sizes, positions, chart settings, columns) to
  `layout.json` next to `config.json`. It loads on every start, in any browser. Until you save, changes live only in
  the browser you made them in. **Reset layout** deletes the saved layout and puts everything back.
- **Voice follows your screen:** it only reads stocks that are in a window you can see right now. A play that is not up
  is never spoken. 🗣 on a QUOTE & TRADE window mutes that symbol; **solo** reads only that symbol.
- **Clean chart** (the `clean` button above the chart, on by default): only candles, volume, VWAP, your levels and your
  orders. Turn it off to see trapped bands, sneaky pivots, reload marks, absorption bubbles and R/C/P call markers.
- **Trade from the chart:** right-click at any price for BUY / SELL limit there (and Flatten / Cancel all), or hover
  the price and press **B** / **S**. The price scale on the right is real: round prices lined up with the candles.
- **Footprint window (5-minute):** every ladder has a FOOTPRINT 5m window next to its chart. Inside each 5-minute candle,
  per price row, it shows shares **sold into the bid × bought at the ask** from the tape, with every row's price on the
  right-hand scale. Pull the price axis up to get down to 1-cent rows. Green cell = buyers 3:1 or
  more, red = sellers 3:1 or more. Rows group into 1/2/5/10… ticks so they stay readable; wheel to zoom. The regular
  chart can also show a footprint on any timeframe with its FOOT button.
- **Chart axes work like TradingView:** pull the price axis down to squeeze, up to expand; pull the time axis right for
  wider bars, left for more bars; wheel to zoom; drag to pan; double-click to reset.
- **Ladder rows:** the gold row is the last price (gold = price, everywhere). White price = your pivot / level. A lit red / green row is a CONFIRMED reload
  seller / buyer with its refill count (`RELOAD SELLER ×14`); only confirmed ones are shown, and when it is gone the row
  says `SELLER CLEARED OUT` or `SELLER PULLED`.
- **Pane controls:**
  - Panes keep a fixed screen position. If a symbol changes, a banner says so.
  - **Pin** a symbol from a pane or from the plays list so it never rotates.
  - **Auto-rotate ON/OFF** in the header.
  - A ladder with a live reload is never rotated away.
  - Drag a pane's corner to resize it. Sizes are remembered; **Reset layout** clears them.
- **Orders · positions · fills (view only):** pending orders, positions with P&L, and today's fills, read from IBKR (`reqAllOpenOrders`, `reqPositions`, `reqExecutions`). Orders are placed and changed in TWS.
- Plus: the plays list with plain-English distance to each level, feed health, and TWS messages.

## Trading tools
- **Drag an order** chip on the ladder to another row, or drag its line on the chart, to move it.
- **Risk sizing:** type a dollar risk in the trade bar and click **size it** — shares = risk ÷ distance from the
  current price to the play's stop.
- **Hotkeys** (click a ladder first): **B** buy on the bid · **S** sell on the ask · **+** / **−** add / close one
  lot (the × dropdown in POSITIONS) · **F** flatten · **Esc** cancel all · **L** level tool · **A** arm / disarm.
- **Mark levels on the chart** (＋ mark… above the chart): choose 2nd entry, pivot, target, stop or extra level,
  then click the chart at the price. The play is updated, the reload trackers move to the new price, and `plays.json`
  is saved. Press **2** to mark a 2nd entry quickly. Drag any level line to adjust it. Click an extra level with the
  extra tool to remove it.
- **Positions panel:** close 1 / 5 / 10 and add 1 / 5 / 10 (× lot), Flatten, all as limits at the touch.
- **Sound:** a short tone on every call (🔊 / 🔇 in the header).
- **Voice** (🗣 Voice ON / OFF in the header; uses the voices built into Windows / Mac, no internet; if you hear
  nothing, Windows → Settings → Time & language → Speech → add a voice): reads out big size
  showing up or leaving a price — "18k buyer at 120", "buyer pulled 17k from 120", "seller at 120 got hit for 11k" —
  and every call: "confirmed reload seller at 241.20, reloaded 12 times, 6 thousand shares absorbed", "seller at 241.20
  cleared out", "pulled". Size threshold in `config.json → voice.min_shares` (5,000). Hit vs pulled is decided by the
  tape: if prints at that price cover the size that left, it got hit; otherwise it was pulled.
- **Replay:** `start_replay.bat` (or `python run_twiney.py --replay recordings/FILE.jsonl --speed 5`) plays a recorded
  session in the dashboard with pause / play / speed, and practice orders fill against the replayed book.
- **Limits (config.json → trading):** `max_position_shares` (1,000) caps any one position; `max_daily_loss` ($500)
  disarms trading for the rest of the session once the day's realized + open P&L reaches it. The header shows day P&L.

## PS60 inside TWINEY
Encoded from the PS60 handoff (Dan Shapiro / Access A Trader, via Antoine). Nothing is invented: every object is read
off the candles you see. Settings live in `config.json → ps60`.

- **Second-entry engine** (per play, from today's candles): pivot = your `pivot`. Long: break the pivot → new high →
  retrace → back through that high = SECOND ENTRY, always on a candle after the one that made the high (the retrace and
  the re-take may happen inside that same new candle once the pullback is real: `min_retrace_fraction` of the move, at
  least 3 ticks). Short is the mirror. The ladder says exactly where
  it is ("Retracing off 738.90 — SECOND ENTRY = through 738.90 on a new candle"), draws the line on the chart, and offers
  **use 738.90 as 2nd entry** so the play and the reload trackers move to it. After the second entry it watches the
  **build**: "building", "just triggered", or "NOT building after two minutes — out at breakeven". A close back
  through the pivot resets it and counts a failure. Judge on 5-minute candles with `second_entry_tf: 5`.
- **Measured potential (MP) and ATR are yours.** MP is the distance from price to the nearest moving average /
  supply / demand on the Daily, which you read off your TradingView chart. TWINEY has no moving averages, so it never
  computes MP. Put `"mp": 2.50, "atr": 3.10` on the play in `plays.json` and it shows
  `MP $2.50 · ATR $3.10 · 0.81× → CLEAR`; below `clear_ratio` (0.5 ATR) it is THIN. A play without `mp` grades PASS
  (no room on the board). `target` stays what it was: the price the runner exits at.
- **Grade READY / WATCH / PASS** on every ladder and in the plays list, with the four questions as ✅ / ❌ (pivot valid,
  size, control, risk). PASS = no `mp` (no room on the board), MP THIN against your ATR, or no stop (risk not known). READY only when
  the second entry has triggered and is building. The order confirmation repeats the grade, so a PASS play warns you
  before you send.
- **Sneaky pivots** on the 60-minute: a micro range inside the macro channel (≥ 2 candles, prefer 3, tight vs ATR,
  inset from the macro edges, ≥ $0.50 of room to the next macro edge). Shown as `SNEAKY PIVOT · SUPPLY 230.71 ×3 · room $1.52`
  on the chart and under the story; the second-entry path is the same.
- **Remount / rejection calls** at your levels: price goes through the level and reclaims it (REMOUNT) or loses it
  again (REJECTION). They go to the CALLS feed with Dan's how-to (in above the level once volume reclaims; the overshoot
  is the max pain). One call per level per 10 minutes.
- **PS60 exits** (header checkbox, or `trading.scale_plan.enabled`): pay yourself along the way — ½ at +$0.50, ¼ at
  +$1.50 (edit `cash_flow`), the rest runs to the target. After the first cash flow fills the stop moves to
  **breakeven**. Cash flow and the runner are separate orders, never one manager.
- **Stops are stop-limits**, never naked stops: pivot at your stop, limit `stop_limit_ticks` (10) through it.
- **Language lock:** supply, demand, pivot, confirmation, second entry, build, measured potential, ATR, cash flow, runner,
  max pain, remount, rejection, sneaky pivot, macro / micro channel, reload buyer / seller. A test scans the PS60 text.
- Not built (no data for it in an equity ladder): the options translation layer, option flow, and the moving-average /
  Bollinger stack for bounce plays. Mark those levels as `extra_levels` or `target` from your chart for now.

## The desk: record, mark, screenshot, journal, replay
- **● REC** in the header, or the **space bar**: start / stop a recording at any moment. Live and demo sessions also
  start recording on launch (`recording.enabled`). A recording started mid-session first writes the current books,
  charts and plays into the file, so it replays cleanly from that moment.
- **⚑ mark / key M:** drops a marker at that second with the focused ladder's symbol, price and what the story said.
  Click a marker in the DESK window to add a note. Markers also go to `recordings/NAME.marks.jsonl`.
- **📷 shot / key P:** screenshot of the whole screen into `recordings/shots/`, plus a marker that links to it.
  Needs the Pillow package (the launcher installs it; or `python -m pip install pillow`).
- **JOURNAL window / key J:** type a note, press Enter. Notes go into the recording and the session journal.
- **Stop** writes `recordings/NAME.journal.md`: duration, plays, P&L, your notes, markers (with screenshots), every
  call with its grade, and every fill. The JOURNAL window links the last journals.
- **DESK window:** every recording with size, marker count and a **▶ Replay** button. Replay opens a second TWINEY
  on the next port in a new tab: **space** = play / pause, **← →** = slower / faster, click a marker to jump there
  (backwards jumps restart the replay and fast-forward). Practice orders fill against the replayed book.
- `start_replay.bat` still works for replaying from the command line.

## Grading calls and tuning
- Every call in the CALLS feed has 👍 / 👎. Grade a call and TWINEY remembers it (`recordings/grades.jsonl`, and inside
  the session recording). Click again to clear a grade.
- `tune.bat` (or `python tune.py recordings/FILE.jsonl`) replays that recording with a grid of reload settings and shows,
  for each, how many of your good calls it keeps and how many bad ones it avoids. Copy the best line into
  `config.json → reload`. Grade a few sessions first: one or two grades prove nothing.
- Demo sessions record too (`recordings/demo-*.jsonl`), so you can practise grading before you have live data.

## Play invalidation
- When price trades through a play's `stop` or reaches its `target`, the play is **retired**: it leaves the ranking,
  gives up its ladder (unless pinned), and the plays list shows `RETIRED — stopped out at 229.62` with a **Reactivate**
  button. TWINEY also posts a message in Feed Messages.
- **Reactivate** puts it back. It won't be retired again until price has first come back inside the stop / target band.
- ✖ next to any play retires it by hand. Plays without a stop or target are never auto-retired.

## Trapped traders and reloader map
- **Tape words:** each print is tagged **IN** (paid the offer — wanted in now) or **OUT** (hit the bid — wanted out now).
  The 30-second read says "impatient buyers paying the offer" / "impatient sellers hitting the bid".
- **Trapped:** IN prints above the current price over the last 10 minutes are **trapped longs**; OUT prints below it are
  **trapped shorts**. A pill in the pane header shows the size and where they got in; the chart shades that band; the
  story says what it means for the play and which reloader absorbed them. Gross numbers: TWINEY can't see who already
  got out, so read them as pressure, not fact. Thresholds in `config.json → trap`.
- **Reloaders:** the nearest confirmed or likely reload buyers below and sellers above the market are listed in the
  story ("Reloaders — below: BUYER 240.13 ×2 …") and marked on the chart's left edge (B×n / S×n).

## Vocabulary (exact rules, all in `config.json → reload`)
| Call | Evidence required |
|---|---|
| `RELOAD SELLER DETECTED` (ask) / `RELOAD BUYER DETECTED` (bid) | Within `window_seconds` (120), the level refilled after executions at least `min_refreshes` (2) times. Shares executed against that side must be at least `min_absorbed_shares` (1000) **and** at least `absorbed_multiple` (1.5) × the largest size ever displayed there. At least `min_display_shares` must still be showing. |
| `CLEANED UP` | A confirmed reload disappeared. Executions after it took its final size (and within 5 s) reached ≥ 50% of that size, **and** price traded through the level. |
| `PULLED` | A confirmed reload disappeared, and after `pull_grace_seconds` (1.5 s, because the tape lags the book) there was not enough execution evidence to call it consumed. |

If a level was consumed but price never followed through within 10 s, TWINEY closes it silently as INCONCLUSIVE and makes no call.
A level that has moved beyond the visible ladder is marked *off view* and is never judged.
After an error 317 reset or a new subscription, disappearances are ignored until the book has resynced plus `resync_grace_seconds`.
TWINEY never claims that displayed liquidity belongs to one identifiable participant.

## Connection handling
- `nextValidId` is used only as the "ready" signal. Its order id is discarded.
- **Disconnect or 502/504/326:** exponential backoff reconnect (2 s up to 60 s). All depth is released and requested again.
- **1100/2110:** feed is marked down and rotation pauses. **1102:** resumes. **1101** (data lost): everything is resubscribed.
- **317:** the book is emptied and resynced, and no verdicts are made during the resync.
- No `nextValidId` within 15 s: TWINEY drops the connection and retries. The usual causes are wrong API settings or a client id already in use.

## Layout
```
run_twiney.py            CLI: live / --demo / --replay
twiney/config.py         config defaults + play validation
twiney/book.py           Smart Depth reconstruction (insert/update/delete, per-price aggregation)
twiney/tape.py           print classification + tape read
twiney/levels.py         reload / cleaned-up / pulled state machine
twiney/ranking.py        proximity ranking + slot allocation
twiney/engine.py         pure, timestamp-driven engine (live, replay and tests share it)
twiney/ibkr.py           TWS API wrapper + session (reconnect, subscriptions)
twiney/safety.py         where the order path may live (checked by tests)
twiney/trading.py        TradingGate + SimBroker / IbkrBroker + Trader
twiney/dashboard.py      local HTTP server (GET only) + static/dashboard.html
twiney/recorder.py       JSONL recorder;  twiney/replay.py  replay + comparison
twiney/desk.py           REC / markers / screenshots / journal / replay launcher
twiney/sim.py            demo feed (with 5 synthetic sessions of history + daily bars)
twiney/ps60.py           PS60: second-entry engine, MP / ATR, grade, sneaky pivots, remount, cash-flow legs
tune.py                  reload-threshold tuner scored against your graded calls
```

## Tests
`python -m unittest discover -s tests -v`

This runs 117 tests covering the book, reload verdicts, 317 resets, ranking/rotation, a fake TWS session (reconnect, 1100/1101, 309, rotation cancels), the safety guard and source scan, replay fidelity and the dashboard.
One test checks the guard against the real `EClient`. It only runs when `ibapi` is installed.

## Before connecting to a live-data session (handoff checklist)
These could not be checked in the build environment because IBKR's download site was not reachable there:
- [ ] Install the official `ibapi` and re-run the tests. The EClient guard test must run, not skip.
- [ ] Confirm the callback signatures in `twiney/ibkr.py` match your installed version: `error` (both pre- and post-10.35 forms are handled), `updateMktDepthL2(..., isSmartDepth)` and `tickByTickAllLast`.
- [ ] Confirm the size units on your feed. Depth and tick-by-tick sizes should be shares (10.x Decimal). If they come through in lots, adjust `reload.*_shares` accordingly.
- [ ] Market-data entitlements: depth for each venue you need (for example NASDAQ TotalView), plus tick-by-tick. Look for errors 354/10089/10092 in the Feed Messages panel.
- [ ] With paper TWS, pull the network or restart TWS and check the reconnect, 1100/1101/1102 handling and depth resubscription.
- [ ] Watch for an error 317 in a live session. The book should empty and resync with no `PULLED` calls.
- [ ] With PS60 exits on, check on paper that a cash-flow fill REDUCES the stop (OCA type 2) instead of cancelling it,
      and that the stop moves to breakeven. If TWS cancels the stop instead, turn PS60 exits off and tell Claude.
- [ ] Replay the first real recording (`--replay`) and check that `replay N / recorded N` matches.
