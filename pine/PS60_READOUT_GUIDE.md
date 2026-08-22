# HOW TO READ A PS60 DESK+ SCREENSHOT — INSTRUCTIONS FOR AI

You are being shown a screenshot of the PS60 Desk+ trading indicator's readout
(a stack of colored text rows at the top-center of a TradingView chart), and
possibly its companion scanner (a table of ticker rows). Decode it using ONLY
the rules below. Do not invent numbers that are not on screen. When a value is
cut off or unreadable, say so instead of guessing.

## CORE CONCEPT: THE GAS TANK
- The "tank" is the stock's ATR: 14-day average true range, RMA-smoothed,
  taken from the prior COMPLETED day. It is frozen all session (levels never
  drift intraday).
- "Gas used" = today's true range so far: max(high-low, |high-prevClose|,
  |low-prevClose|) — gaps count as fuel burned.
- "x ATR traveled" = used / tank. 1.0x = a full typical day. 1.61x = the stock
  ran 161% of a normal day.
- All dollar distances in the readout are also expressed as gas: "$3.60 gas
  needed" = the move required; "in the tank" = fuel remaining today
  (tank - used); "only $X in the tank" = the target needs more than what a
  typical day has left — probably not today's move.

## THE READOUT ROWS, TOP TO BOTTOM
1. GAS row. Live session: "GAS 31% left · 0.69x ATR traveled" with color =
   green (>=40% left), yellow (>=15%), red (below). Market closed:
   "GAS waiting 9:30 · tank N" — no session running; tank shown is the LAST
   session's tank (it updates once at the next open, then freezes).
2. Usage row. Live: "used A / tank B · left C". Market closed it becomes the
   LAST SESSION RECAP: "last session traveled 1.1x ATR · used A of B tank".
3. DAY AFTER verdict (colored). "DAY AFTER a <bucket> day: <verdict> ·
   typical Nx". Buckets classify the last completed day by tanks burned:
   quiet (<0.5x), normal (0.5-1x), extended (1-1.5x), blowout (1.5x+).
   Verdicts, from this symbol's own full daily history:
   - USUALLY KEEPS RUNNING (teal): 40%+ of next days ran 1.2x+ — momentum
     personality, big days chain, respect breakouts.
   - USUALLY COOLS OFF (yellow): 50%+ of next days stayed under 0.8x —
     mean-reversion personality, expect digestion, distrust morning breakouts.
   - NO STRONG LEAN (gray): mixed history.
   "typical Nx" = average next-day travel after that bucket.
4. DAY AFTER detail. "930 days like the last one since Jan 18 '15: 255 ran
   again (1.2x+) · 273 normal · 402 chopped (under 0.8x)". The three counts
   always sum to the total. This is the receipts for row 3 — cite these counts
   when giving confidence.
5. TODAY block (navy/cyan rows, each prefixed "TODAY ·"). Intraday
   continuation odds: today's ATR progress at 30-minute checkpoints is matched
   against up to 300 stored days (from a 30-minute data pull, not capped by
   chart history). Rows: odds line, color verdict (STRONG GO >=70% continued,
   LEANS GO >=55%, COIN FLIP >=45%, USUALLY STALLS below; "(thin sample)"
   when under 10 matches), raw counts, and sample context (n of total, date
   span, match %). "odds start at 10:00" = first checkpoint not reached yet.
   "no similar days in sample" = nothing matched today's profile.
6. EARN block (amber/gold rows, prefixed "EARN ·"), only if enabled:
   earnings-reaction-range break history — breaks, % that ran +1x beyond the
   edge, % faked out (closed back inside), typical run, resolution speed.
7. SUPPLY row (red) / DEMAND row (green), if enabled. "SUPPLY (selling)
   714.94 · PDH + EMA9 D + whole (7 levels) · $1.50 gas needed · $5.22 in the
   tank · THIN · ↑bias". Decode: zone price; named member levels (up to 3,
   then "+N more") with total count — more independent level types agreeing =
   stronger zone; gas needed vs gas remaining; THIN = under 0.25x ATR of room,
   not worth taking (especially on options); LINE IN THE SAND (N touches
   held) = level tested N times recently with no close through it — a
   defended battle line; ↑/↓bias = which side of the daily 50 SMA.

## SCANNER ROWS (if the screenshot shows the ticker table)
Format: TICKER · STATE · details. States, in setup order:
- NO BOX (with reason: "range 3.4x ATR > 2x" or "N wild bars"): no qualified
  consolidation — no pivots, no signals. A box must fit within the height cap
  with no wild bars, or it does not exist.
- DISTRIBUTION · box T / B: qualified box, price inside, edges = future pivots.
- BREAKOUT/BREAKDOWN WATCH (orange) over/under <price>: no box, but a
  completed bar confirmed past the prior day's high/low — continuation setup.
- RETAIL FLUSH ▲/▼ · push P · liquidation, wait (yellow): first wave broke a
  box edge; chasers being flushed; DO NOT CHASE; P = push extreme so far.
- INSTITUTIONS L/S · trigger P (green): flush complete, second wave staged;
  entry fires if price reclaims P.
- ENTRY L/S · trigger P (purple): price is at the trigger now.
Active rows append: "grade A+/A/B/C" (checklist score: bias alignment +2,
tank covers trip +2, 3+ levels at target +2 / 2 levels +1, armed second entry
+2 / earlier +1, not THIN +1, line in the sand +1; 8-10 A+, 6-7 A, 4-5 B;
it is a quality checklist, NOT a backtested probability) and a
"→ SUPPLY/DEMAND ..." target in the same format as row 7.

## HOW TO WRITE YOUR BREAKDOWN
1. State what the last/current session did (gas rows) in one sentence.
2. State the stock's personality and next-day lean (day-after rows), citing
   the counts.
3. If TODAY rows are live, give the intraday odds with sample context.
4. Map the battlefield: nearest demand and supply zones, their strength
   (level count, line in the sand), and whether the tank can reach them.
5. Give the actionable read: which setups the evidence favors, which to
   distrust, and what invalidates the read. Never present a checklist grade
   or a thin sample as a probability. This is analysis, not financial advice.
