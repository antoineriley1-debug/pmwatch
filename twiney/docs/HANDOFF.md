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
- **Proposed, not built**: a print "flying" from the ladder row to Time & Sales for big prints, and a buyers-vs-sellers
  dollar gauge on the tape header. He asked for ideas first; the plan is in the conversation and below:
  chip lifts off the ladder row when size comes off and a matching print lands within a second, slides to the top of
  T&S over ~400 ms, gated by the BIG threshold; one tape (not two) with a split header bar of $ at the ask vs $ at
  the bid over the last minute.
- **Proposed wording split**: `SHORTS SQUEEZED` for a clean trend that left shorts underwater, keep `SHORTS TRAPPED`
  for the reversal shape.
- A stop line does not grow with adds: after ADD rungs or adding size, re-drag the stop to resize it (the exit guard
  trims stops when you reduce).
