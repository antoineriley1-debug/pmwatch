"""DAN'S DAILY: the Market Notes email from Access A Trader, read from Twiney's Gmail every day and put on the desk.

The email carries the "Current Pivot Watchlist" (a ticker, its pivot or pivots, Short when it is a short, the
stars) and the "OPTION FLOW" lines. TED reads it over IMAP with a Gmail app password that lives only in the private
config.json, parses the plain text with rules (never a model), keeps the newest one in the data folder, and shows
it on the WATCHLIST panel. Watch only: nothing is traded from it; a click puts a name on the desk, with its pivot."""

import email
import imaplib
import json
import logging
import os
import re
import threading
import time
from email import policy

log = logging.getLogger("twiney.danmail")

WATCH_HEAD = re.compile(r"current\s+pivot\s+watch\s*list\s*(?P<date>[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})?", re.I)
FLOW_HEAD = re.compile(r"^\s*option\s+flow\s*$", re.I)
ROW = re.compile(r"^\s*(?P<sym>[A-Z][A-Z0-9.]{0,5})\s+(?P<px>\d[\d.,]*(?:\s*(?:&|and|/)\s*\d[\d.,]*)*)\s*(?P<side>short|long)?\s*(?P<stars>\d)?\s*(?:⭐|★|\*)?", re.I)
FLOW = re.compile(r"^\s*(?P<who>BUYER|SELLER)\s+(?P<size>[\d,]+)\s+(?P<sym>[A-Z][A-Z0-9.]{0,5})\s+(?P<exp>WKLY|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+"
                  r"(?P<strike>\d[\d.]*)(?P<right>[CP])(?:\s*@\s*(?P<px>\d[\d.]*))?\s*(?P<prem>[\d.]+\s*[MK])?", re.I)


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(text):
    """The watchlist and the flow out of the email's plain text. Rows that do not read cleanly are left out, never
    guessed. Returns {"date", "rows": [...], "flow": [...], "notes": the Market Notes paragraphs}."""
    lines = [ln.rstrip() for ln in str(text or "").replace("\r", "").split("\n")]
    out = {"date": None, "rows": [], "flow": [], "notes": ""}
    i = 0
    n = len(lines)
    # the watchlist block: from its heading to OPTION FLOW (or a footnote line)
    while i < n and not WATCH_HEAD.search(lines[i]):
        i += 1
    head_i = i
    if i < n:
        m = WATCH_HEAD.search(lines[i])
        out["date"] = (m.group("date") or "").strip() or None
        i += 1
        while i < n:
            ln = lines[i].strip()
            if not ln:
                i += 1
                continue
            if FLOW_HEAD.match(ln) or ln.startswith("*"):
                break
            r = ROW.match(ln)
            if r and r.group("sym").upper() not in ("OPTION", "FLOW", "THE", "AND"):
                pivots = [p for p in (_num(x) for x in re.split(r"\s*(?:&|and|/)\s*", r.group("px"))) if p]
                if pivots:
                    out["rows"].append({"symbol": r.group("sym").upper(), "pivots": pivots, "side": "short" if (r.group("side") or "").lower() == "short" else "long",
                                        "stars": int(r.group("stars")) if r.group("stars") else None, "line": ln})
            i += 1
    # the flow block
    j = 0
    while j < n and not FLOW_HEAD.match(lines[j].strip()):
        j += 1
    if j < n:
        j += 1
        while j < n:
            ln = lines[j].strip()
            if ln.startswith("*"):
                break
            if ln:
                f = FLOW.match(ln)
                if f:
                    out["flow"].append({"who": f.group("who").upper(), "size": int(_num(f.group("size")) or 0), "symbol": f.group("sym").upper(),
                                        "expiry": f.group("exp").upper(), "strike": _num(f.group("strike")), "right": f.group("right").upper(),
                                        "price": _num(f.group("px")), "premium": (f.group("prem") or "").replace(" ", "").upper() or None, "line": ln})
            j += 1
    # the notes: between "Market Notes" and the watchlist heading
    k = next((x for x in range(n) if lines[x].strip().lower() == "market notes"), None)
    if k is not None and head_i < n:
        out["notes"] = "\n".join(l for l in lines[k + 1:head_i] if l.strip())[:6000]
    return out


def body_text(msg):
    """The plain text of an email message (the HTML stripped when there is no plain part)."""
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        return part.get_content()
    part = msg.get_body(preferencelist=("html",))
    if part is None:
        return ""
    html = part.get_content()
    html = re.sub(r"<\s*br\s*/?>|</p>|</div>|</tr>", "\n", html, flags=re.I)
    return re.sub(r"<[^>]+>", " ", html)


def parse_message(raw):
    msg = email.message_from_bytes(raw, policy=policy.default)
    out = parse(body_text(msg))
    out.update({"subject": str(msg.get("subject") or ""), "from": str(msg.get("from") or ""), "sent": str(msg.get("date") or "")})
    return out


def fetch_latest(user, app_password, sender, subject_word, host="imap.gmail.com", limit=5):
    """The newest email from ``sender`` whose subject has ``subject_word`` (the last ``limit`` looked at). Raises on a
    login or connection problem, with IMAP's own words."""
    box = imaplib.IMAP4_SSL(host)
    try:
        box.login(user, app_password)
        box.select("INBOX", readonly=True)
        crit = f'(FROM "{sender}" SUBJECT "{subject_word}")' if subject_word else f'(FROM "{sender}")'
        typ, data = box.search(None, crit)
        ids = (data[0] or b"").split()
        if not ids:
            return None
        best = None
        for uid in reversed(ids[-limit:]):
            typ, parts = box.fetch(uid, "(RFC822)")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if not raw:
                continue
            got = parse_message(raw)
            if got["rows"] or got["flow"]:
                return got
            best = best or got
        return best
    finally:
        try:
            box.logout()
        except Exception:
            pass


class DanMail:
    """Reads the email on a schedule (the times in SETTINGS, New York), at startup, and on demand; keeps the newest
    result in the data folder so the desk shows yesterday's list until today's lands."""

    def __init__(self, engine, cfg, data_dir, clock=time.time, fetcher=fetch_latest):
        self.engine = engine
        self.cfg = cfg
        self.path = os.path.join(data_dir, "dan-watchlist-latest.json")
        self.clock = clock
        self.fetcher = fetcher
        self.lock = threading.Lock()
        self.latest = None
        self.status = {"last_try": None, "last_ok": None, "error": None, "busy": False}
        self._fired = set()
        self.load()

    def gc(self):
        return self.cfg.get("gmail") or {}

    def enabled(self):
        g = self.gc()
        return bool(g.get("enabled")) and bool(g.get("user")) and bool(g.get("app_password"))

    # ---- storage ----
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.latest = json.load(f)
        except (OSError, ValueError):
            self.latest = None

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.latest, f, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("dan watchlist not saved: %s", exc)

    # ---- fetching ----
    def refresh(self, t=None, wait=False):
        """Read the email now (in the background unless ``wait``). Returns the status at once."""
        if not self.enabled():
            self.status["error"] = "Gmail is off: SETTINGS › Gmail (Dan's Market Notes): user + app password, then on"
            return dict(self.status)
        if self.status["busy"]:
            return dict(self.status)
        self.status["busy"] = True
        if wait:
            self._work(t or self.clock())
        else:
            threading.Thread(target=self._work, args=(t or self.clock(),), name="twiney-danmail", daemon=True).start()
        return dict(self.status)

    def _work(self, t):
        g = self.gc()
        try:
            got = self.fetcher(g.get("user"), g.get("app_password"), g.get("sender") or "support@accessatrader.com",
                               g.get("subject") if g.get("subject") is not None else "Watchlist")
            with self.lock:
                self.status["last_try"] = t
                if got is None:
                    self.status["error"] = "no Market Notes email from that sender in the inbox"
                else:
                    got["fetched"] = t
                    self.latest = got
                    self.status["last_ok"], self.status["error"] = t, None
                    self.save()
                    try:
                        self.engine._message("info", f"DAN'S DAILY read from Gmail: {len(got['rows'])} names, {len(got['flow'])} flow lines ({got.get('subject') or ''})", t, category="INFORMATION")
                    except Exception:
                        pass
        except Exception as exc:
            with self.lock:
                self.status["last_try"] = t
                self.status["error"] = str(exc)[:200]
            try:
                self.engine._message("error", f"DAN'S DAILY: Gmail did not answer: {str(exc)[:160]}", t, category="CONNECTION")
            except Exception:
                pass
        finally:
            self.status["busy"] = False

    def tick(self, t):
        """Once a minute from the desk: the scheduled reads (each time once a day), and once at startup."""
        if not self.enabled():
            return
        from . import studies
        d = studies.ny(t)
        day = d.strftime("%Y%m%d")
        if ("start", "once") not in self._fired:
            self._fired.add(("start", "once"))
            self.refresh(t)
            return
        for hm in self.gc().get("times") or ["06:30", "19:45"]:
            try:
                hh, mm = (int(x) for x in str(hm).split(":"))
            except ValueError:
                continue
            key = (day, hm)
            if key in self._fired:
                continue
            if (d.hour, d.minute) >= (hh, mm) and (d.hour * 60 + d.minute) - (hh * 60 + mm) <= 30:
                self._fired.add(key)
                self.refresh(t)

    # ---- the page ----
    def view(self):
        with self.lock:
            lt = self.latest or {}
            return {"enabled": self.enabled(), "date": lt.get("date"), "subject": lt.get("subject"), "sent": lt.get("sent"),
                    "fetched": lt.get("fetched"), "rows": list(lt.get("rows") or []), "flow": list(lt.get("flow") or [])[:20],
                    "status": dict(self.status), "times": list(self.gc().get("times") or ["06:30", "19:45"])}
