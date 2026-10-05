# TED (Twiney Execution Desk) — handoff for another assistant

Read this first. It tells you what the program is, how it is put together, the rules the owner has set, and what is
still open. Everything here is true as of commit on branch `claude/twiney-v1-complete-gdn0ws`.

## What it is

A local order-flow trading desk for one trader (Twiney) who trades Dan Shapiro's PS60 method. It runs on his Windows
laptop, talks to Interactive Brokers Trader Workstation (TWS) through the TWS API, and shows a browser page at
`http://127.0.0.1:8765`. Option flow comes from Quant Data's REST API. Nothing is hosted; nothing leaves the laptop
except the requests to IBKR and Quant Data.

What it does, in one line each:

- **Ladder (Level II / DOM)**: bid · price · ask. Size drains as it gets hit (`−1.2k HIT` / `+800 REFILL` flashes),
  reloaders (size that keeps refilling at one price) are outlined with `↻N`, followed until CLEANED UP or PULLED, and
  recognised when they come BACK. Click or right-click rows to trade.
- **Time & Sales** (price, size) and **BIG TAPE** (big prints and builders only; MIN shares / $ filter in its header).
- **Chart**: candles, Dan's moving averages and Bollinger bands, VWAP, the play's lines (pivot, 2nd entry, stop,
  target), working orders. Lines are drawn with MARK or right-click and dragged with the mouse.
- **PLAY SETUP** (pivot, 2nd entry, stop, target; side inferred from the levels), **CONVICTION** board, **PS60** panel.
- **Option flow** panel and voice: unusual calls / puts, "expires today / this week", "again ×N" at one far strike,
  in-the-money prints called hedges, NO FLOW NO DOUGH gate.
- **TRAPPED on the day** (crowd underwater since the open, their exit level), **order-flow pressure**, **big money 30D**.
- **ORDER ENTRY**: limit-only ticket, brackets, scale plan (MP / CASH FLOW / BUILD / custom rungs), OPTIONS chain with
  Greeks and option orders, positions with scale / close.
- Recording, replay, clips, journal, voice notes, practice simulator (`--demo`).

## Run it

```
python run_twiney.py            # live: TWS must be running with the API enabled
python run_twiney.py --demo     # practice: synthetic market + simulator, no IBKR
python -m unittest discover -s tests     # 340 tests, all must pass
python tools/acceptance.py --port 8765 --symbol AAPL --switch MSFT [--demo --yes]   # against a running desk
python tools/sim_orders_test.py         # 34 order checks against a running demo on port 8799
```

Windows launcher: `start_twiney.bat` (live) / `start_demo.bat`.

## Where things live

| Path | What |
|---|---|
| `run_twiney.py` | entry point: modes, IBKR session, Quant Data feed, dashboard, watchdog thread |
| `twiney/engine.py` | the market model: books, tape, reloaders, plays, alerts, pane snapshot for the page |
| `twiney/trading.py` | order entry: `TradingGate` (paper-only gate, caps), `Trader` (submit, brackets, scale plan, chart lines → exit orders, watchdog), `SimBroker`, `IbkrBroker` |
| `twiney/ibkr.py` | TWS API adapter: connection, market data, depth, tape, orders, errors, options |
| `twiney/flow.py` | Quant Data feed and option-flow logic |
| `twiney/board.py`, `ps60.py`, `levels.py`, `narrative.py` | PS60 board, signals, reloader tracking, spoken / written words |
| `twiney/dashboard.py` | the local HTTP server and `/api/*` routes |
| `twiney/settings.py`, `config.py` | SETTINGS schema and defaults (every setting is editable in the page) |
| `twiney/paths.py` | the user's data folder `C:\Users\<you>\TWINEY` (config.json with the port and key, plays, layout, recordings) |
| `page_src/` | **the page source**: `desk_*.js`, `desk_body.html`, `desk.css`, `skin.css`, `dashboard_old.html` |
| `twiney/static/dashboard.html` | **built** from `page_src/` — never edit it by hand |
| `tests/` | unittest suite; `helpers.py` builds configs and plays |

### Editing the page

Edit the pieces in `page_src/`, then:

```
python page_src/build_page.py
```

`dashboard_old.html` is the original single-file page; `build_page.py` takes its helpers, chart drawing, ladder and
tape renderers from it and wraps them with the newer panel system (`desk_pool.js`, `desk_core.js`, `desk_panels.js`,
`desk_boot.js`). The live poll loop is in `desk_panels.js` (`poll()`), at 250 ms, self-pacing on slow machines.
After building, check every `<script>` parses (`node -e "new Function(src)"` on each), run the tests, and look at the
page in the demo. A JavaScript error in a render function used to grey the whole desk; it now shows `DRAW ERROR` in
the status bar instead.

## Rules the owner has set (do not break these)

1. **The Quant Data key** lives only in `config.json` in the data folder, set from SETTINGS. Never in git, never in
   chat, recordings or exports. Private zips for the owner may carry it; the repository never does.
2. **Live trading** is off unless he switches *Allow live* on in SETTINGS → Trading (it confirms, then RESTART NOW).
   Paper accounts start with `DU`. Order entry is limit / stop-limit only, with share, dollar and per-minute caps.
3. **All settings belong in SETTINGS.** He does not edit JSON.
4. **Simple and readable first.** Plain English, his words. Dan's language in the voice: "they keep scooping up the
   calls", "the dough", "cash flow", "measured potential", "trapped shorts cover here".
5. **The chart stays clean** unless he turns an overlay on (IND menu).
6. **Every change is tested**: unit tests, the demo in a browser, and a screenshot when it is visual.

## How chart trading works (the part he asked about last)

- Draw a STOP or TARGET with MARK ▸ stop / target and a click, or right-click ▸ STOP here.
- **On any open position**, those lines are its exit orders (`Trader._lines_are_exits`, setting
  `trading.lines_are_exits`, default on): a drawn stop sends a stop-limit for the shares held; dragging the line moves
  the order; existing bracket exits are adopted, so nothing is duplicated. When the desk moves a stop itself
  (breakeven after the first cash flow), the line follows the order. Test: `tests/test_scale_plan.py::ChartStopTests`.
- A stop already through the market is not sent (it would fill at once); the desk says so and asks you to move it.
- Working orders on the chart can also be dragged directly.

Top-bar buttons: **MARK** puts a marker on the recording timeline (key M). **SNAP** saves a screenshot to the journal
(key P). **STOP+TARGET** attaches the play's stop and target as a bracket to every entry. **PS60 EXITS** splits the
target into cash-flow pieces (50% at +$0.50, 25% at +$1.50 by default) with a runner to the target, and moves the
stop to breakeven after the first cash flow.

## Open items

- **IBKR real-data validation** needs his paper login to have market data shared (Client Portal → Settings → Paper
  Trading Account → share real-time market data → Yes; takes effect next trading day). Then run
  `tools/acceptance.py --reconnect` against TWS paper.
- Built: big prints fly from LEVEL II to T&S (`flyBigPrints`), the last-minute money gauge on T&S (`tape.stats`
  `usd_60`), `SHORTS SQUEEZED` / `LONGS FLUSHED` for clean trends (TRAPPED stays for reversals; HEAVY said once per
  trap), the chart stop grows with adds (`_auto_protect`), option stops on the stock or the contract
  (`Trader.set_opt_stop`, chart STOP line by the contract's direction, setting `trading.option_stop_follows_chart`),
  IBKR 110 on an option price re-sends once on the dime.

## Options desk (latest)

- **Layout ★ Options Desk**: 1-hour CHART, FOOTPRINT 5m, OPTION CHART, OPTION FLOW + POSITIONS (split), stock LEVEL II +
  T&S (split), stock BIG TAPE, OPTION LEVEL II + OPTION T&S (split), OPTION BIG TAPE. A zone can be SPLIT (⬓ on its
  tab bar) to show two windows stacked. CHARTS opens CHART / CHART 2 (5m) / CHART 3 (15m) / FOOTPRINT / OPTION CHART
  as floating windows; DOCK ▾ docks them, ⧉ floats them.
- The option side follows the contract on the OPTION CHART (picked in the OPTION CHAIN). `/api/options/bars?key=`
  returns bars (mid; IBKR MIDPOINT + TRADES history for volume), quote, position, orders and `tape` (book rows, prints,
  big prints incl. Quant Data flow on that contract). IBKR gives options top of book only; the practice desk models a
  book. `Engine.practice_opt_tick` re-prices held / ordered / charted contracts from the stock every 0.5 s.
- FAST strip on the stock chart and the option chart header: BUY / SELL now, ½ OUT, ALL OUT (outs never confirm).
- Option prices: `opt_through` (fill-now limit, one step through the touch), `opt_snap` (typed / dragged prices on a
  nickel). Moving an option order re-sends it on the option contract (`IbkrSession.modify_order`).
- Safety (latest): sell to open off by default (`trading.allow_sell_to_open`, covered calls allowed, red SHORT
  confirm always); day P&L and the loss lock include options and option commissions; option quotes re-subscribe after
  a reconnect (`IbkrSession._forget_opt_quotes`); expiration day warning 15:30 + auto-close 15:50
  (`Trader._expiry_tick`, `trading.expiry_*`); halts from IBKR tick 49 (`Engine.on_halt`, HALTED badge, voice);
  RISK sizing for contracts (delta × 100 × distance to the stock stop); option hotkeys (HOTKEYS menu, unassigned).

## Stock + Options desk (latest)

- **Layout `★ Stock + Options`** (default; opens once on its own): option chain / flow / ORDER ENTRY tabs left, stock
  chart centre with LEVEL II and T&S right, the linked contract underneath (option chart, option LEVEL II, option T&S).
- **ORDER BAR** on top of the stock chart (`#fastStock`, `renderFast`): STOCK | OPTION switch, size, BUY, SELL,
  CLOSE POSITION, SELL 25 / 50 / 75 / 100 %. All limits; outs never confirm.
- **Pick first**: the bar's STOCK / OPTION switch sets the play's `trade_as` (`Trader.set_trade_as`, saved in
  plays.json with `opt_key`, `opt_qty`, `trade_as_set`). OPTION: the stock chart's 2nd entry buys the contract when the
  stock trades back through it, the STOP line is its stop (option stop), the TARGET sells every contract
  (`Trader._opt_link_tick`). A call makes the play long, a put short. No stock order is sent for those lines. Picking
  another strike moves the link unless the old contract is still held. Not picked yet: a new 2nd entry asks.
- **Auto stop**: a new 2nd entry drawn with no stop on its side gets one `trading.auto_stop_dollars` ($1) away.
- **Adds**: with brackets on, adding to a position joins its working stop and take profit (`_grow_exits` grows them to
  every share); taking profit along the way trims them (`_guard_exits`).
- **Cancel from ORDERS**: CANCELLING… at once, CANCEL PENDING until IBKR confirms, a cancelled STOP / TARGET takes its
  line off the chart; orders typed in TWS say "cancel it in TWS" (the API can't).

## PRO ladder (default Level II mode)

`LEVEL │ STK │ SOLD │ BID │ PRICE │ ASK │ BOT │ STK` (`ladderProHTML` in desk_panels.js; MODES pro → simple → tight → wide).
- SOLD / BOT = this visit (`Engine._visit`): resets when price returns after trading `ladder.visit_away_ticks` (3) away;
  ×N on the price = visits in 15 min. STK = `PullBook.pullstack` (added vs pulled, `ladder.stack_seconds` 60); shown
  from a fifth of BIG, lit at half of BIG (stepping up / pulling).
- LEVEL / strips = `Engine._ladder_marks`: play lines (both sides), `sneaky_levels` (drawn: MARK → sneaky pivot or
  right-click ◇ SNEAKY PIVOT here) and TED's 60-minute sneaky pivots, HOD / LOD, proven reloaders, and option strikes
  with `ladder.strike_min_premium` ($100K) today. Lines within 80 rows get their own row past a gap.
- CLR ▲ / CLR ▼ = `/api/ladder/clear` (`Engine.ladder_clear`: baselines age out with the prints they covered).
- Option ladder: visits from the contract's prints, pull / stack from the practice book or the touch's size changes
  live (`on_opt_size`), marks = the contract stop, your entry, the stock lines as ≈ contract prices (mid + Δ × move),
  and the option flow on that contract.
- Stock chart: `#optPosStrip` = contracts held on the ticker with ≈ value and P&L at the TARGET and STOP.

## Trade journal

- `Desk` builds a trade per instrument from fills: stocks (`engine.on_fill`) and options (`engine.on_opt_fill`, × mult).
  A stock trade and an option trade on the same ticker are separate entries; both read the ticker's log.
- At entry: `plan` (the lines for that direction), default `name`. At exit: `result` WIN / LOSS / SCRATCH (< 0.1 %),
  `pnl` (× mult), `pnl_pct`, `r` (stock, against the planned stop), `minutes`, `transcript` (voice notes), `marks`
  (with `context`: what the screen showed), `log` (every order, fill, line, mark, word). One page per trade:
  `recordings/journal/<date>-<name>.md` (`save_trade`, re-written on rename / grade).
- Every `Trader._note` (orders, stops, refusals) and fill lands in the log; MARK adds a screen-context line
  (`recording.mark_screenshot` also grabs the screen when Pillow can).
- `Desk.reconcile` (engine tick, every 5 s): an open journal trade whose real position is flat is dropped and said.
- JOURNAL panel: IN TRADE card (name it, live P&L, plan, words, marks), then the trades with ▸ details and SAVE.

## Chart studies (your TradingView scripts, inside TED) — stock charts only

`twiney/studies.py` ports three scripts line for line: **new PS60 Gas + ATR**, **PS60 MP Airspace**, **new Unvisited Highs
Lows**. Each switches off on its own (SETTINGS > Chart studies, or the IND menu on the chart); every input of the
scripts is a setting there. Never drawn on the option chart.

Data (IBKR, asked one at a time so TWS never flags pacing; asked again each new day after 9:25):
- Daily 10 years (the Daily / Weekly 200s settle like TradingView's), 30-minute regular hours 1 year (the CONT
  sample; 60-minute candles = two 30s from 9:30, like TradingView's), 5-minute extended hours 3 days kept up to date
  (premarket / after hours / the 9:30 open), 5-minute chart history 2 months (the 5 / 15 minute charts' long MAs).
- Everything is recorded, so replays draw the studies too.

One number everywhere:
- ATR = Wilder (TradingView's ta.atr) for the desk, the play grades and the studies.
- High / low of day = the regular session only (9:30-4:00). The chart's daily candle, the ladder's HOD / LOD and
  the studies use the same one. The practice market (any time of day) is exempt.
- The study MAs are the chart's MAs: same bars, same formulas (EMA seeded with the SMA, population-stdev BB).
  Verified equal to the last digit.

Deliberate differences from the TradingView scripts (from reviewing them):
- Unvisited highs / lows: a level is cleared only by a COMPLETED daily close through it. On TradingView the
  realtime daily close clears it intraday, and it comes back on a refresh. TED flags "CLOSING THROUGH" until the close.
- One second-entry helper: the pivot is YOUR pivot on the chart (or the tight box when its master is on). The
  two scripts each had their own, with different tight-box defaults.
- Prev day high / low / close before 9:30 = yesterday (the scripts' daily [1] reads the day before in premarket).
- Earnings: IBKR's API has no earnings calendar, so the reaction bar takes a date you type (SETTINGS).
- Airspace ATR distances use the live day's ATR like the script; "Airspace ATR on the live day" off = the GAS tank ATR.
