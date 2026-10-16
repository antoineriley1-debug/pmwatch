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
WATCH / PASS · CLEAR / THIN · the lean (sellers have the tape / buyers have the tape / neutral) · regime (up / down /
chop) · attempts (TOOK / FAILED) · buyers took / sellers took / bounced / rejected / defended / reclaimed / lost ·
breakout / breakdown with speed / without speed · buy / sell program · SOMEBODY KNOWS SOMETHING · THE DESK SCORE
(HIT / MISS / FLAT) · buyers are trying / sellers are trying.

"Rising 60-minute support" is the one allowed use of the word support.

## Forbidden, always

resistance · support (except the phrase above) · trigger (say pivot) · iceberg · dark pool (say large orders) ·
stack · door · box · zone · ribbon · fading · stale · gone · "into supply is not MP" · order block · fair value gap ·
liquidity sweep / grab · smart money concept · imbalance · breaker · mitigation · RSI · MACD · Fibonacci · stochastic ·
Ichimoku · "support and resistance" · "key resistance" · "failed breakout" (say price hit supply) · any module or
object name invented outside Dan's teaching.

## How a wrong word gets fixed

Replace it in place with the PS60 word, in every file it touched, including comments and tests, then rebuild the
page and run the tests. Tell Twiney it was there and that it is gone. Never defend the word.
