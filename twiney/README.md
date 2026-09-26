# TWINEY COMPLETE v1.0

A read-only IBKR order-flow workstation built around PS60 levels. **There is no way to place orders.**
It sends only market-data requests. The client class also blocks the order calls
(`placeOrder`, `cancelOrder`, `reqGlobalCancel`, `exerciseOptions`, `reqIds`), which raise before anything reaches TWS.

## Quick start (double-click)
- **Windows:** `start_demo.bat` to try the demo, `start_twiney.bat` to connect to TWS.
- **Mac:** `start_demo.command` / `start_twiney.command` (first time: right-click → Open).

The launchers create `config.json` and `plays.json` from the examples if they are missing. You still need Python and IBKR's `ibapi` package (steps 3–4 below).

## Workflow
All commands run from this `twiney/` folder.

1. `cp plays.example.json plays.json`, then put in your PS60 plays. The example prices are placeholders.
2. `cp config.example.json config.json`, then set the port: 7497 for TWS paper, 7496 for TWS live, 4002 for Gateway paper, 4001 for Gateway live.
3. Install IBKR's official TWS API Python package so `ibapi` is available. Download the TWS API from IBKR, then run `python -m pip install .` inside `source/pythonclient`. The `ibapi` package on PyPI is an old 9.x build, so don't use it.
4. Start TWS or IB Gateway. In the API settings, enable socket clients and **enable "Read-Only API"** as a second safety layer. Make sure your account has market-data permissions, including depth.
5. `python run_twiney.py`
6. The dashboard opens at `http://127.0.0.1:8765` and only binds to loopback.

Other modes:

| Command | What it does |
|---|---|
| `python run_twiney.py --demo` | Synthetic feed with no IBKR connection. It is labelled DEMO everywhere. |
| `python run_twiney.py --replay recordings/X.jsonl` | Re-runs a recording and compares its calls with the ones made live |
| `... --replay X.jsonl --speed 5` | Paced replay (5x) with the dashboard |
| `... --replay X.jsonl --override` | Replays using the current `config.json`/`plays.json` so you can tune thresholds |

## What it does
- **L1 on every play** (`reqMktData`).
- **Ranks every symbol** by fractional distance to its PS60 **trigger and second entry**, whichever is closer.
- **Three full-depth slots** go to the closest symbols. Each slot gets Smart Depth (`reqMktDepth`, 10 rows requested, 5 shown) plus tick-by-tick prints (`reqTickByTickData AllLast`).
- **Slot rotation uses hysteresis.** A challenger must be 15% closer than the worst incumbent, and that incumbent must have held its slot for at least 20 s. If IBKR rejects a depth request (309/10092), that symbol is skipped for 30 s.
- **Watched levels.** The trigger, second entry and any `extra_levels` are watched on both bid and ask. TWINEY also auto-tracks big inside levels (≥ 2,000 shares). Many levels are tracked at once.
- **Records every raw event** to `recordings/*.jsonl` (L1, depth ops, prints, resets, slot changes, errors and alerts) for replay or audit.
- **One dashboard**, with one pane per ladder:
  - **Plain-English headline.** For example: "Price is approaching your trigger 128.40 — 6¢ above it", "A SELLER keeps reloading at 128.40 (your trigger): 6,200 shares traded into it, refilled 5x", "The SELLER at 128.40 got CLEANED UP". It also says what that means for the PS60 play.
  - **Chart:** 1-minute candles with IBKR history at startup, a 1m/5m toggle, and buy/sell volume. Your trigger, 2nd entry, extra levels, target and stop are drawn as labelled lines with a zone band. Green/red bubbles show shares absorbed into resting buyers/sellers at watched levels. R/C/P markers show reload, cleaned-up and pulled calls. Your working orders are drawn as lines too.
  - **Level-memory ladder.** Every price row remembers the last 15 minutes: shares sold into the bid and bought from the ask there, how many times the size came back after being hit (●), and a glowing **BUYER ×n / SELLER ×n** tag when a reload is confirmed. Your levels and your orders are tagged on their rows. The ladder stays centered on price.
  - **Time & sales** with prints at your levels tagged.
- **Pane controls:**
  - Panes keep a fixed screen position. If a symbol changes, a banner says so.
  - **Pin** a symbol from a pane or from the plays list so it never rotates.
  - **Auto-rotate ON/OFF** in the header.
  - A ladder with a live reload is never rotated away.
  - Drag a pane's corner to resize it. Sizes are remembered; **Reset layout** clears them.
- **Orders · positions · fills (view only):** pending orders, positions with P&L, and today's fills, read from IBKR (`reqAllOpenOrders`, `reqPositions`, `reqExecutions`). Orders are placed and changed in TWS.
- Plus: the plays list with plain-English distance to each level, feed health, and TWS messages.

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
twiney/safety.py         read-only guard
twiney/dashboard.py      local HTTP server (GET only) + static/dashboard.html
twiney/recorder.py       JSONL recorder;  twiney/replay.py  replay + comparison
twiney/sim.py            demo feed
```

## Tests
`python -m unittest discover -s tests -v`

This runs 68 tests covering the book, reload verdicts, 317 resets, ranking/rotation, a fake TWS session (reconnect, 1100/1101, 309, rotation cancels), the safety guard and source scan, replay fidelity and the dashboard.
One test checks the guard against the real `EClient`. It only runs when `ibapi` is installed.

## Before connecting to a live-data session (handoff checklist)
These could not be checked in the build environment because IBKR's download site was not reachable there:
- [ ] Install the official `ibapi` and re-run the tests. The EClient guard test must run, not skip.
- [ ] Confirm the callback signatures in `twiney/ibkr.py` match your installed version: `error` (both pre- and post-10.35 forms are handled), `updateMktDepthL2(..., isSmartDepth)` and `tickByTickAllLast`.
- [ ] Confirm the size units on your feed. Depth and tick-by-tick sizes should be shares (10.x Decimal). If they come through in lots, adjust `reload.*_shares` accordingly.
- [ ] Market-data entitlements: depth for each venue you need (for example NASDAQ TotalView), plus tick-by-tick. Look for errors 354/10089/10092 in the Feed Messages panel.
- [ ] With paper TWS, pull the network or restart TWS and check the reconnect, 1100/1101/1102 handling and depth resubscription.
- [ ] Watch for an error 317 in a live session. The book should empty and resync with no `PULLED` calls.
- [ ] Replay the first real recording (`--replay`) and check that `replay N / recorded N` matches.
