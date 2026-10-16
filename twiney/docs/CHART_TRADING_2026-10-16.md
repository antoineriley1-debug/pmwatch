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

## The option chart

- The bid / ask, delta and "practice model" words are gone from the top line.
- Holding the contract, the top line shows CLOSE (all at the touch) and BREAK EVEN. The STOP box (on the stock or on
  the contract) stays.

## The order block (bottom of ORDER ENTRY)

| holding | buttons |
|---|---|
| shares | SELL / BUY presets, ALL, **BREAK EVEN**, and a **STOP** box: type a price, SET |
| a contract | SELL 25% / 50% / 75%, **CLOSE**, **BREAK EVEN**, and a **STOP** box: ON the stock or ON CONTRACT, type a price, SET |

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
