"""Append-only JSONL recording of every raw market-data event for replay/audit."""

import json
import os
import threading
import time


class Recorder:
    def __init__(self, directory, name=None):
        os.makedirs(directory, exist_ok=True)
        name = name or time.strftime("twiney-%Y%m%d-%H%M%S.jsonl")
        self.path = os.path.join(directory, name)
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()
        self.count = 0

    def write(self, event):
        line = json.dumps(event, separators=(",", ":"), default=str)
        with self._lock:
            if self._fh is None:
                return
            self._fh.write(line + "\n")
            self.count += 1

    def close(self):
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


def read_events(path):
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # a crash can truncate the final line; everything before it is still valid
                continue
