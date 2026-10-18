# THE CALL BOOK and THE PHRASE LIST (2026-10-17)

## THE CALL BOOK (panel: CALL BOOK)

Every call THE DESK SCORE judges gets a card. Open the panel from PANELS › CALL BOOK.

- **CALLS**: the list, newest first. Pick today, 2, 7, 30 or 90 days and one kind of call. 🎯 = the target came
  first, ⛔ = the stop came first, 📷 = it has a picture, ✎ = you wrote a note.
- Click a card to open it:
  - the words the desk said, the time, the symbol, the price
  - 5 / 15 / 30 minutes later, and which came first: the target (or the MP) or the stop. Your play's target and
    stop when they point the call's way, otherwise half an ATR for the target and a quarter ATR for the stop
    (SETTINGS › Call book)
  - for a level that was taken: how it held 10 minutes later (STRONG / HOLDING / NOT STRONG / LOST)
  - HIT / MISS / FLAT (the DESK SCORE rule, at 15 minutes)
  - who was in control, the last 30 prints on the T&S, the top of the LEVEL II, the option flow prints on that stock
    in the last 15 minutes (each print on its own), the candles with the levels, the option money reads
  - the picture of the chart, the T&S and the flow (taken by the page when the desk is open on that stock)
  - 👍 / 👎 and a note: click, type, SAVE
  - REPLAY: opens the recording at that moment in the replay desk
- **WEEKLY REVIEW**: every kind of call, worst first: how many, the hit rate, hit · miss · flat, target or stop
  first, your thumbs, the level-hold grades. Below it, every setting that changed in those days with the hit rate
  before and after the change.

Kept on the server in `/var/lib/ted/recordings/callbook/`: the cards forever, the pictures 60 days (SETTINGS ›
Call book changes both).

## THE PHRASE LIST (panel: CALL PHRASES)

The voice says each call in the desk's own line, or, in turn, a version you approved. Nothing is spoken until you
approve it.

1. Open PANELS › CALL PHRASES and click a call (for example A LEVEL TAKEN).
2. Click **WRITE VERSIONS**. The DESK AI writes a few in your words; after a few seconds they show in yellow as
   PENDING. A version that drops a number, adds one, or uses a word that is not yours is thrown out before you see it.
3. **APPROVE** the ones you like, **REJECT** the rest. **REMOVE** takes an approved one back off.
4. Or type your own line in the box and click **ADD**. Keep the numbers in braces, like `{level}` and `{price}`:
   the list under the box shows which ones that call has.

SETTINGS › Phrase list › use_approved off = the desk's own lines only. The list is kept in
`/var/lib/ted/recordings/phrases.json`.

## Running the DESK AI on your own computer instead of the server

1. Install Ollama on your PC (ollama.com) and run `ollama pull llama3.1:8b`.
2. Make Ollama listen on the network: Windows: Settings › System › About › Advanced system settings › Environment
   Variables › New: `OLLAMA_HOST` = `0.0.0.0`, then quit Ollama from the tray and start it again.
3. Install Tailscale on the PC and sign in with the same account as the server.
4. In TED: SETTINGS › AI › Ollama address = `http://<your-pc-name>:11434` (the name Tailscale shows for the PC),
   enabled on, SAVE.
5. The PC only needs to be on when you use the AI (WRITE VERSIONS, the recap, EXPLAIN...). When it is off, the desk
   keeps working and the AI buttons say Ollama is not answering.

## MY READ (the tag on each ticker tab)

How you see a stock, set by you only. Click the small tag next to the ticker on its tab (it says READ when nothing
is set): BULLISH, BEARISH, NEUTRAL or HANDS OFF, a one-line why, and tick "for the week" to keep it until Friday's
close (otherwise it comes off at today's close). CLEAR takes it off.

- It shows on the tab, the watchlist and THE SHOW.
- If your read and the Daily read disagree, the desk says so once.
- A call against your read is marked AGAINST YOUR READ (or HANDS OFF); it is still said.
- An order against it gets a warning on the confirm (or a note with one-click on). It never blocks the order.
- THE CALL BOOK keeps it on every card. THE WEEKLY REVIEW shows the desk's hit rate with your read and against it,
  and how your own reads did: a BULLISH read is right when price closed over where it was when you set it.

## THE TRADE BOT (POSITIONS › the bar on top)

Paper only. Once you are in, it manages the trade the PS60 way. Shares and contracts on the same stock are managed
side by side, each on its own.

1. With the stock on screen, click **BOT OFF** so it says **BOT ON**. It takes over the position you hold (or the next
   one you open there).
2. **TRAIL 5 | 60**: the runner's stop trails under the last finished 5-minute or 60-minute candle.
3. **KIND**: AUTO (it reads the Daily: 15+ daily candles in one range and an MP of 2+ ATR = GIVE IT ROOM, else PAY
   YOURSELF EARLY), or pick ROOM / EARLY yourself, any time.
4. **PAY AT $**: your own pay-yourself distance for this stock (blank = a quarter of the ATR, $0.50 to $1.00).
5. **TAKE BACK**: you manage it from here; the bot moves nothing more.

What it does: the stop at max pain (the prior 5-minute low / high), or it keeps the stop you set on a contract;
GIVE IT ROOM = break even after 1 ATR and pay yourself only near the MP; PAY YOURSELF EARLY = half off at the pay
distance, then break even; then the runner trails. It tightens into a ROAD BLOCK (a Daily level, a key level, your
sneaky pivot, a 60-minute moving average of 20 or slower in the way) and when the market turns against the trade for
two minutes while it is green. It gets out when the level is graded LOST, a reload under it is CLEANED UP, or a
5-minute candle closes back through the pivot, and it never adds back.

Its read, live on the bar: THE PLAN (setup, pivot, 2nd entry, stop, MP, R), THE GOAL, EXPECTING, ROAD BLOCKS, IN THE
TRADE (from the entry, best / worst, the stop), WITH IT / AGAINST IT (who is in control, the option flow, MY READ,
VWAP), ON PLAN or CAREFUL. Every step goes into THE CALL BOOK. All the numbers are in SETTINGS › Trading › bot.

Hand management stays one click: 25 / 50 / 75, +½, BE and X on every row (shares and contracts), X asks once, a
message never covers a button, and a row never redraws while you are clicking it.

## THE SHOW: premium, sound board, theme, clips, posting

Open the SHOW (the SHOW button on the desk, or /show). Everything new is in the panel on the right:

- **The look**: the network top bar with your logo letter (PREMIUM › logo letter), a LIVE pill, and the index strip
  (SPY / QQQ / IWM / VIX when they are on your desk, and how many of your stocks are green).
- **PREMIUM**: MEMBERS BADGE (gold, top right: your own words), QR CORNER (paste your sign-up link: viewers scan it),
  BIG MOMENT ON CLOSE (a closed trade fills the screen with its R for five seconds; SHOW LAST TRADE replays it).
- **SOUND BOARD**: 12 pads, click or keys Q W R T Y U I O P [ ] ;. Right-click a pad to put your own sound on it.
  PADS / MASTER volume, MUTE ALL.
- **THEME MUSIC**: pick your file once (kept in this browser). PLAY / STOP (fades out), WITH THE INTRO (plays with
  WE'RE LIVE and STARTING SOON), LOOP, and DUCK UNDER MY VOICE (the music drops while you talk).
- **CLIPS**: START CLIPPING and pick THIS tab with its audio once. CLIP LAST 30s / 60s saves the moment; VERTICAL
  makes the 9:16 for Reels / Shorts / TikTok. They download to your computer.
- **POST**: WRITE CAPTIONS writes one for X, StockTwits, Threads, Facebook, Instagram and YouTube from the ticker in
  the red frame (price, move, your plan, MY READ). Edit it, then POST ON X / STOCKTWITS / THREADS opens the post with
  the caption in it (attach the clip); for Facebook, Instagram and YouTube it copies the caption and opens the site.

In OBS, add the SHOW as a Window Capture (or a Browser Source with ?clean=1) and tick "capture audio" so the pads and
the theme go out on the stream.
