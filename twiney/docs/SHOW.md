# THE SHOW — your broadcast screen

**SHOW** in the desk header opens it in its own tab (address: the desk's address + `/show`). It is linked to your
watchlist and has clean charts, drawing tools and the broadcast pieces. It is read-only: nothing on it can place or
cancel an order.

The **stage** (what viewers see) is a fixed picture. Everything in the dark panel on the right is for you only.
**H** hides the panel. `/show?clean=1` is the stage alone.

## Formats: where you post

| button | size | for |
|---|---|---|
| YOUTUBE 16:9 | 1920 x 1080 | YouTube Live, YouTube videos, Twitch, X, Facebook, Instagram Live from a computer (landscape) |
| INSTAGRAM 9:16 | 1080 x 1920 | Instagram Live from a phone layout, Reels, Stories, TikTok, YouTube Shorts |
| FEED 1:1 | 1080 x 1080 | Instagram / X feed posts and carousels (SNAPSHOT each chart) |

**SAFE AREA GUIDES** shows red bars where the app puts its own buttons and comments (9:16: the name and LIVE badge at
the top, the comments at the bottom, the side buttons). Keep your drawings out of the red, then turn the guides off
before going live.

## How to go live

- **YouTube (16:9).** Use OBS (free). Add a **Window Capture** of the SHOW tab, or a **Browser Source** at
  `https://<your desk address>/show?clean=1`. With the Browser Source, click **Interact** once and sign in. In OBS,
  Settings › Stream › YouTube: connect your account or paste the stream key. Your camera goes on top in the CAMERA
  SPOT.
- **Instagram Live from the computer.** Instagram gives a stream key under **Live Producer** (on instagram.com:
  create › Live video › streaming software). Paste the server URL and key into OBS, Settings › Stream › Custom. Set
  the OBS canvas to 1080 x 1920 and use INSTAGRAM 9:16 here.
- **Reels / Shorts / TikTok clips.** Record in OBS at 1080 x 1920 with INSTAGRAM 9:16, or record 16:9 and post the
  same video to YouTube. For a post, SNAPSHOT saves the chart with your drawings, name and show as a picture.
- **Both at once.** OBS with a multi-stream plugin (or a restream service) sends one 16:9 show to YouTube and X while
  you go live on Instagram from the phone.

## Layout

- **1 BIG**, **2 SIDE BY SIDE** or **4 GRID** (16:9). The 9:16 format stacks 1 or 2 charts with the watchlist as chips.
- Click a watchlist name: it goes into the chart with the red frame. Double-click a chart: it fills the screen
  (double-click again: back).
- **WATCHLIST RAIL** shows or hides the list. Click MINE / DAN'S at its top to switch to Dan's watchlist.

## The charts: your desk chart, nothing else

The SHOW draws with the desk's own chart code (copied in when the page is built), so it looks like the chart you trade
on:
- **MY DESK CHART LOOK** (on by default) uses your desk's screen (white / blue / pink / your colour / dark) and its
  candles: Dan's green and red with black wicks and borders on a light screen, or your own candle colours.
- **MOVING AVERAGES**: your SMA and EMA lines in the desk's colours. On the daily, the 34 / 65 / 89 EMA too. Any line
  you switched off on the desk (IND) stays off here.
- **BOLLINGER**: 20, 2.
- **GAS + ATR**: prior day high / low / close, premarket and after-hours high / low / close, high / low of day, the
  ATR levels. Intraday only; off on the daily, like the desk.
- **AIRSPACE**: daily and weekly bounce and rejection.
- **UNVISITED** highs and lows.
- **PS60 LINES**: your pivot, 2nd entry, stop, target and partials, labelled at the left.
- **VWAP** and **VOLUME**.
- **LABELS S / M / L / XL**: the study label size for the camera.

Each layer switches on and off with one click. Timeframes: 1, 2, 5, 15, 60 min and daily. The mouse wheel zooms.
MOVE + drag pans; drag the price scale to squeeze or stretch it. Double-click resets. Everything you draw sits on top.

## Drawing tools (keys)

| key | tool |
|---|---|
| 1 | PEN: freehand, the sports-broadcast telestrator |
| 2 | SQUARE |
| 3 | TREND LINE |
| 4 | ARROW |
| 5 | PRICE LINE: a dashed line with its price tag |
| 6 | MP RULER: drag from the pivot to the target; shows the dollars, the % and the times-ATR |
| 7 | TEXT |
| 8 | CIRCLE |
| 9 | HIGHLIGHT: a wide see-through marker |
| L | LASER: a glowing red pointer that leaves nothing behind |
| S | SPOTLIGHT: drag to dim everything but the part you are talking about |
| E | ERASER: click a drawing |
| Z | undo |
| X | clear this chart |
| M / Esc | back to MOVE |
| B | the WE'RE LIVE intro |
| H | hide / show the panel |

Six colors. Drawings stay on their ticker at their price and time, so they are still there tomorrow and on every
timeframe.

## The broadcast pieces

- **Top bar**: your show name with a pulsing LIVE dot, the segment and its line, the clock in ET, the market status
  (PREMARKET with the countdown to the open, MARKET OPEN, AFTER HOURS).
- **Segments**: one click each. THE WATCHLIST, PREMARKET PREP, LIVE TRADING, TRADE OF THE DAY, THE BREAKDOWN, MARKET
  RECAP, Q&A, TOMORROW'S PLAYS, or type your own. Leave the line under it blank and it reads the chart's PS60 plan
  (side, pivot, 2nd entry, target, stop).
- **Lower third**: your name and @handle with the segment.
- **Ticker crawl**: your watchlist scrolling with price and % on the day, plus FOLLOW @handle. Slow / normal / fast.
- **POTENTIAL SETUP** banner: the desk's calls on your watchlist slide in by themselves (2nd entry, pivot broken,
  READY, bounce / rejection, target / stop, fills). The red label is yours to pick (POTENTIAL SETUP by default, or type
  your own). AUTO switches the desk's calls off. Type your own line and press Enter. SAY IT has the browser read it
  out; it is off by default so you do the talking.
- **WE'RE LIVE intro**: a red sweep with WE'RE LIVE, for the top of the show.
- **Scenes**: STARTING SOON with a countdown, OPEN COUNTDOWN to 9:30, BE RIGHT BACK, THANKS FOR WATCHING, LIVE (back
  to the charts).
- **LAST TRADE CARD** and **TODAY'S SCORECARD**: your closed trades in R (or % on options), wins and losses.
- **VIEWER QUESTION**: type the question and the @name and it shows as a card while you answer.
- **CAMERA SPOT**: a marked corner for your camera in OBS. GREEN FILL lets OBS key it.
- **Looks**: NETWORK (red, white, navy, the news-desk look), NIGHT DESK (TED's graphite and gold), NEON, DAYTIME
  (light).
- **SHOW-SAFE** (on by default): no dollars and no sizes on screen. Cards show R and %. Turn it off only if you want
  dollars shown.
- **SNAPSHOT**: saves the chart with your drawings as a PNG for a post.
- **REPLAY THE DAY**: plays the session back candle by candle from the open, for the recap.

## Segment boards, chat, sponsor, sound, hotkeys

- **MARKET IN 60 SECONDS** (F6): SPY, QQQ and the four biggest movers on your watchlist, one full-screen card each,
  timed to fill a minute, with a red bar running along the bottom. Each card shows the price, the % on the day and the
  PS60 plan if you have one (side, pivot, 2nd entry, target, stop). Press it again to stop.
- **THE PLAYS** board (F4): a full-screen table of your plays (name, side, pivot, 2nd entry, target, stop) with Dan's
  stars. Type your own title in the box under it. Esc closes it.
- **LEVEL II** layer: the book drawn on the chart, big, for a teaching segment: waiting sellers over waiting buyers,
  the size as a bar. The desk only has the book for names it has open on a ladder; for any other name it says so.
- **MY TRADES** layer (on by default): your stock trades today on the chart. Blue ▲ (long) or ▼ (short) where you got
  in, the exit in green (a win) or red, joined by a dashed line, with the R.
- **SPONSOR / COURSE corner**: type the headline and the line under it (your link). ON shows it every N minutes for
  N seconds. SHOW NOW (F8) shows it once.
- **YOUTUBE LIVE CHAT**: paste a YouTube API key and the live video's ID (or its address), then CHAT ON. New messages
  come in every 7 seconds and list in the panel. Click one: it goes up as the VIEWER QUESTION card. CHAT ON SCREEN
  shows the last four messages on the stage. The key stays in this browser only; it is never sent to TED or saved on
  the server.
  - Getting the key: console.cloud.google.com › new project › APIs & Services › Library › "YouTube Data API v3" ›
    Enable › Credentials › Create credentials › API key.
- **SOUND** (on by default): a short sound when the POTENTIAL SETUP banner comes in, on each MARKET IN 60 card, and
  on the WE'RE LIVE intro. Made in the browser; OBS picks it up with the page's audio.

### Hotkeys (for a Stream Deck: set each button to "Hotkey")

| keys | what |
|---|---|
| Shift+1 … Shift+8 | the eight segments, in the order of the buttons |
| Alt+1 | LIVE (back to the charts) |
| Alt+2 / Alt+3 / Alt+4 / Alt+5 | STARTING SOON / OPEN COUNTDOWN / BE RIGHT BACK / THANKS FOR WATCHING |
| F2 | LAST TRADE CARD |
| F3 | TODAY'S SCORECARD |
| F4 | THE PLAYS board |
| F6 | MARKET IN 60 SECONDS |
| F7 | VIEWER QUESTION card |
| F8 | the sponsor corner, now |
| B | WE'RE LIVE intro |

The SHOW tab must be the window in front for the keys to land (OBS Browser Source: right-click › Interact).

## Still for later

- A trade recap from a recording: pick a recorded trade from the journal and replay it with its fills marked.
