# The VPS test day (2026-10-13): what was fixed, what is left

The agent that runs TED on the VPS tested it end to end against the paper account and wrote up sixteen findings
(`TED_CLAUDE_CODE_HANDOFF.md`). This build answers them. BUILD stamp in `twiney/static/dashboard.html`.

| # | finding | done | what changed |
|---|---|---|---|
| 1 | a move of a bracket stop / target silently refused (10326, OCA group) | **yes** | the adapter keeps IBKR's own OCA group name from `openOrder` and re-sends that on a move; codes above 10000 on one of our orders are treated as the order's answer: a refused move rolls the desk's record back to the old price and says ORDER REJECTION. A move now answers `pending: true`, "IBKR confirms, or refuses and the old price stands" |
| 2 | a move skipped the new-order price checks | **yes** | a moved entry gets the same 5% band check as a new order |
| 3 | a stop could be moved through the market | **yes** | a SELL stop at or over the bid / a BUY stop at or under the offer is refused: "it would fire at once" |
| 4 | PLAY bracket with no lines went out bare | **yes** | with no stop and no target drawn, a stop `auto_stop_dollars` away ($1 by default) goes out with the entry and the desk says so; with that setting at 0 the order is refused: "the bracket has nothing to attach". The AUTO 2nd entry (lines join as drawn) and a REVERSE you confirmed are the two exceptions |
| 5 | bad size coerced (0 → 100, 1.5 → 1) | **yes** | 0, negative, fractions and words are refused with the reason; the default size only when the size is omitted |
| 6 | IBKR 399 (queued until 04:00) labelled ORDER REJECTION | **yes** | 399 → INFORMATION "QUEUED by IBKR"; 2161 (price capped) → WARNING; 2109 → INFORMATION |
| 7 | no overnight (20:00–04:00 ET) stock venue | no | not built: needs the OVERNIGHT venue routing and its own session rules; left for its own build |
| 8 | option orders after hours "held" but refused | **yes** | refused plainly before anything is sent: "the options market is closed: a contract order is REFUSED now, nothing is queued — send it after the 9:30 ET open"; the SIM light's words say the same |
| 9 | flatten left working entries; no flatten-all | **yes** | FLATTEN cancels the symbol's working orders even when flat (answers `cancelled: n`); **FLATTEN ALL** (`/api/trade/flatten_all`, hotkey "FLATTEN ALL" with a confirmation) cancels every order then closes every position |
| 10 | cancelling a bracket stop also cancelled its target (OCA), no warning | **yes** | the paired exit is read before the cancel and re-sent on its own (same side, size, price, no group); the answer carries the warning; if the re-send fails it says UNPROTECTED |
| 11 | Level II partial (TotalView / OpenBook not on the API login), crossed book not flagged | **partly** | the DOM header says SOME VENUES MISSING when IBKR sends 2152, and CROSSED BOOK when the book's best bid is at or over its best offer; `health.crossed` and `depth_partial` in the snapshot. The subscription itself is yours: Client Portal › Settings › Paper Trading Account › share market data, and TotalView + OpenBook for the API |
| 12 | market page slow (417 names, timeouts) | no | not changed; the history pull wants batching and a retry list, its own build |
| 13 | heavy polling (169 KB every 250 ms) | **mostly** | every JSON answer over 2 KB is gzip-compressed when the browser accepts it: the snapshot went 274 KB → 43 KB on the practice desk. Diffs per pane are not built |
| 14 | error 162 (another login) silent | **yes** | a 162 "connected from a different IP" says, once a minute, ANOTHER IBKR LOGIN is taking the data, as a CONNECTION error; the DOM header shows OTHER LOGIN for five minutes; 10197 does the same |
| 15 | grade of an unknown key ok; raw Python error on a bad price; garbled bracket text | **yes** | `/api/grade` answers 400 for a call the desk never made; a price or size that is not a number answers "price must be a number, not 'abc'" / "shares must be a whole number"; the SENT line reads `cash flow 1: 50 sh @ 10.49 + runner: 25 sh @ 10.60` |
| 16 | futures | no | not wanted on this desk (Twiney: stocks and options only) |

Tests: `tests/test_audit_vps.py` (13: sizes and prices, the bare bracket, the two move guards, flatten when flat,
flatten all, the OCA partner re-sent, the grade key, 399 / 10326 / 162 in the adapter, the crossed book and
missing venues). Browser: the two DOM probes unchanged, 14/14 and 12/12.

## For the agent on the VPS

Drop the new `TWINEY.zip` at `/opt/ted/TWINEY.zip`, run `sudo bash /root/vps/update.sh`, then during RTH:

1. Move a bracket stop on the ladder: the desk says MOVE SENT, then either the new price stands or ORDER REJECTION
   with the old price back. No silent "MOVED".
2. Try to move the long's stop above the ask: refused with "it would fire at once".
3. Cancel one leg of a QUARTERS bracket from ORDERS: the other leg comes back on its own, the answer says so.
4. FLATTEN with buys working and no position: they are cancelled.
5. Watch the DOM header: SOME VENUES MISSING until TotalView / OpenBook are on the API login.

## Round two (BUILD 20261014-0147 and later)

| # | finding | done | what changed |
|---|---|---|---|
| 7 | no overnight stock venue | **yes** | 8:00 PM to 3:50 AM ET, Sunday evening through Friday morning, a stock LIMIT goes to IBKR's OVERNIGHT venue (DAY, outside RTH) and the desk says so; a stop-limit stays on SMART and the desk says it waits for the 4:00 AM session. SETTINGS › Trading › "Overnight (8 PM - 3:50 AM ET): stock limits go to IBKR's OVERNIGHT venue" (`trading.overnight_venue`). A moved overnight order stays on the venue |
| 12 | market page slow | **yes** | an unanswered history request is asked again after 40 s (twice) instead of failed for the day; six in flight, 0.2 s apart (`market.in_flight`, `send_gap_s`, `timeout_s`); the daily cache already carried across restarts |
| 13 | heavy polling | **yes** | the page tells the server who it is and gets only the pieces that changed: every top-level piece and every pane field by field (the ladder and the tape move every tick, the studies, story and levels hardly at all); gzip on top. Practice desk: 274 KB a poll → 53 KB the first time, then ~10 KB |

Tests: `tests/test_vps_round2.py` (the window, the routing, the switch, the diffs). Browser: the DOM probes 14/14 and 12/12 on the diffed page.
