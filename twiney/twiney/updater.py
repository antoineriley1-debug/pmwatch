"""UPDATE from the desk (the VPS): a newer build on GitHub shows an UPDATE button; one click downloads it, checks it
starts, swaps it in and restarts TED. Your data folder (config.json, plays, layouts, recordings) is never touched.

Only where TED runs from a swappable link (the VPS: /opt/ted/app -> /opt/ted/unpack.../TWINEY/twiney). Anywhere else
(Windows) the button never shows. The previous build stays next to it (app.prev) for a rollback by hand:
    ln -sfn "$(readlink /opt/ted/app.prev)" /opt/ted/app && systemctl restart ted
"""

import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

BUILD_RE = re.compile(rb'name="build" content="([0-9]{8}-[0-9]{4})"')


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "TED-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def default_verify(app_dir):
    """The new build must import cleanly with this Python before it replaces the running one."""
    try:
        r = subprocess.run([sys.executable, "-c", "import twiney.dashboard, twiney.engine, twiney.trading, twiney.auth"],
                           cwd=app_dir, capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()[-400:]


class Updater:
    def __init__(self, current_build, repo, branch, app_link="/opt/ted/app", fetch=None, verify=None, clock=time.time):
        self.current = current_build or ""
        self.repo, self.branch, self.app_link = repo, branch, app_link
        self.fetch = fetch or _get
        self.verify = verify or default_verify
        self.clock = clock
        self.latest, self.checked_at, self.check_error = None, 0.0, None
        self.state, self.reason = "idle", ""
        self._lock = threading.Lock()

    def enabled(self):
        return bool(self.repo and self.branch and os.path.islink(self.app_link))

    def _raw_url(self):
        return f"https://raw.githubusercontent.com/{self.repo}/{self.branch}/twiney/twiney/static/dashboard.html"

    def _zip_url(self):
        return f"https://github.com/{self.repo}/archive/refs/heads/{self.branch}.zip"

    def check(self, force=False, max_age_s=600):
        """What is running, what is on GitHub, and whether the UPDATE button shows."""
        if self.enabled() and (force or self.clock() - self.checked_at > max_age_s):
            self.checked_at = self.clock()
            try:
                m = BUILD_RE.search(self.fetch(self._raw_url(), 20)[:8000])
                self.latest, self.check_error = (m.group(1).decode() if m else None), None
            except Exception as exc:  # noqa: BLE001
                self.check_error = str(exc)[:200]
        newer = bool(self.latest and self.current and self.latest > self.current)
        return {"ok": True, "enabled": self.enabled(), "current": self.current, "latest": self.latest, "newer": newer,
                "state": self.state, "reason": self.reason, "error": self.check_error}

    # ---------------------------------------------------------------- install
    def install(self):
        """Download, unpack beside the running build, check it imports, swap the link. Returns {ok, build | reason}.
        The caller restarts TED after an ok."""
        if not self.enabled():
            return {"ok": False, "reason": "updating from the desk works on the VPS install only"}
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "reason": "an update is already running"}
        try:
            self.state, self.reason = "downloading", ""
            data = self.fetch(self._zip_url(), 180)
            self.state = "installing"
            base = os.path.dirname(os.path.abspath(self.app_link))
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock()))
            dest = os.path.join(base, f"unpack-{stamp}")
            app_dir = self._unpack(data, dest)
            m = None
            try:
                with open(os.path.join(app_dir, "twiney", "static", "dashboard.html"), "rb") as fh:
                    m = BUILD_RE.search(fh.read(8000))
            except OSError:
                pass
            if not os.path.exists(os.path.join(app_dir, "run_twiney.py")) or not m:
                shutil.rmtree(dest, ignore_errors=True)
                return self._fail("the download is not a TED build")
            ok, why = self.verify(app_dir)
            if not ok:
                shutil.rmtree(dest, ignore_errors=True)
                return self._fail("the new build did not start a test run, nothing changed: " + why)
            prev = os.readlink(self.app_link)
            tmp = self.app_link + ".new"
            if os.path.lexists(tmp):
                os.remove(tmp)
            os.symlink(app_dir, tmp)
            os.replace(tmp, self.app_link)                      # the swap is one atomic step
            ptmp = self.app_link + ".prev.new"
            if os.path.lexists(ptmp):
                os.remove(ptmp)
            os.symlink(prev, ptmp)
            os.replace(ptmp, self.app_link + ".prev")
            self._cleanup(base, keep={self._top(app_dir, base), self._top(prev, base)})
            build = m.group(1).decode()
            self.state, self.reason = "restarting", f"build {build} installed"
            return {"ok": True, "build": build}
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"update failed, nothing changed: {exc}")
        finally:
            self._lock.release()

    def _fail(self, why):
        self.state, self.reason = "failed", why
        return {"ok": False, "reason": why}

    @staticmethod
    def _top(path, base):
        rel = os.path.relpath(os.path.realpath(path) if os.path.exists(path) else path, os.path.realpath(base))
        return rel.split(os.sep)[0]

    @staticmethod
    def _cleanup(base, keep):
        for name in os.listdir(base):
            if (name == "unpack" or name.startswith("unpack-")) and name not in keep:
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)

    @staticmethod
    def _unpack(data, dest):
        """GitHub's branch zip holds <repo>-<branch>/twiney/...: only that folder comes out, as TWINEY/twiney. Never
        a private config.json, never a path outside the folder."""
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        top = names[0].split("/")[0] if names else ""
        pre = top + "/twiney/"
        out = os.path.join(dest, "TWINEY", "twiney")
        root = os.path.realpath(out)
        os.makedirs(out, exist_ok=True)
        for info in zf.infolist():
            if not info.filename.startswith(pre) or info.is_dir():
                continue
            rel = info.filename[len(pre):]
            if not rel or rel == "config.json":
                continue
            target = os.path.realpath(os.path.join(out, rel))
            if not (target == root or target.startswith(root + os.sep)):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return out
