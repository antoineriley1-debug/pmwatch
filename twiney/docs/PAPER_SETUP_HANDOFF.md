# Handoff: set up Twiney's IBKR paper account and sign TED into it

You are helping Twiney on his own computer (Windows). Paste-ready: everything you need is on this page.
Talk to him in plain English, short sentences, one step at a time.

## The three jobs

1. **Set up his IBKR paper trading account** (or confirm it exists and get its username).
2. **Share his live account's market data with the paper account**, so paper gets real-time quotes and Level II.
3. **Sign TED (his trading desk) into the paper account** and confirm it shows PAPER with live data.

## Ground rules (do not break these)

- **Never type, read out or store his passwords or 2FA codes.** When a login screen comes up, stop and let
  Twiney type them himself (IBKR also sends a push to the IBKR Mobile app to approve).
- **Paper only.** Do not change anything that would let TED trade the live account. In TED, SETTINGS →
  Trading → **Allow live** stays OFF. The live TWS port 7496 is not used.
- **Place no orders.** Not in TWS, not in TED. TED starts DISARMED; leave it that way.
- **His Quant Data API key is already in TED's config.** Never print it, paste it or send it anywhere.
- IBKR's menus get renamed. If a menu below isn't where this page says, look for the same words on the
  page (or in IBKR's help search) and tell Twiney what you see before you click anything that saves.

## What TED is (so the rest makes sense)

TED = **Twiney Execution Desk**. It's a trading program that runs only on his computer. It's written in
Python and shows its screen in his web browser at `http://127.0.0.1:8765`. It does **not** log in to IBKR
itself. It connects to **TWS (Trader Workstation)** on the same computer through the TWS API: TWS has to be
running and logged in first, and TED attaches to it on a port.

- **Which account TED trades** is whichever account TWS is logged into. Paper accounts have an ID starting
  with **DU**; TED detects that and shows **PAPER account**. A live account (ID starting with **U**) is
  refused for orders.
- **Port:** TWS paper listens on **7497** (TED's default). TED's port is in TED → SETTINGS → IBKR.
- **Where TED lives:** the folder Twiney unzipped `TWINEY.zip` into: `...\TWINEY\twiney\`. It starts with
  **`start_twiney.bat`** (double-click). `start_demo.bat` is the practice mode with fake data (no IBKR); don't
  use it for this.
- **His settings** (port, Quant Data key, plays, layout) live in `C:\Users\<him>\TWINEY\config.json`. He
  never edits that file by hand; TED's SETTINGS button does it.
- **Needs:** Python 3.10+ ("Add Python to PATH" ticked when installed), and IBKR's TWS API Python package
  (`ibapi`). If TED says `ibapi` is missing: install the **TWS API** from IBKR (interactivebrokers.github.io,
  "Stable" for Windows, default folder `C:\TWS API`), then double-click **`install_ibapi.bat`** in the TED
  folder. It should end with "ibapi installed OK". Do not `pip install ibapi` from PyPI (old, wrong version).

## Job 1: the paper trading account

1. Open the IBKR **Client Portal** (interactivebrokers.com → Log In → Client Portal). Twiney logs in with his
   **live** username and password himself.
2. Go to **Settings → Account Settings** (person icon, top right). Find **Paper Trading Account** and click it
   (or the gear next to it).
3. If there is no paper account yet, request/create one. If there is one, note the **paper username**. It's
   separate from his live username. Write down the **account ID** as well (it starts with **DU**).
4. If Twiney doesn't know the paper password, use **Reset Paper Trading Account Password** on that page.
   He types the new password himself.
5. A new paper account can take a little while to become usable (IBKR says up to a day). If the paper login
   is refused right after creating it, that's why.

## Job 2: share the market data with paper

1. On the same **Paper Trading Account** page in Client Portal, find **"Share real-time market data
   subscriptions with paper trading account?"** → **Yes** → **Save**.
2. This takes effect at IBKR's side, usually **within 24 hours** (often the next day). Until then, paper shows
   delayed data or none.
3. Check his **live** account has the subscriptions TED needs: **Settings → Market Data Subscriptions**. US
   stocks real-time (e.g. NYSE / NASDAQ / Cboe One / US Securities Snapshot and Futures Value Bundle). For
   TED's **Level II**, a depth feed: **NASDAQ TotalView-OpenView** and/or **NYSE ArcaBook**. For options,
   **OPRA (US Options Exchanges)**. Don't buy anything without Twiney's OK; just tell him what's there and
   what's missing.
4. **Important:** with shared data, only **one** session gets real-time data at a time. If he's logged into
   the **live** account in TWS or the IBKR mobile app while paper TWS is running, paper loses the live data.
   TED then says "another session is logged in with this user and is taking the live data (10197)". So log
   out of live everywhere while using paper.

## Job 3: sign TWS into paper, then start TED

1. Open **TWS** (Trader Workstation). On the login screen pick **Paper Trading** (the Live / Paper switch),
   then Twiney types the **paper** username and password.
2. In TWS: **File → Global Configuration → API → Settings** (on Mosaic layouts: **Edit → Global
   Configuration**):
   - **Enable ActiveX and Socket Clients**: ON
   - **Read-Only API**: OFF (TED needs to place paper orders later)
   - **Socket port**: **7497**
   - **Allow connections from localhost only**: ON
   - **Trusted IPs**: `127.0.0.1`
   - Click **Apply**, then **OK**.
3. Double-click **`start_twiney.bat`** in the TED folder. A black window opens (leave it open) and the desk
   opens in the browser. If TWS pops up "accept incoming connection?", click **Accept**.
4. **Check it worked.** All of these should be true:
   - Top/status bar: IBKR **connected**, **PAPER account** with the **DU…** ID.
   - **MKT light green "LIVE"** (not amber DELAYED / QUIET, not red NO DATA). In a closed market, amber QUIET is
     normal.
   - Type `AAPL` in the symbol box (top left) and Enter: the chart fills, Time & Sales moves, Level II shows sizes.
   - TED → **SETTINGS → IBKR**: port **7497**, market data type **1 · live**.
5. **If the data is wrong**, look in TED's **MESSAGES** panel:
   - **354 / 10089 / 10090 / 10168 / 10189 / 2152**: paper doesn't have the market data yet. Job 2 is still
     pending at IBKR (wait up to 24 h) or the subscription is missing on live.
   - **10197**: someone is logged into the live account somewhere else. Log out there.
   - **"Read-Only API"** / orders refused: untick Read-Only API in TWS (step 2).
   - TED can't connect at all: TWS not logged in, API not enabled, or the port isn't 7497 on both sides.
   - Level II empty but quotes OK: no depth subscription (TotalView / ArcaBook).

## When you're done, tell Twiney

- The paper username and account ID (DU…). Not the password.
- Whether data sharing is switched on, and whether it's live yet.
- What TED shows: connected / PAPER / MKT light / Level II working or not, and any MESSAGES codes.
- Which market data subscriptions he has and which are missing (TotalView or ArcaBook for Level II, OPRA for
  options).
