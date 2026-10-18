# DAN'S DAILY — the Market Notes email on the desk

Every evening Access A Trader sends the Market Notes: the day's notes, the **Current Pivot Watchlist** (a ticker,
its pivot or pivots, `Short` when it is a short, the stars) and the **OPTION FLOW** lines. TED reads that email
from Twiney's Gmail and puts it on the WATCHLIST panel. Watch only: nothing is traded from it.

## Set it up once

1. Google account › Security › 2-Step Verification › **App passwords**: make one for "TED". Sixteen letters. That is
   the only password TED ever sees; never the real one.
2. SETTINGS › **Gmail (Dan's Market Notes)**: your Gmail address, the app password, on. The sender
   (`support@accessatrader.com`) and the subject word (`Watchlist`) are filled in; the read times are 06:30 and
   19:45 New York. SAVE.
3. The app password lives in `config.json` in the data folder and nowhere else: not in git, not in a recording, not
   in an export (it is a SECRET field, shown as KEY SAVED).

## What it does

- Reads the newest Market Notes at startup, at each read time, and when you click REFRESH on the panel. Over IMAP
  (`imap.gmail.com`), read-only; the mailbox is never changed.
- Parses the text with rules, never a model: a row is `TICKER pivot [& pivot] [Short] [N⭐]`; a flow line is
  `BUYER|SELLER size TICKER expiry strikeC|P[@price] [premium]`. A line that does not read cleanly is left out.
  Nothing is ever guessed.
- Keeps the newest result in the data folder (`dan-watchlist-latest.json`): after a restart the desk shows it at once,
  until the next read.
- On the WATCHLIST panel, on top: DAN'S DAILY · the date · when it was read · REFRESH. Each name: the pivot(s), SHORT
  or LONG, the stars, and `+ ADD` or `ON THE DESK`. Under it, the flow lines from the notes.
- **Click a name:** if it is not on the desk it is added as a play with Dan's pivot and side, then opened; if it is
  already there it opens (and gets Dan's pivot when it has none). Your own pivot is never overwritten.
- A Gmail problem (wrong app password, no network) is said on the panel and in MESSAGES, never hidden.

## Code

`twiney/danmail.py`: `parse` / `parse_message` / `fetch_latest` / `DanMail` (refresh, tick, view). The engine carries
`engine.dan`, the snapshot key `dan`, `/api/dan/refresh`. Config `gmail.*`, SETTINGS section "Gmail (Dan's Market
Notes)". Tests `tests/test_danmail.py` (the parser on a synthetic email, plain and HTML; the schedule; a Gmail error;
storage; the snapshot). Browser `scratchpad/dan.js`.
