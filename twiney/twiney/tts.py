"""THE DESK'S VOICE from a cloud voice (ElevenLabs): every call the desk says is spoken in one fixed voice (the voice
ID in SETTINGS > Voice), so it never changes between computers or browser updates.

Each phrase is made once and kept on disk (voice_cache/), so a repeated call plays at once and sounds the same every
time. If the service cannot be reached, the page falls back to the browser's own voice for that call.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request


class TTSError(Exception):
    pass


# how the cloud voice did last time it was asked (shown on the desk's VOICE button and by TEST VOICE)
STATUS = {"ok": None, "t": None, "error": ""}


def _status(ok, error=""):
    import time
    STATUS.update(ok=ok, t=time.time(), error=error)


def ready(cfg):
    sc = cfg.get("speech") or {}
    return sc.get("engine") == "cloud" and bool(sc.get("api_key")) and bool(sc.get("voice_id"))


def _cache_path(cache_dir, sc, text):
    h = hashlib.sha1(json.dumps([sc.get("voice_id"), sc.get("model"), sc.get("stability"), sc.get("similarity"),
                                 sc.get("speed"), text]).encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, h + ".mp3")


def speak(cfg, text, cache_dir, timeout=10.0, fresh=False):
    """The audio (mp3 bytes) for ``text`` in the configured voice: from the cache, or made now and kept.
    ``fresh``: ask the voice service even when the phrase is cached (TEST VOICE)."""
    try:
        audio = _speak(cfg, text, cache_dir, timeout, fresh)
    except TTSError as e:
        if ready(cfg):
            _status(False, str(e))
        raise
    return audio


def _speak(cfg, text, cache_dir, timeout, fresh):
    sc = cfg.get("speech") or {}
    if not ready(cfg):
        raise TTSError("the cloud voice is not set up: SETTINGS > Voice (engine cloud, API key, voice ID)")
    text = " ".join(str(text or "").split())[:600]
    if not text:
        raise TTSError("nothing to say")
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, sc, text)
    if not fresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as fh:
            return fh.read()
    base = str(sc.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
    body = {"text": text, "model_id": sc.get("model") or "eleven_turbo_v2_5",
            "voice_settings": {"stability": float(sc.get("stability", 0.5)), "similarity_boost": float(sc.get("similarity", 0.8)),
                               "speed": float(sc.get("speed", 1.0))}}
    req = urllib.request.Request(f"{base}/v1/text-to-speech/{sc['voice_id']}?output_format=mp3_44100_64",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": sc["api_key"], "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise TTSError(f"voice service said {e.code}: {detail or e.reason}")
    except Exception as e:
        raise TTSError(f"voice service not reachable: {e}")
    if not audio:
        raise TTSError("voice service sent no audio")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(audio)
    os.replace(tmp, path)
    _status(True)
    return audio
