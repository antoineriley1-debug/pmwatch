"""Options for the desk: the option contract key, a practice chain and a practice pricer.

Live, the chain (expiries, strikes) and every quote come from IBKR (reqSecDefOptParams + reqMktData on the
option contract). The practice desk has no option market, so it makes one: weekly expiries, strikes on the
usual steps around the spot, and a Black-Scholes price with a wide-ish spread that moves with the stock.
The practice prices are for training the hands, never a claim about any real contract.
"""
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def key_of(symbol, expiry, strike, right):
    """'TSLA 20261003 240C' — the same name ibkr.opt_key builds from an IBKR contract."""
    return f"{str(symbol).upper()} {expiry} {float(strike):g}{str(right)[:1].upper()}"


def parse_key(key):
    sym, exp, rest = key.split(" ", 2)
    return sym, exp, float(rest[:-1]), rest[-1]


def fits_side(key, side):
    """A CALL rides the LONG side, a PUT the SHORT side. None = not an option key."""
    try:
        right = parse_key(str(key or ""))[3]
    except (ValueError, IndexError):
        return None
    return (right == "C") == ((side or "long") == "long")


def strike_step(spot):
    return 0.5 if spot < 25 else 1.0 if spot < 200 else 2.5 if spot < 500 else 5.0


def practice_expiries(now, n=6):
    """The next n Fridays, as IBKR expiry strings YYYYMMDD. Today counts when it is a Friday morning; from noon on
    the expiry day the practice chain rolls to next week (hours from the close the model's prices barely move, so a
    practice contract picked by default would be a dead one)."""
    nyd = datetime.fromtimestamp(now, NY)
    d = nyd.date()
    if d.weekday() == 4 and nyd.hour >= 12:
        d += timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() == 4:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def practice_strikes(spot, n_each_side=15):
    step = strike_step(spot)
    centre = round(spot / step) * step
    return [round(centre + i * step, 2) for i in range(-n_each_side, n_each_side + 1) if centre + i * step > 0]


def dte(expiry, now):
    """Days to expiration, fractional, to the 4 pm New York close of the expiry day."""
    try:
        d = datetime.strptime(expiry, "%Y%m%d").replace(hour=16, tzinfo=NY)
    except ValueError:
        return None
    return max(0.0, (d.timestamp() - now) / 86400.0)


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot, strike, days, right, iv=0.35, r=0.04):
    """Black-Scholes, days to expiry (calendar), for the practice desk."""
    if spot <= 0 or strike <= 0:
        return 0.0
    t = max(days, 0.0) / 365.0
    if t <= 1e-6:
        return max(0.0, spot - strike) if right == "C" else max(0.0, strike - spot)
    sd = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t) / sd
    d2 = d1 - sd
    if right == "C":
        return spot * _ncdf(d1) - strike * math.exp(-r * t) * _ncdf(d2)
    return strike * math.exp(-r * t) * _ncdf(-d2) - spot * _ncdf(-d1)


def practice_quote(spot, strike, expiry, right, now, iv=0.35):
    """bid / ask / last for a practice contract: the model price with a spread that widens on cheap and
    short-dated contracts, on the penny / nickel grid IBKR uses."""
    days = dte(expiry, now)
    if days is None:
        return None
    iv_eff = iv * (1.25 if days < 2 else 1.1 if days < 7 else 1.0)
    mid = bs_price(spot, strike, days, right, iv_eff)
    if mid < 0.01:
        return {"bid": 0.0, "ask": 0.01, "last": 0.01}
    half = max(0.01, mid * (0.008 if mid > 1 else 0.03))     # a liquid contract: a few cents wide
    grid = 0.01 if mid < 3 else 0.05
    bid = max(0.0, math.floor((mid - half) / grid) * grid)
    ask = math.ceil((mid + half) / grid) * grid
    return {"bid": round(bid, 2), "ask": round(ask, 2), "last": round(mid, 2)}


def bs_greeks(spot, strike, days, right, iv=0.35, r=0.04):
    """delta, gamma, theta (per day), vega (per 1 vol point) for the practice chain."""
    if spot <= 0 or strike <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "iv": iv}
    t = max(days, 0.0) / 365.0
    if t <= 1e-6:
        itm = (spot > strike) if right == "C" else (spot < strike)
        return {"delta": (1.0 if itm else 0.0) * (1 if right == "C" else -1), "gamma": 0.0, "theta": 0.0, "vega": 0.0, "iv": iv}
    sd = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t) / sd
    d2 = d1 - sd
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    delta = _ncdf(d1) if right == "C" else _ncdf(d1) - 1.0
    gamma = pdf / (spot * sd)
    vega = spot * pdf * math.sqrt(t) / 100.0
    if right == "C":
        theta = (-(spot * pdf * iv) / (2 * math.sqrt(t)) - r * strike * math.exp(-r * t) * _ncdf(d2)) / 365.0
    else:
        theta = (-(spot * pdf * iv) / (2 * math.sqrt(t)) + r * strike * math.exp(-r * t) * _ncdf(-d2)) / 365.0
    return {"delta": round(delta, 3), "gamma": round(gamma, 4), "theta": round(theta, 3), "vega": round(vega, 3), "iv": round(iv, 3)}
