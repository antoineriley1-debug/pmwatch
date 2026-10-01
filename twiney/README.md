# TED — TWINEY EXECUTION DESK (v3.1)


> **Settings live in the app.** Click **SETTINGS** on the command bar: every setting, with its explanation, a search box, SAVE, and RESTART NOW for the few marked RESTART. The desk writes config.json for you; you never need to open it. Two things stay locked by design: live trading (paper-only) and the desk address (this computer only). Your Quant Data key is entered there too, shown only as its last four characters, and never written into recordings or exports.

A professional single-screen trading workstation on top of Interactive Brokers, built around PS60 and order flow,
with ladder trading that is **locked to paper accounts** until you deliberately unlock it.

## The desk
- **Symbol box** (top left, `Ctrl+L`): type a ticker, Enter. Every symbol-linked panel switches together: chart,
  Level II, time & sales, PS60, reloads, calls, the order ticket. Recent symbols are in the ▾ next to it. A ticker that
  is not in plays.json becomes a watch-only play (mark its pivot on the chart to rank it).
- **Symbol tabs**: NVDA | TSLA | AMD | +. Each tab keeps its own chart zoom. **Only the active tab speaks**: voice reads
  reload buyer / seller calls ("Reload seller at 140.00. 30 reloads. 40 thousand shares observed."), cleared out and
  pulled, for the tab you are on. Background tabs are silent. VOICE: ON/OFF and a volume slider in the command bar.
- **Dockable panels**: CHART, FOOTPRINT 5m, LEVEL II, TIME & SALES, PS60, RELOADS, ORDER ENTRY, POSITIONS, ORDERS,
  WATCHLIST, CALLS, DESK, JOURNAL, MESSAGES. Six dock zones (left / center / right × top / bottom), each holding tabbed
  panels. Drag a panel's tab to another zone, or off the zones to float it. ⤢ maximizes, ⧉ undocks, ✕ hides (Panels ▾
  brings it back). Drag the gutters to resize. Nothing scrolls the page.
- **Layouts**: ★ PS60 Execution (default), ★ Scalping, ★ Tape Focus, ★ Chart Focus, ★ Laptop. Save your own under a
  name, rename, duplicate, delete. Layouts live in `layouts.json` next to config.json and the last one used loads on the
  next start, on any browser.
- **Order ticket**: symbol (linked), BUY / SELL, quantity, LIMIT or STOP LIMIT (MARKET and naked STOP are off by your
  rules; `trading.allow_market` turns them on), price with bid / ask / mid / last, TIF (DAY / GTC / IOC), stop+target,
  PS60 exits, TRANSMIT. A double-click, retry or lag can never send twice: every ticket carries a nonce. The ticket log
  shows SUBMITTED → what IBKR says. Order states are IBKR's, never assumed: CREATED, SUBMITTED, ACKNOWLEDGED,
  PARTIALLY FILLED, FILLED, CANCEL PENDING, CANCELED, REJECTED.
- **POSITIONS**: symbol, side, qty, average entry, last, **P&L %** (no dollars), ½ / ¼ / custom reduce, CLOSE (asks).
- **ORDERS**: working orders with filled / remaining / status, MODIFY, CANCEL, CANCEL ALL; click a row to jump to that
  symbol; "history" shows done orders.
- **Hotkeys** (command bar): every action is configurable. Execution hotkeys (buy, sell, cancel, flatten) are unassigned
  until you set them; they go through the same checks as the mouse.
- **Status bar**: IBKR connection, data type, ORDERS state (why not, if not), ladders in use, REC timer, the day loss
  lock, the clock. When order routing is down the ticket's TRANSMIT is disabled and the reason is shown.
- **Data**: a value that is not there shows as —. Nothing is invented.

## Trading from the ladder (paper only)
- **ARM** in the header. TWINEY starts DISARMED every launch; nothing can be sent until you arm it.
- Click **BUY** on any ladder row to place a limit buy at that price; **SELL** likewise. Or use the
  trade bar: **BUY bid** / **SELL ask** at the current quote, **Flatten**, **Cancel all**.
- A confirmation box shows size, price, dollar value and the stop/target legs (Enter sends, Esc cancels).
  Tick **one-click** to skip it.
- **AUTO 2ND ENTRY** (on by default, `trading.auto_second_entry`): the lines you draw ARE the orders, while ARMED.
  Draw the 2nd entry and the entry order goes in at once as a STOP-LIMIT: a long fills only when price comes back
  up through it, a short only when it comes back down through it. With price already past the level the order
  waits until price is back on the other side, so it never chases. The stop-limit's limit is a cap, not the fill:
  the bigger of `auto_entry_limit_ticks` (10) and `auto_entry_max_slip_pct` (0.3% of the price) past the level, so
  a fast print through the level still fills at the market. If price ever runs past even that, PLAY SETUP shows
  TRIGGERED and the desk says so; if price crosses the level with no order working (disarmed, locked), the desk
  says why at that moment. Drawing a 2nd entry while the desk is DISARMED arms it (paper / practice accounts
  only, never when locked for the day; `auto_arm_on_second_entry`). Levels already on the chart when the desk
  starts never arm it. A chip on the 2nd entry line says ENTRY LIVE (side, shares), PART FILLED, FILLED,
  TRIGGERED or NO ORDER with the reason. Draw with **2** then a click, the **＋ mark** menu, or right-click the
  chart: 2ND ENTRY here / TARGET here / STOP here. A part fill keeps the rest of the entry working. The FILLED
  chip goes 90 s after the fill (`filled_chip_seconds`), and when the trade goes flat (stopped out, target,
  flatten) its 2nd entry, stop and target come off the chart (`clear_lines_when_flat`); the pivot stays. It uses the
  ticket size until you draw the
  stop, then it is sized from your RISK $. Draw the target and the stop and they join the entry as its bracket.
  Drawn after the fill, they go in as the position's stop and target, and dragging a line moves its order.
  Clearing a line never pulls a stop that is protecting a position. One entry per drawn level; a hand cancel
  switches that play's AUTO off until you redraw the 2nd entry or tick it back on in PLAY SETUP.
- **Charts start blank.** A new ticker has no levels; you put the stop, target and 2nd entry on it. The launcher
  writes a watch-only `plays.json`, and any play still carrying the example file's placeholder prices is blanked
  on load (the desk tells you). **CLEAR PLAY** in PLAY SETUP wipes every level off a chart.
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

1. Start with a blank `plays.json` (the launcher writes one; or `{"plays": [{"symbol": "SPY", "watch": true}]}`) and draw your levels on the desk, or copy `plays.example.json` and put in your PS60 plays. The example prices are placeholders and are blanked on load. `pivot` is the
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
- **One screen, one symbol.** Type a ticker in the box at the top (or press `/`) and Enter: TWINEY opens it, gives it a
  ladder, and the whole screen is that stock — quote strip (last, change, bid × ask with sizes, pivot / 2nd / target /
  stop, grade, MP and ATR), day stats (open, high, low, prev close, volume, tape read, trapped traders), the trade bar,
  the chart, the 5-minute footprint under it, the ladder and time & sales on the right, and a bottom drawer with tabs:
  STORY (what's happening + the PS60 read), CALLS (this symbol; tick "show every play" for all), ORDERS, PLAYS, DESK,
  JOURNAL, MESSAGES. The watchlist on the left lists your plays closest to pivot first; click one to switch. A ticker
  that is not in plays.json becomes a watch-only play — mark its pivot on the chart and it joins the ranking.
- **Panels:** drag the gutters between them to resize; ▾ on a panel header collapses it; the drawer collapses too.
  **💾** saves the sizes, chart settings and columns to `layout.json` (loads on every start). **Reset** puts it back.
- **Ladders:** the symbol on screen is always pinned to a ladder; the other two rotate to the plays closest to their
  pivots (⟳ turns rotation off). Pin from the quote strip to keep a symbol's ladder when you switch away.
- **Voice and beeps follow the screen:** only the symbol you have up is spoken or beeped. 🗣 in the header turns the
  voice off.
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
- **DESK window:** every recording with size, marker count, **⬇ Export**, **▶ Replay**, and **🗑** (deletes the
  recording with its markers, journal and screenshots, asks first).
- **⬇ Export** downloads one zip made to hand to a person or an AI: the raw recording, `calls.csv` (every call with
  your grade), the journal, markers, screenshots, and `SUMMARY.md` (plays, settings, calls, notes, markers, orders,
  fills, and what the vocabulary means). The JOURNAL window has "Export this session so far" while you are still
  recording. Replay opens a second TWINEY
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

## Conviction: is he still there? (v3.2)
A proven reloader used to stay lit until the desk called him cleaned up or pulled. The shape told you someone WAS
there; it did not tell you whether he still is. Now every proven level carries a **conviction** (0..1) and a word for
where he stands, in Dan's language, and the ladder row's brightness IS that conviction:

| Word | Meaning | On the ladder |
|---|---|---|
| **RELOADING** | size came back after getting hit; little has traded through since | bright, breathing glow |
| **STILL THERE** | he's still there but hasn't reloaded in a bit | steady, dimmer |
| **NOT RELOADING** | more has traded through than he was putting back, or untested too long | dim; don't lean on him |
| **CLEANED UP** | price came back and the level didn't hold | a dashed **C** for `gone_show_seconds` |
| **PULLED** | the size left without getting hit | a dashed **P** for `gone_show_seconds` |

Volume does the work, not the clock: shares that hit the level since his last reload are measured against the most he
ever let trade before putting it back (never less than his biggest showing), times `stale_multiple` (1.5). Time is a
slow second bleed to `stale_seconds` (40 min); while size is still showing it never takes the reading under half on
its own. A reload snaps conviction back to 1. Price trading through with nothing there is CLEANED UP at once, no decay.

- **The long memory.** A row where a proven reloader absorbed real size earlier today keeps a dashed **A** mark for the
  rest of the session (Ac = then cleared out, Ap = then pulled), even hours later, even after the tracker is gone.
- **REAL or FAKE size.** For every price on the ladder: of the size that has LEFT that price, how much traded and how
  much simply vanished. A thin line under the size: green = REAL (it gets filled), gold = MIXED, red = FAKE (it gets
  pulled before it trades). Hover for the numbers. Inferred from size changes between settled book reads (once a tick),
  minus what printed there in between; a drop that comes straight back inside `requote_seconds` is one venue re-quoting,
  not a pull. IBKR gives displayed size, not order IDs, so read it as a tilt, not a measurement. `config.json → ladder`.
- **Rotation leans toward a live reloader.** A symbol whose best level is RELOADING or STILL THERE is never rotated out (its
  conviction only keeps moving while the desk can see its book), and for slot allocation its distance to its pivot is
  cut by `depth.conviction_weight` × conviction. The watchlist's own ranking stays distance-only so the order you read
  never jumps.
- The RELOAD panel shows CONVICTION (bar + the word), SINCE RELOAD (how long, and how much traded through not put
  back), and SIZE HERE (REAL / MIXED / FAKE) for every proven level.
- **SOMEBODY KNOWS (⚡).** Dan's tell when a pivot triggers: short-dated, out-of-the-money options getting bought at
  the ask, in the direction of the level. A reload BUYER is confirmed by calls, a reload SELLER by puts, inside the
  urgency window (`flow.urgency_window_minutes`, `urgency_max_dte`, `urgency_min_otm_pct`, `urgency_min_dollars`).
  A gold ⚡ beside the R tag (or beside your pivot's price while it is still building) means the flow agrees; hover
  it for the strike, days out, dollars, prints and sweeps. The RELOAD panel carries the same line. When the other
  side has more premium the score is halved and it never reads as KNOWS. Rotation leans toward it too
  (`depth.flow_weight`).

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

This runs 119 tests covering the book, reload verdicts, 317 resets, ranking/rotation, a fake TWS session (reconnect, 1100/1101, 309, rotation cancels), the safety guard and source scan, replay fidelity and the dashboard.
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

## BIG MONEY 30D

Every option print of `flow.big_money_min_premium` ($500K) or more is remembered for `flow.big_money_days` (30), in
`recordings/big_money.jsonl`, and judged on facts each time you look: the premium paid, the breakeven (strike ± the
price paid), and the stock now — or its close on expiry day once the contract has expired. BUYERS IN PROFIT /
BUYERS UNDERWATER / EXPIRED WORTHLESS (and the sellers' side for prints sold at the bid). Open contracts are counted
at their intrinsic value only ("worth at least"): time value needs live option quotes. The BIG MONEY 30D panel lists
them for the symbol on screen; the chart marks the biggest open strikes (cogwheel → TRADING to hide them).

## Practice option flow (demo)

Modelled on how real flow behaves: most of it FOLLOWS price. A watchlist stock moving hard on its own (0.25%+ in
90 s) draws put buying and call selling on a drop (calls bought, puts sold on a rally), near the money and
short-dated, more and bigger the harder it moves, with out-of-the-money sweeps on sharp moves and a minority of
contrarian dip buyers. Separate quiet clusters of out-of-the-money buying come before a move only about a third of
the time. URGENT FLOW has a ticker search: that name's contracts being chased now and everything urgent-type that came
in on it this session. The daily chart counts down to the close in session and to the next open outside it.

## NO FLOW, NO DOUGH

Dan's confirmation, on the real feed and in practice. The setup comes first (pivot, 2nd entry, reloaders). Then the
desk watches for short-dated, out-of-the-money money on the play's side (calls for a long, puts for a short) bought
at the ask, and asks whether it KEEPS coming: `flow.dough_min_dollars` ($300K) across at least
`flow.dough_min_minutes` (3) separate minutes inside `flow.dough_window_minutes` (30), the last of it inside
`flow.dough_fresh_minutes` (10). The FLOW line in PS60 and PLAY SETUP reads NO FLOW, NO DOUGH / FLOW STARTING /
FLOW CONFIRMED / FLOW FADED / FLOW AGAINST. A READY setup is held at WATCH until FLOW CONFIRMED
(`flow.no_flow_no_dough`; off = shown, never holds the grade). FLOW CONFIRMED and FLOW AGAINST are said once.
In practice, the option clusters that come before a move are the sustained ones with size; a few prints and done
rarely lead anywhere, as in the market.

