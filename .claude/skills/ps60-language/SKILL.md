---
name: ps60-language
description: "**THE PS60 LANGUAGE RULE (utmost importance)**: on Twiney's desk every word about stocks or the market is a PS60 word, the way Dan Shapiro teaches it, and nothing else. Read this before writing, coding, naming, commenting, documenting, speaking or teaching anything that touches price, levels, the tape, the book, option flow, charts, trades or the market. Trigger on any market, stock, trading, chart, level, tape, Level II, option, flow, PS60 or desk topic, and on any chat reply to Twiney about the market."
---

# The PS60 language rule

Twiney's instruction, verbatim in intent: *"You're forbidden to speak about anything pertaining to stocks or the
market with any other kind of terminology outside of PS60 theory. Do not incorporate your own bullshit into my
strategy."* This is a rule, not a preference. It applies to chat replies, code, variable and function names,
comments, docs, commit messages, the desk's screen text, the voice, alerts, the DESK AI's knowledge and its answers.

## Before you write anything about the market

1. Say it in PS60 words. If the word you reached for is not in the allowed list, do not use it.
2. If PS60 has no word for the thing, describe it in plain English using the PS60 words around it. Never borrow a
   word from another method, indicator set or trading vocabulary.
3. Grep what you touched for the forbidden words before you finish. Tests guard some of them
   (`tests/test_story.py`, `tests/test_levelverdict.py`); the guard list there is the floor, not the ceiling.

## Allowed (PS60, Dan Shapiro / Access A Trader)

supply · demand · pivot · confirmation · second entry · build · measured potential (MP) · ATR · cash flow · runner ·
max pain · remount · bounce · rejection · sneaky pivot · macro channel · micro channel · option flow · reload buyer ·
reload seller · RELOADING · STILL THERE · NOT RELOADING · CLEANED UP · PULLED · large orders · large size · pay yourself ·
breakeven · scale · the 50-day · the 200-day · the 5-day (orange) · VWAP · Bollinger · linear regression · prior-day
high / low / close / open · premarket high / low / close · after-hours high / low / close · high / low of day · the
open · 60-minute candle · Daily · 5-minute · sweep · block · hedge · premium · weeklies · out of the money · READY /
WATCH / PASS · CLEAR / THIN · who is in control (SELLERS IN CONTROL / BUYERS IN CONTROL / NEITHER SIDE IN CONTROL) · regime (up / down /
chop) · attempts (TOOK / FAILED) · buyers took / sellers took / bounced / rejected / defended / reclaimed / lost ·
breakout / breakdown with speed / without speed · buy / sell program · SOMEBODY KNOWS SOMETHING · THE DESK SCORE
(HIT / MISS / FLAT) · buyers are trying / sellers are trying.

"Rising 60-minute support" is the one allowed use of the word support.

## Twiney's own words (they override everything else)

- Buyers and sellers, always first. Bulls and bears only now and then in the storyline (about one line in five), and
  never on the screen strips: they back up buyers and sellers, they never replace them.
- Who is in control: SELLERS IN CONTROL / BUYERS IN CONTROL / NEITHER SIDE IN CONTROL ("sellers are still in control",
  "buyers are trying, but sellers are still in control").
- The voice and the story, as it happens: "buyers are paying higher prices to get in" / "sellers are accepting lower
  prices to get out".
- The T&S read, the option chart, PLAY SETUP (what happened): BUYERS PAID UP TO GET IN / SELLERS SOLD DOWN TO GET OUT;
  the Level II column headers: PAID UP / SOLD DOWN. The hover explains it: a buyer wanted in now, so they paid the
  seller's price; a seller wanted out now, so they took the buyer's price.
- NEW MONEY OVERNIGHT (open interest added overnight), OPTION FLOW LEAN (counted in prints: call prints vs put prints
  buyers paid up for), OPTIONS EXPECT (the expected move), OPTION MAX PAIN (never just "max pain", which is the stop).
- Option flow calls name the print that just hit, its own premium, strike, expiry and side: never a total of many
  prints ("$3M of calls"). Repeats are a count ("x4 on this strike in 30 min"), never added-up dollars.
- A level is TAKEN only after it held: a close through it, then price stays through it the whole hold time. Say how
  long ago and how it held (strong / holding / not strong / lost).

## Forbidden, always

resistance · support (except the phrase above) · trigger (say pivot) · iceberg · dark pool (say large orders) ·
stack · door · box · zone · ribbon · fading · stale · gone · "into supply is not MP" · order block · fair value gap ·
liquidity sweep / grab · smart money concept · imbalance · breaker · mitigation · RSI · MACD · Fibonacci · stochastic ·
Ichimoku · "have / has / own the tape" (say in control) · "lifting the offer" / "hitting the bid" / "at the ask" / "at the bid" on the screen or in the voice (say paid up / sold down) · "support and resistance" · "key resistance" · "failed breakout" (say price hit supply) · any module or
object name invented outside Dan's teaching.

## How a wrong word gets fixed

Replace it in place with the PS60 word, in every file it touched, including comments and tests, then rebuild the
page and run the tests. Tell Twiney it was there and that it is gone. Never defend the word.
