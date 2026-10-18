# TED ladder / DOM — install, launch, IBKR, paper trading, architecture, limitations

TED (Twiney Execution Desk) is a local workstation: a Python engine talks to Interactive Brokers TWS or IB
Gateway over the API, and the desk is a single page served on `127.0.0.1` only. The ladder (LEVEL II panel)
is the order-entry surface. Nothing here ever runs live money unless you unlock it in `config.json`, and the
desk refuses live accounts until you do.

## Install

1. Python 3.10+ (3.11 recommended). No third-party Python packages except IBKR's own API.
2. The IBKR API package: run `install_ibapi.bat` (Windows) or install it from TWS API → `source/pythonclient`
   (`pip install .`). The desk runs without it in practice / replay mode.
3. Copy `config.example.json` to `config.json`. Put your Quant Data key in `quantdata.api_key` through
   SETTINGS (never in chat or git).

## Launch

| What | Windows | Mac |
|---|---|---|
| IBKR paper (TWS running, paper login) | `start_twiney.bat` | `start_twiney.command` |
| Practice desk (no TWS, synthetic market) | `start_demo.bat` | `start_demo.command` |
| Replay a recording | `start_replay.bat` | `python3 run_twiney.py --replay recordings/<file>.jsonl` |

The desk opens at `http://127.0.0.1:8787` (demo: 8799). `python3 run_twiney.py --help` lists every flag.

## IBKR configuration (TWS)

1. Log in to TWS with your **paper** account (the login screen has the paper toggle).
2. File → Global Configuration → API → Settings: **Enable ActiveX and Socket Clients** on, **Read-Only API**
   off, **Allow connections from localhost only** on, socket port **7497** (paper; live is 7496 and the desk
   refuses it unless unlocked), trusted IP `127.0.0.1`.
3. Market data: the paper account must carry your market-data subscriptions (IBKR propagates them from the
   live account; errors 354 / 10168 / 10189 / 2152 in MESSAGES mean they have not arrived yet — ask IBKR to
   enable them for the paper account). Delayed data (market data type 3) gives charts only.
4. Level II needs a depth subscription (NASDAQ TotalView or ARCA Book for US stocks). Without it the ladder
   shows the inside quote and the tape, and DEPTH reads off.
5. `config.json → ibkr`: host `127.0.0.1`, port `7497`, `client_id` (any number not used by another API
   client), `market_data_type` 1 for live.

## Operating modes

| Mode | How it is chosen | What it means |
|---|---|---|
| **SIM** (PRACTICE) | `start_demo` or `--demo` | synthetic market, in-memory broker, nothing reaches IBKR |
| **IBKR PAPER** | TWS paper login (account `DU…`) | real quotes, paper orders through TWS |
| **IBKR LIVE** | a live account (`U…`) AND **Allow live** switched on in SETTINGS → Trading (confirmed, then RESTART NOW) | real money. The ladder's status strip pulses **LIVE TRADING** in red |

The desk starts DISARMED every launch. ARM (top bar) enables order entry; the day-loss lock disarms it for
the day. Closing a position is never blocked (FLATTEN, CLOSE, X, a reducing order).

## Paper-trading checklist

With TWS paper logged in and the desk launched:

```
python tools/acceptance.py --port 8787 --symbol AAPL --switch MSFT --reconnect
```

It checks, in order: connection · mode · ticker load · quotes · depth · a far-off limit placed, modified and
cancelled · a bracket (parent + stop + targets) · symbol switch with no stale data · FLATTEN (only if you hold
the symbol, and it asks) · reconnect (you restart TWS while it watches) · replay. Every line prints PASS, FAIL
or BLOCKED with the reason. Against the practice desk: `--port 8799 --demo --yes`.

## The ladder

- **SIMPLE** (default): BID · PRICE · ASK. Size drains as prints attack it (the bar behind the number is what
  is left of the most it showed in 90 s; a drop flashes −n, size back after a drop floats +n ↻). A confirmed
  reload buyer / seller is a solid green / red cell with ↻N and the $ that traded into him. Absorption is the
  thin line under the number. Fake size prints dim, big bold, huge gold. Option money is a mark on the row
  edge (green calls left, red puts right). Your orders are chips: click to cancel, drag to move. TIGHT adds
  HIT / PAID and CALLS / PUTS columns; WIDE adds the who tags. The button in the ladder bar cycles them.
- **Status strip** over the ladder: symbol, last, change %, bid / ask, spread, position, average entry,
  P&L %, market-data light, IBKR connection state, trading mode.
- **QTY** box and presets (`trading.qty_presets`) in the ladder bar; the ticket follows it.
- **Left click** a size: JOIN mapping (default) buys at that price on the bid side, sells on the ask side;
  HIT mapping (COLS menu) trades against the size instead. The price is taken when you press, and the ladder
  holds still until you release.
- **Right click** a row: BUY / SELL limit there, BUY / SELL stop-limit triggered there, market (when
  `trading.allow_market`), join bid / ask, move a selected order here, cancel bid orders / ask orders / all,
  FLATTEN, REVERSE, and STOP / TARGET / 2ND ENTRY here.
- **AVG** tag on the row nearest your average entry. Stops and targets are chips on their rows; drag them
  and the desk sends the modification and waits for IBKR's acknowledgment before the chip settles (a refused
  move snaps back and says so).
- **Brackets**: PLAY = the stop and target you drew (plus PS60 cash-flow exits when on); or a template
  (`trading.bracket_templates`: stop −$, up to three targets at +$ with share splits), picked on the ticket.
  Every target is paired with its own stop (OCA). Trailing stops are not sent (see limitations).
- **COLS** menu: show / hide columns, auto-centre on price, rows above / below (also
  `ladder.half_rows`), row height, text size, the click mapping, HOW TO READ IT. Column widths drag and are
  saved per layout.
- **Hotkeys** (top bar → Hotkeys): Esc cancels the symbol's working orders (configurable), plus buy / sell /
  join bid / join ask / cancel all / flatten / reverse / arm, all rebindable.
- **Order flow**: BIG TAPE (builders and blocks), the 5 s / 15 s delta and the pressure state in PLAY SETUP
  (`twiney/orderflow.py`; thresholds in `config.json → orderflow`). The side of a print is inferred from the
  quote it hit, so the delta is labelled ESTIMATED, never exchange data. Reloads are described as what was
  observed (refilled N times, $ traded into it), never as intent.

## Options from the desk

The OPTION CHAIN panel (docks beside PLAY SETUP; tab, drag or close it like any panel) is option order entry:

- **Chain**: expiries and strikes come from IBKR (`reqSecDefOptParams`, SMART) once the underlying is
  resolved; pick the expiry and CALLS / PUTS. The practice desk makes its own chain (weekly expiries, strikes
  on the usual steps) and prices it with a Black-Scholes model, labelled PRACTICE prices.
- **Quotes and Greeks**: the strikes around the spot are quoted live (`reqMktData` on each contract; IBKR's
  `tickOptionComputation` supplies delta, gamma, theta, vega and implied vol — the model tick wins). The row
  shows BID / ASK / LAST / Δ / IV; the position row shows its net delta. Quotes for rows you scroll away from
  are cancelled, held contracts keep theirs.
- **Open**: CT = contracts per click, PX = your limit (blank = at the touch: ask to buy, bid to sell). BUY /
  SELL on a row sends a LIMIT DAY order on that contract through the same gate as a stock order, in real
  dollars (price × multiplier × contracts); never market, never without a price. The confirmation box shows
  the contract, the limit and the dollars (ONE-CLICK skips it). Working option orders list under the chain
  with a cancel.
- **Manage**: the position shows in POSITIONS with OUT 25 / 50 / 75 / … / X and IN +1 / +½ / +1× / +…, and
  the row's X in the chain closes it. Option fills go to the journal, separate from the stock P&L.
- IBKR needs option market-data permissions on the paper account for live quotes (OPRA); without them the
  chain lists but rows show no quote and ask for a typed price.

## Architecture

| Concern | Module |
|---|---|
| IBKR connection, reconnect backoff, subscriptions, contract details, orders, positions, executions | `twiney/ibkr.py` |
| Depth book (INSERT / UPDATE / DELETE, normalized, SMART or direct) | `twiney/book.py` |
| Engine: symbols, ladder memory, levels, alerts, snapshot for the page | `twiney/engine.py` |
| Order management, gate (modes, caps, day-loss lock), brackets, flatten, reverse, auto 2nd entry | `twiney/trading.py` |
| Order-flow analytics (delta, pressure), tape, big tape | `twiney/orderflow.py`, `twiney/tape.py` |
| Reload / conviction (REAL / FAKE size) | `twiney/levels.py`, `twiney/conviction.py` |
| PS60 (second entry, MP, grade) and the `SignalProvider` interface | `twiney/ps60.py` |
| Option flow, conviction board, big money | `twiney/flow.py`, `twiney/board.py`, `twiney/bigmoney.py` |
| Options: contract keys, practice chain and pricer, Greeks | `twiney/options.py` |
| Persistence: plays, layouts, alerts, recordings, grades, structured log | `plays.json`, `layouts.json`, `recordings/` (`desk.log` = JSON lines) |
| Replay (pause / play / speed / step / restart / scrub) | `twiney/replay.py` |
| HTTP API and the page | `twiney/dashboard.py`, `twiney/static/dashboard.html` |
| Configuration and the SETTINGS schema | `twiney/config.py`, `twiney/settings.py` |
| Tests | `tests/` (`python3 -m unittest discover -s tests`) |

Connection states: CONNECTING → CONNECTED; DISCONNECTED → RECONNECTING (backoff) → CONNECTED; DATA_LOST /
FEED_DOWN while TWS loses its farms; DELAYED when the market data type is delayed. On reconnect the session
re-requests positions, open orders, executions and depth, and the broker's view wins over the desk's.

Every IBKR error is categorized (INFORMATION · WARNING · MARKET DATA · ORDER REJECTION · CONNECTION ·
PERMISSION · FATAL) in MESSAGES and in `recordings/desk.log`; the original code is kept.

## Completion gate (what was validated here, what is blocked)

| Gate | Status |
|---|---|
| builds, launches | PASS (practice desk, Playwright-driven page checks) |
| automated tests pass | PASS (`tests/`, 309 tests) |
| ticker lookup, depth ladder updates, order place / modify / cancel, fills and positions sync, P&L %, brackets, stops, targets, flatten, symbol switching, replay | PASS against the practice desk and the in-process IBKR fake (`tests/test_ibkr.py`); the acceptance script passes in `--demo` |
| IBKR paper connection, live market data, paper order round trips, reconnect | **BLOCKED here**: no TWS in this environment. Run `tools/acceptance.py --reconnect` against your paper login; the desk's own paper account must carry the market-data subscriptions (IBKR side) |

## Known limitations

- Trailing stops are not sent to IBKR (templates carry `trail` for later; the stop is a stop-limit).
- Option spreads (multi-leg combos) are not built; each leg is its own order.
- Column reorder is by layout (three ladder layouts), not by dragging a header.
- The delta is estimated from the quote each print hit; IBKR does not provide aggressor-side trade data.
- Depth beyond the inside quote needs an IBKR Level II subscription; without it the ladder still trades.
