"""Where the order path is allowed to live.

TWINEY can send orders, but only through ``trading.TradingGate``:
  - PAPER accounts (IBKR ids starting "DU") or the built-in simulator only,
    unless ``trading.allow_live`` is explicitly true in config.json;
  - DISARMED at every launch until the trader clicks ARM;
  - LIMIT entries only, size and dollar caps, per-minute order cap.

``ORDER_CALLS`` lists the IBKR client methods that place / cancel orders.
The test-suite scans the package and fails if any file other than those in
``ORDER_PATH`` calls them, so the gate cannot be bypassed by accident.
"""

ORDER_CALLS = ("placeOrder", "cancelOrder", "reqGlobalCancel", "exerciseOptions")

# the only files allowed to mention the order calls
ORDER_PATH = ("twiney/ibkr.py", "twiney/trading.py", "twiney/safety.py")
