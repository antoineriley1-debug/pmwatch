# OPTION MONEY (2026-10-17)

What the option market says about the stock you are on, read for the PS60 trade. Flow backs up the setup, it never
replaces it: Daily room → 60-minute pivot → confirmation → second entry → build → pay yourself → runner to MP.
Nothing here places an order.

## The six reads

| read | what it is | the question it answers |
|---|---|---|
| OPTION MAX PAIN | the strike where this week's options pay out the least; price tends to be pulled toward it on expiry day. Not the PS60 max pain (where you are wrong, the stop): always called OPTION MAX PAIN | pay yourself / runner on expiry days |
| BIG STRIKES | the 3 strikes with the most option money above price and the 3 below. Hedging on those options tends to slow price there or hold it: more supply / demand in the way | is there room from the pivot to the MP? |
| CALL vs PUT MONEY | the day's running total: calls bought at the ask minus sold at the bid, minus the same for puts | confirmation: is the option money with the break? |
| EXPECTED MOVE | how far the options say the stock moves by the expiry (± dollars) | is the MP inside what is priced in? |
| OPENING MONEY | open interest added overnight, calls against puts | is somebody building and holding? |
| AT THE ASK | on the contract you trade: % traded at the ask against at the bid today | do I add, or are they selling into me? |

Where each one comes from is shown in grey beside it:
- **QUANT DATA**: their tools (net drift, exposure by strike, max pain, open interest by strike, term structure,
  contract trade sides), when your key opens them.
- **FLOW / CHAIN OI / CHAIN IV**: the desk's own: the option flow it already pulls, the IBKR option chain's open
  interest and implied volatility, the option tape.
- **PRACTICE**: on the practice market, made the same way from the practice chain and flow.

## Where you see it

- **The stock chart**: OPTION MAX PAIN as a dashed purple line, the BIG STRIKES as lines on the right half (green-blue
  = call money, pink = put money, thicker = more money), CALL−PUT money as a line across the volume pane (above the
  middle = calls ahead today). Anything off the chart gets a ▲ / ▼ tag on the top / bottom edge.
  ⚙ CHART SETTINGS › OPTION MONEY switches each one off.
- **PLAY SETUP**: the six reads in one block, then the checks against your play:
  - "MP 4.20 · options expect 3.10 by 10/24: the target is past what is priced in"
  - "big strike 360 between the pivot and the target: pay yourself into it"
  - "expiry today: option max pain 355 is against the long"
  - "option money leans PUTS today (−$2.1M): against the long"
- **The option chart header**: AT THE ASK % · AT THE BID % on that contract today.
- **DESK SCORE panel**: THE ODDS and QUANT DATA TOOLS (with the CHECK button).

## THE ODDS (the data collection)

Every call on THE DESK SCORE (second entry live, CLEANED UP, a level taken on a close, a breakout with speed, a
program, calls / puts pounded, the open read) now keeps what the option money said at that moment, in the call's
direction:

- CALL vs PUT MONEY today: WITH / AGAINST / EVEN; and over the last 15 min: WITH / AGAINST
- BIG STRIKE ahead (within half an ATR): IN THE WAY / CLEAR
- OPTION MAX PAIN: TOWARD / AWAY
- EXPECTED MOVE room left: ROOM / STRETCHED
- OPENING MONEY: WITH / AGAINST / EVEN

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

SETTINGS › Option money: on / off, how often each tool is asked (net drift every 60 s, the strikes every 5 min, max
pain and the expected move every 15 min, open interest every 30 min), at most 60 calls a minute for all of it (Quant
Data allows 240; the flow feed uses 12), how many big strikes, what counts as "ahead", the lean threshold
($250K), and a tool's path if Quant Data ever moves it.
