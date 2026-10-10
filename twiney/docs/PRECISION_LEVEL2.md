# Twiney's Precision Level 2 — build and test report

The Level II now opens as one ladder, the DOM, built to the handoff spec (`Twineys_Precision_Level2_Complete_Handoff`,
SPEC §1–§13). The tape, the chart, PS60, the option flow and the reload buyer / seller detector are untouched: the DOM
reads the same rows the other ladders read, from the same engine, and adds nothing of its own to the numbers.

## What it is

Six aligned columns, one price a row, the price column fixed in the centre:

| column | what it is | where the number comes from |
|---|---|---|
| WAITING BUYERS | shares resting to buy at this price now, with a bar against the biggest size on screen | the book (`row.bid`) |
| ACTUAL SELLING | shares that hit the bid at this price this session (or this visit: COLS) | the tape, read against the quote in force (`row.bk[2]` / `row.vs`) |
| LEVELS (rail) | every level on the row, stacked (+n, all on hover / click); the reload buyer / seller cluster ↻N | the chart's level registry (`row.lv`), the existing reload trackers |
| PRICE | one fixed-width column, the last-traded row framed | |
| ACTUAL BUYING | shares that lifted the offer at this price | `row.bk[1]` / `row.vb` |
| WAITING SELLERS | shares resting to sell now, with its bar | the book (`row.ask`) |
| TRADED AT PRICE | every confirmed trade at this price today (bought + sold + unclassified), with its bar | `row.bk[0]`, counted once per print on the server |
| $ HERE (optional) | (buyers + sellers showing) × price | |

A header line above the rows says what the data is: **LIVE / DELAYED / PRACTICE / REPLAY / DISCONNECTED**, SMART DEPTH
(every venue IBKR quotes) or ONE EXCHANGE'S BOOK or NO BOOK, the age of the quote and of the book, FEED OLD when the feed
is old, REFUSED with the reason when IBKR refused the book (and SETTINGS says what fixes it). ⌖ RECENTER appears when
you scrolled away from price and brings it back.

Motion: every bar eases to its new size in 160 ms (shrinking on a cancel and on a trade alike, never hiding the number).
A volume cell pulses once, 220 ms, only when the server's count for it GREW: a print landed. A size that falls with no
print shrinks and pulses nothing. Reduced motion (COLS) turns both off. The numbers are the server's: a skipped
animation never changes one.

Each print also drops a token into the row it traded at: its dollars into $ HERE when that column is on, its shares
into TRADED otherwise, red from the selling side and green from the buying side (the same drop engine the basket
ladder used; reduced motion turns it off).

Nothing sits above the rows but the data header: the story line, VWAP / 50-day, the pace bar and the off-ladder
level pills are off on the DOM by default, so the rows never jump when a strip appears or disappears. They live on the
chart, the STORY and the PS60 panels; COLS › "strips above the rows" brings them back on the ladder.

Settings (COLS on the ladder bar): session or rolling volume, colour-blind palette (blue / orange), reduced motion,
each column on or off, the $ column, the strips, rows, row height, text size. Everything persists in the browser.

The mode button cycles DOM → CANDLE → CLEAN → PRO. Pots and baskets are retired from the cycle (the server still counts
per-price trades the same way; the story and the scorecard use them).

## Event model (unchanged, now covered by tests)

- Depth operations (INSERT / UPDATE / DELETE per IBKR row) rebuild the book; a drop in displayed size is judged on the
  next quarter-second read against the prints that landed at that price in between: the traded part is FILLED, the
  rest waits one second for a re-quote and only then files as PULLED. Never an execution from a depth drop alone.
- Prints are keyed by IBKR time + price + size + exchange + their ordinal within the second: two real identical prints
  both count; a re-delivery after a reconnect is ignored.
- A reconnect or a 317 reset wipes the judgement window: the rebuilt book explains nothing and nothing is filed from it.
- Aggressor side: a print at the offer is a lift, at the bid a hit; a print outside the market now is read against the
  quote it traded in (the last second), else by the tick rule. Unreadable prints stay unclassified and count only in
  TRADED.

## The ten replay scenarios (SPEC §11) → `tests/test_precision_l2.py`

| # | scenario | test | result |
|---|---|---|---|
| 1 | 5,000 resting, 3,000 sells, drop to 2,000, 4,000 added, 6,000 showing | `Scenario1_HitThenRefill` | FILLED 3,000 / PULLED 0, stacked +4,000, TRADED unchanged by the refill |
| 2 | 5,000 → 2,000 by cancel alone | `Scenario2_CancelIsNotATrade` | TRADED stays empty, 3,000 PULLED, no pulse (no print) |
| 3 | reload buyer and seller at separate prices | `Scenario3_ReloadClusters` | one call each, cluster on its own price and side, refills and absorbed carried |
| 4 | cancel / add / execute interleaved, out-of-order prints, reconnect re-delivery | `Scenario4_OutOfOrderAndDuplicates` | 1,000 traded in 2 prints, the re-delivered print ignored (`dup_prints == 1`), rebuild not judged |
| 5 | a run through five rows | `Scenario5_FastRun` | each row keeps exactly its volume, one last-price row |
| 6 | session and prior-day levels | `Scenario6_SessionLevels` | the ladder's marks equal `key_levels` (one registry) |
| 7 | overlapping levels on one price | `Scenario7_OverlappingLevels` | all three kept on the row |
| 8 | no book / reconnect / old feed | `Scenario8_Degradation` | trades counted without a book, rebuild files nothing, FEED OLD reported |
| 9 | 5,000-print burst | `Scenario9_HeavyBurst` | every share counted once; ladder build < 250 ms (measured 1.6–3.2 ms) |
| 10 | resize and theme while animating | browser probe at four viewports | see below |

## Browser verification (Playwright, the practice desk)

`scratchpad/dom.js` at 1024×640, 1280×720, 1440×900 and 1920×1080: 14 checks each, all passing on the final build:
the DOM renders, seven aligned columns (compact words on a narrow ladder), one fixed-width price column, the data-state
header, no clipped numbers, one footer strip with the pin box inside it (the two overlapping bottom boxes are gone),
bars eased to their sizes, levels on the rail, execution pulses on prints (77 in 12 s of practice tape), colour-blind +
reduced motion applied (transition 0 s), RECENTER after a scroll, no page errors. The same probe on a recorded replay
(`demo-20261009-051240`, 5×) passes with the header reading REPLAY. Screenshots: `dom_<w>x<h>.png`,
`domlad_<w>x<h>.png`, `domreplay_1440x900.png` in the session scratchpad.

The burst / overlap / multi-cluster states (SPEC §12) are rendered synthetically by `scratchpad/domsyn.js` on top of
the live ladder: three levels on one row stack as one marker (+2) that opens to all of them on click, three reload
clusters (buyer RELOADING ↻6, seller STILL THERE ↻3, buyer CLEANED UP) sit in the rail without crossing into the
price, no number clips, every row keeps one height, a 90,000 share size reads HUGE with a full bar.
Screenshot: `domsyn_1440x900.png`.

Two layout defects found by the narrow viewport and fixed: a column's bottom window kept a fixed 300 px and left the
ladder 47 px tall (now the top window keeps at least 40% / 170 px); the chart's time axis threw on a tiny chart.

## Performance

| measure | value |
|---|---|
| server ladder build after a 5,000-print burst | 1.6–3.2 ms |
| full snapshot after the burst | 41 ms |
| page-side DOM motion per draw (bars + pulses, 27 rows) | 0.6–1.0 ms |
| draw cadence | the poll (≈ 4/s) plus the streamed ticker frames |

Nothing in the DOM drops events: all accounting is on the server, counted as prints and depth arrive; the page only
draws the latest snapshot.

## Feed limitations (honest list)

- IBKR allows **3 depth lines** per login across every application; the desk uses up to 3 (one goes to the charted
  contract when its book is on). A refused book is said on the ladder with the reason (code 309 / 10092).
- **SMART depth** needs NASDAQ TotalView (and ArcaBook / OpenBook) on the account (Twiney has them); an account without
  them gets the single-exchange book and the header says so.
- Aggressor side is **inferred** from the quote in force (IBKR prints carry no side); prints the quote cannot read stay
  unclassified and count only in TRADED.
- IBKR print times are whole seconds; the desk's own clock orders prints inside a second.
- Delayed data (market data type 3 / 4) is shown as DELAYED in the header.
- ACTUAL SELLING / BUYING for the session count prints seen since the desk connected, not the day's history.
- The practice desk is synthetic: its numbers test the plumbing, never the market.

## Not done / out of scope

- No order placement was added: a click on a size stages the usual order through the existing ticket, exactly as before.
- No plain-English battle read on the DOM rows (it lives on the story and the voice).
- Venue attribution per print beyond IBKR's exchange code is not available from the feed.
