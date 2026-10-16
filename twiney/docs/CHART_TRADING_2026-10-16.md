# Chart trading and the order block (2026-10-16)

## The stock chart

- The top line no longer shows LAST. **BREAK EVEN** sits next to the timeframe dropdown: it moves the stop on what
  you hold in this symbol to your entry (the shares, or the contract you hold on it, at what you paid). It is grey
  when you hold nothing here, and it says so when price is not past your entry yet.
- **Grabbing a line:** the cursor turns into a hand within 8 px of a line (stop, target, 2nd entry, pivot, a level,
  a working order). Press and drag to move it.
- **Double-click a line** to pick it up. It follows the mouse with no button held. Click once to drop it there, or
  press Esc to put it back. The move is saved like a drag.
- **Holding a contract on this stock (no shares):** one left click on the stock chart opens the contract's menu at
  that stock price:
  - STOP: the stock through this price sells the contract
  - TARGET
  - BREAK EVEN: the contract's stop goes to what you paid
  - CLOSE: every contract at the touch

  A double-click never opens this menu.

- **OPT picked (contract mode), not holding it yet:** a right-click on the stock chart is the contract's menu, never
  shares:
  - BUY n of the contract when the stock hits this price, or BUY now
  - 2ND / STOP / TARGET at that stock price: the lines trade the contract. The stock trading through the 2ND buys
    it, the STOP sells it, the TARGET sells it (or your %).

## A new 2nd entry: STOP and TARGET drawn for you, 2 to 1

Draw a 2nd entry and the desk draws the rest:
- **STOP**: tight, $0.20 away (under a long, over a short). SETTINGS › Trading › auto stop dollars.
- **TARGET**: 2 to 1 on that stop ($0.40 away). SETTINGS › Trading › auto target r.

Lines you drew yourself are never replaced. Drag either one to move it. Take the 2nd entry off before a trade and the
two the desk drew go with it. Auto target mode "supply" uses the next supply (demand on a short) instead, never closer
than the 2 to 1.

## The voice says prices like a trader

13.45 is "thirteen forty-five", 13.05 "thirteen oh five", 13.00 "thirteen dollars", 0.45 "forty-five cents", 152.50
"one fifty-two fifty". Never "thirteen point four five".

## PARTIAL targets (right-click the stock chart)

Holding contracts: right-click where you want some of them off. The menu has **PARTIAL sell [dropdown] when the stock
hits that price** and a **SET** button.

- The dropdown knows how many you hold. It counts whole contracts, never a part of one: "1 of 6, 2 of 6, 3 of 6 (half)".
- SET puts a green dashed **PART n** line on the chart. Drag it, or double-click it to pick it up, to move it. Right-click
  it and choose Remove to take it off.
- When the stock reaches it, that many contracts come off at the touch. The rest stay on with their stop and target.
- Several partials at different prices add up, never to more than you hold.

Holding shares: the same menu has **PARTIAL sell [10% … 75% of your shares] @ price** with SET. That rests a limit
order that only takes the position down, drawn on the chart as an order line you can drag.

## The option chart

- The bid / ask, delta and "practice model" words are gone from the top line.
- Holding the contract, the top line shows CLOSE (all at the touch) and BREAK EVEN. The STOP box (on the stock or on
  the contract) stays.

## The order block (bottom of ORDER ENTRY)

| holding | buttons |
|---|---|
| shares | SELL / BUY presets, ALL, **BREAK EVEN**, and a **STOP** box: type a price, SET |
| a contract | SELL 25% / 50% / 75%, **CLOSE**, **BREAK EVEN**, and a **STOP** box: ON the stock or ON CONTRACT, type a price, SET |

## BREAK EVEN, +5¢, +10¢, CLEAR, FLAT

On the top line of the stock chart, in the order block (shares and contract), on the option chart and in the left-click
contract menu:

- **BREAK EVEN** moves the stop to your entry. It always answers:
  - "stop moved to BREAK EVEN"
  - "BREAK EVEN already in place"
  - "your stop is already past break even: left where it is" (plain BREAK EVEN never pulls a better stop back)
  - "not yet: price is under it" (a stop there would sell at once)
  - "you hold nothing in AAPL"
- **+5¢ / +10¢** puts the stop 5 or 10 cents past your entry (past what you paid, on a contract).
- **CLEAR** takes every line off the chart, cancels every working order on the stock and its contracts, and turns
  every contract watch off. What you hold stays open (it asks first, and warns that it will have no stop).
- **FLAT** gets you out of the shares and every contract on the stock, now, at the touch. No confirm box: getting out
  never waits.

## UPDATE (the VPS)

The button is always in the header on the server: grey **UP TO DATE** when you have the newest build (click it to check
GitHub again), orange **UPDATE · build** when a newer one is out. The PRACTICE desk has it too: it asks the live desk,
which installs the build and restarts both (the practice desk comes back by itself).

When a newer build is on GitHub, the orange **UPDATE · build** button shows in the header. Click it and confirm: TED
downloads the build, checks that it starts, swaps it in and restarts (about 20 seconds), and the page comes back by
itself. Your settings, keys, plays, layouts and password stay. It refuses while you hold shares or contracts or have
working orders ("close out first"). The previous build is kept as `/opt/ted/app.prev` for a rollback by hand.

## TAKE PROFIT along the way

In a trade you can have a target, break even and a stop set, and still pay yourself on the way. The order block has a
TAKE PROFIT row for shares and for a contract:

- 25% / 50% / 75% fill in how many.
- Type a price to rest a limit there, or leave it blank to take it now at the touch.
- TAKE PROFIT sends it.

What is left keeps its stop and target.

## Dropdowns

A dropdown you have open is never rebuilt under the mouse. This covers the timeframe, the expiry, the stop's ON
choice and every other dropdown on the desk. The panel catches up the moment you pick or click away.

## The voice and your position

When you hold a position, every story line reads the market from your side. In a short you hear about demand under
you, never "supply to supply" over you. The Daily and the last break no longer talk over the trade. The 2nd-entry
watch and FLOW WATCH for a play on the other side stay quiet while you are in the trade.

## Time & Sales, OPTION FLOW, the CANDLE ladder, the chart wheel

- **T&S** gets the last 150 prints (it used to get 14): pull the window taller and it fills. SETTINGS › Time & Sales ›
  rows sent.
- **OPTION FLOW** text is smaller, with tighter rows, so more prints fit.
- **The CANDLE on the Level II** is the chart's candle, number for number (checked against the chart: same open, high,
  low and close). Green while the last price is at or over the candle's open, red under it; the body runs from the open
  to the last price. When the candle runs past the rows on the ladder, the top or bottom row of the candle column says
  where it goes (▲ O 200.54 · H 200.56), so a column that is all one colour still reads as a candle.
- **The chart's mouse wheel** zooms smoothly around the mouse and re-fits the prices every time, so nothing goes off the
  top or bottom; a trackpad zooms a little at a time.
