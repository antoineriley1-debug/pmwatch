# PS60 Pine Scripts

TradingView Pine Script v5. Each file is a complete script — paste the whole
thing into the Pine editor (select all → delete → paste), never a snippet.

## Files

- **PS60_Desk_Plus.pine** — the upgraded desk. All 11 spec upgrades applied
  on top of the running v1 source: tight box with outlier rejection (master
  OFF by default), auto-pivot second entry off the tight-box edges, open-line
  fix, half-step ATR levels (OFF by default), whole-numbers overhaul with
  labels + touch alerts, price labels + price-scale registration on every
  reference line, locked premarket/after-hours, per-feature toggles and
  colors, earnings reaction bar with break alerts (OFF by default), and the
  probability upgrades (verdict bar, raw counts, sample-context line,
  earnings-break stats, tooltips throughout).
- **PS60_Second_Entry_Backtester.pine** — separate lower-pane strategy.
  Tests the auto-pivot second entry off the tight-box edges with remaining
  ATR as the target filter. Full Strategy Tester report plus a custom stats
  table (win rate, target hit rate, typical run, fakeout rate, sample line).
- **PS60_Scanner.pine** — watchlist scanner: one script, up to 15 tickers,
  runs the tight-box auto-pivot second-entry engine on each via its own
  5-minute data pull, status table, and a single alert() covering every
  ticker ("Any alert() function call").
- **PS60_Desk_Plus_v1_original.pine** — the source as received, archived as
  the rollback copy. Do not edit.

## Conventions locked in

- ATR: 14-day default, RMA, prior COMPLETED day, static intraday.
- Day rollover keys off the calendar date (year*10000+month*100+day) — never
  ta.change(time("D","0930-1600")), which goes na across extended-hours bars.
- Day high/low seeds from RTH bars only.
- Spent ATR level labels read "1x ATR Traveled <price>".
- Never name a variable `line`, `label`, or `box`.
- All new features default OFF or to current behavior.
- The probability sample rebuilds from loaded history on every recompile;
  300-day cap.
