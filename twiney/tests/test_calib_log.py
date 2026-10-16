"""CHILD ORDERS calibration log: every detection on the live tape, one line as it grows; never on practice."""

import json
import os
import tempfile
import unittest

from helpers import cfg, plays
from twiney.engine import Engine


class CalibLogTests(unittest.TestCase):
    def _engine(self):
        e = Engine(plays(), cfg(), None)
        d = tempfile.mkdtemp()
        e.calib_path = os.path.join(d, "inst_calib.jsonl")
        st = e.syms[plays()[0]["symbol"]]
        st.l1["last"] = 100.0
        return e, st

    def _kids(self, n=12):
        return {"side": "BUY", "size": 300, "n": n, "every": 5.0, "minutes": 1.0, "one_way": 90, "shares": 300 * n, "usd": 30000 * n,
                "t0": 1000.0, "sizes": [300], "since": "9:30", "sizes_set": {300}}

    def test_live_only_and_once_per_growth(self):
        e, st = self._engine()
        memo = {}
        e._calib(st, self._kids(), 1060.0, memo)                       # not connected: nothing written
        self.assertFalse(os.path.exists(e.calib_path))
        e.connection["state"] = "CONNECTED"
        e._calib(st, self._kids(), 1060.0, memo)
        e._calib(st, self._kids(), 1061.0, memo)                       # the same detection again: not repeated
        e._calib(st, self._kids(13), 1066.0, memo)                     # it grew: a new line
        with open(e.calib_path) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual([r["n"] for r in rows], [12, 13])
        self.assertEqual(rows[0]["symbol"], st.symbol)
        self.assertEqual(rows[0]["price"], 100.0)
        self.assertNotIn("sizes_set", rows[0])

    def test_demo_never_writes(self):
        e, st = self._engine()
        e.connection["state"] = "DEMO"
        e._calib(st, self._kids(), 1060.0, {})
        self.assertFalse(os.path.exists(e.calib_path))


if __name__ == "__main__":
    unittest.main()
