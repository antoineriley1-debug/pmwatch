"""Hard read-only guard.

The IBKR client class is built as ``ReadOnlyGuard`` first in the MRO, so even
if some future code tried to reach an order/execution call, the guard raises
before the request could be serialized to TWS / IB Gateway. For defense in
depth, also enable "Read-Only API" in TWS / Gateway API settings.
"""

FORBIDDEN_CALLS = (
    "placeOrder",
    "cancelOrder",
    "reqGlobalCancel",
    "exerciseOptions",
    "reqIds",
)


class ReadOnlyViolation(RuntimeError):
    pass


def _blocked(name):
    def method(self, *args, **kwargs):
        raise ReadOnlyViolation(f"TWINEY is market-data only: {name}() is disabled")
    method.__name__ = name
    return method


class ReadOnlyGuard:
    pass


for _name in FORBIDDEN_CALLS:
    setattr(ReadOnlyGuard, _name, _blocked(_name))
del _name
