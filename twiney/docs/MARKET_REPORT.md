# MARKET ANALYSIS DETAILED REPORT

The MARKET button on the desk opens this page in its own window (`/market`). It rebuilds Twiney's TradingView
boards inside TED on daily closes, so the page and the boards agree, and adds what a Pine board cannot see: all
500 S&P members by name and by sector. DESK AI reads every number on the page and writes the report.

It is the backdrop, never a call. It sets how much and which way Twiney leans; his PS60 setup (pivot, confirmation,
second entry) sets when.

## What is on the page

| section | from which board | what it shows |
|---|---|---|
| MARKET STATE | Market State v1.1 | CLEAR / CAUTION / CONFIRMED / LATE, days in the state, the action for it, what flips it, the four-state ladder with the share of days and times entered since 2007 |
| RECESSION STEPS | Recession Steps v1.2 | the five steps as a track (lenders nervous, fewer stocks, banks lag, recession warning, jobs), each with its meter (5 weak days, 5 thin days, 2 of 3 bank clues, 3 warning points, 0.50 Sahm), the full read of each step on click, what to watch next |
| BREADTH | Recession Steps v1.2 | share of S&P stocks above their 50-day and 200-day, the 30 and 45 lines, a week and a month ago, a year of both lines with the state shaded behind them, what the gap says |
| DESK AI | new | the written report (the call, what is driving it, where the money is going, the relationships, the scenarios with their counts, what to watch, what it means for the PS60 desk) and a question box; WHAT THE AI WAS GIVEN under every answer |
| SCENARIOS | new, from the history counts | what happens next for the step the sequence is on: what has to happen (the number and its line), how many times it has happened before (N of M), and what to do if it comes |
| RELATIONSHIPS BOARD | Relationships Board v1.5 | the sixteen lines, each PAST THE LINE / WATCH / CLEAR / DATA CHECK with its cushion, which way it moved this week, and on click what it is and what a rise or a fall means; the key rows carry ★1 ★2 ★3 |
| RATE BASKETS | Rate Baskets v1.3.0 | the 13 sector funds in the three rate baskets (and FOLLOWS THE ECONOMY) against the S&P on the week, month and year; the winner, rates, what it means, the rotation, the blueprint, winner vs loser, the tells |
| WHO IS CARRYING IT | Macro Vision | the average stock (RSP) against the S&P, the chip fund and the big names, the sectors on the last session |
| LEADERS AND THE STOCKS LAGGING | new | the S&P members leading and lagging on the day, week or month, new 52-week highs and lows, each sector's share of members above their 50-day and 200-day |
| HISTORY | Recession Steps + Market State | per step: times on, average and longest run, how often the next step followed within 40 trading days, last on; per state: share of days, times entered |
| FEEDS | new | every feed loading, old or missing; symbols IBKR could not give |

The tests are the boards' own tests, word for word where the boards have words. Words the PS60 language rule does
not allow were changed (TRIGGERED reads PAST THE LINE, "just triggered" reads JUST TURNED ON, "old leader fading"
reads losing ground).

## Where the numbers come from

- **IBKR** (your TWS / Gateway login; historical daily bars, no extra market data): SPY (plain and dividend-adjusted),
  HYG (adjusted), the bank fund (XLF, adjusted), the 13 sector funds, RSP, SMH, copper (COMEX continuous future), the
  ~500 S&P 500 members, and any big name that is not a member.
- **FRED** (free, no key): the 10-year (DGS10) and 2-year (DGS2) rates, unemployment (UNRATE), weekly jobless claims
  (ICSA), WTI and Brent oil, the high-yield credit spread (BAMLH0A0HYM2).
- **The S&P member list** ships with TED (`twiney/knowledge/sp500_members.csv`); UPDATE THE S&P MEMBER LIST on the
  page fetches today's list from the public datasets list on GitHub.

The first load asks for 20 years of daily bars per symbol, four at a time (SETTINGS > Market report > in flight), so
it takes a few minutes and never crowds the desk's own chart requests. After that only the missing days are asked,
once a day after the close. Everything is kept in the data folder (`TWINEY/history/macro`), so the page opens with the
last report at once, before IBKR connects. Today's bar is skipped until 4:15 PM ET: the report reads closed days.

**Breadth is counted by TED** (TradingView's S5FI / S5TH are not on IBKR): the share of today's members above their
own 50-day / 200-day. Older years count companies that joined the index later, so they read a little stronger than
the official numbers did. The page says so.

## SETTINGS > Market report

enabled · members · years · in flight · FRED · confirm days (2) · hold days (5) · follow window (40) · tie points
(0.25) · rate move (0.05) · carried points (1.5) · bank fund (XLF / KBE) · copper (HG / CPER) · chip fund · big names
· DESK AI writes it after the refresh · practice members · practice seed.

## Practice and replay

The practice desk builds the page from synthetic closes, labelled PRACTICE · SYNTHETIC, NOT THE MARKET. A replay
shows the last saved closes and asks for nothing.

## Code

`twiney/macro.py` (the boards, pure: closes in, report out), `twiney/macrofeed.py` (IBKR / FRED / cache loading),
`page_src/market.html` (the page; `build_page.py` copies it to `static/market.html` with the BUILD stamp),
`twiney/ai.py` (jobs `market` and `marketask`), `tests/test_market.py`.
