# OPTION MONEY (2026-10-17)

What the option market says about the stock you are on, read for the PS60 trade. Flow backs up the setup, it never
replaces it: Daily room → 60-minute pivot → confirmation → second entry → build → pay yourself → runner to MP.
Nothing here places an order.

## The six reads

| read | what it is | the question it answers |
|---|---|---|
| OPTION MAX PAIN | the strike where this week's options pay out the least; price tends to be pulled toward it on expiry day. Not the PS60 max pain (where you are wrong, the stop): always called OPTION MAX PAIN | pay yourself / runner on expiry days |
| BIG STRIKES | the 3 strikes with the most option money above price and the 3 below. Hedging on those options tends to slow price there or hold it: more supply / demand in the way | is there room from the pivot to the MP? |
| OPTION FLOW LEAN | call prints against put prints that buyers paid up for, today and the last 15 minutes: counted, never added up in dollars | confirmation: is the option flow with the break? |
| OPTIONS EXPECT | how far the options say the stock moves by the expiry (± dollars) | is the MP inside what is priced in? |
| NEW MONEY OVERNIGHT | open interest added overnight, calls against puts | is somebody building and holding? |
| YOUR CONTRACT TODAY | on the contract you trade: % buyers paid up to get in against % sellers sold down to get out today | do I add, or are they selling into me? |

Where each one comes from is shown in grey beside it:
- **QUANT DATA**: their tools (exposure by strike, max pain, open interest by strike, term structure,
  contract trade sides), when your key opens them.
- **FLOW / CHAIN OI / CHAIN IV**: the desk's own: the option flow it already pulls (the FLOW LEAN is always counted here), the IBKR option chain's open
  interest and implied volatility, the option tape.
- **PRACTICE**: on the practice market, made the same way from the practice chain and flow.

## Where you see it

- **The stock chart**: OPTION MAX PAIN as a dashed purple line, the BIG STRIKES as lines on the right half (green-blue
  = call money, pink = put money, thicker = more money), the FLOW LEAN as a line across the volume pane (above the
  middle = more call prints today). Anything off the chart gets a ▲ / ▼ tag on the top / bottom edge.
  ⚙ CHART SETTINGS › OPTION MONEY switches each one off.
- **PLAY SETUP**: the six reads in one block, then the checks against your play:
  - "MP 4.20 · options expect 3.10 by 10/24: the target is past what is priced in"
  - "big strike 360 between the pivot and the target: pay yourself into it"
  - "expiry today: option max pain 355 is against the long"
  - "option flow leans DOWN (puts) today (4 call prints vs 11 put prints, buyers paid up): against the long"
- **The option chart header**: BUYERS PAID UP TO GET IN % · SELLERS SOLD DOWN TO GET OUT % · who is IN CONTROL on that contract today.
- **DESK SCORE panel**: THE ODDS and QUANT DATA TOOLS (with the CHECK button).

## THE ODDS (the data collection)

Every call on THE DESK SCORE (second entry live, CLEANED UP, a level taken on a close, a breakout with speed, a
program, calls / puts pounded, the open read) now keeps what the option money said at that moment, in the call's
direction:

- OPTION FLOW LEAN today: WITH / AGAINST / EVEN; and over the last 15 min: WITH / AGAINST
- BIG STRIKE ahead (within half an ATR): IN THE WAY / CLEAR
- OPTION MAX PAIN: TOWARD / AWAY
- ROOM LEFT IN WHAT OPTIONS EXPECT: ROOM / STRETCHED
- NEW MONEY OVERNIGHT: WITH / AGAINST / EVEN

Fifteen minutes later the call is judged HIT / MISS / FLAT as always (recordings/score.jsonl). THE ODDS add them up
across every day: for each read and answer, how many calls, the hit rate (green when 8 points better than all calls,
red when 8 worse) and the average move. Only the live market counts; the practice desk keeps its own.

Give it two to three weeks of market days before reading anything into it.

## Monday: start it

1. Click **UPDATE** on the desk (or the Hostinger paste) and wait for the page to come back.
2. Before 9:30, open **PANELS › DESK SCORE**. Under **QUANT DATA TOOLS** click **CHECK**. After about 10 seconds each
   tool says **OPEN** (your key has it), **NOT ON THIS KEY**, or **UNREAD** (it answered, the desk could not read it).
   Send a screenshot of that list.
3. Each tool's first answer is saved on the server in `/var/lib/ted/recordings/quantdata_tools/` (the answer only,
   never the key). If any says UNREAD, send what this prints (Hostinger Web console):
   ```
   head -c 2000 /var/lib/ted/recordings/quantdata_tools/*.json
   ```
4. Leave TED running every market day. Nothing else to do.

## Settings

SETTINGS › Option money: on / off, how often each tool is asked (the strikes every 5 min, max
pain and the expected move every 15 min, open interest every 30 min), at most 60 calls a minute for all of it (Quant
Data allows 240; the flow feed uses 12), how many big strikes, what counts as "ahead", the lean threshold
(3 prints), and a tool's path if Quant Data ever moves it.
