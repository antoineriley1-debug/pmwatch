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


def _clean(v):
    return "".join(str(v or "").split())          # a pasted key / ID often carries a space or a line break


def has_voice(cfg):
    sc = cfg.get("speech") or {}
    return bool(_clean(sc.get("api_key"))) and bool(_clean(sc.get("voice_id")))


def ready(cfg):
    """The desk speaks in the ElevenLabs voice: engine auto (the default: whenever a key and a voice are in) or cloud."""
    sc = cfg.get("speech") or {}
    return (sc.get("engine") or "auto") in ("auto", "cloud") and has_voice(cfg)


_NAMES = {}      # (key tail, voice name) -> voice ID found in the account


def _looks_like_id(v):
    return len(v) >= 18 and v.isalnum()


def voice_id(cfg, timeout=10.0):
    """The voice ID to speak with. A NAME typed in (\"dan\") is looked up in your ElevenLabs voices once."""
    sc = cfg.get("speech") or {}
    vid, key = _clean(sc.get("voice_id")), _clean(sc.get("api_key"))
    if _looks_like_id(vid):
        return vid
    name = str(sc.get("voice_id") or "").strip()
    hit = _NAMES.get((key[-6:], name.lower()))
    if hit:
        return hit
    base = str(sc.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
    req = urllib.request.Request(f"{base}/v1/voices", headers={"xi-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            voices = json.loads(r.read().decode("utf-8")).get("voices") or []
    except urllib.error.HTTPError as e:
        raise TTSError(_plain(e.code, "") + f" (looking up the voice named '{name}')")
    except Exception as e:
        raise TTSError(f"voice service not reachable: {e}")
    for v in voices:
        if str(v.get("name") or "").strip().lower() == name.lower() or v.get("voice_id") == vid:
            _NAMES[(key[-6:], name.lower())] = v["voice_id"]
            return v["voice_id"]
    names = ", ".join(str(v.get("name")) for v in voices[:12]) or "none"
    raise TTSError(f"no voice named '{name}' in this ElevenLabs account (it has: {names}). "
                   "SETTINGS > Voice > Voice id: paste the voice's ID (ElevenLabs: My Voices > the voice > ID) or its exact name")


def _plain(code, detail):
    """ElevenLabs' answer in plain words."""
    return {401: "ElevenLabs refused the API key (401): copy it again from ElevenLabs > API Keys, with Text to Speech allowed",
            402: "ElevenLabs says the account is out of credits or this voice needs a paid plan (402)",
            403: "ElevenLabs refused (403): the API key is not allowed this (turn on Text to Speech / Voices for the key)",
            404: "ElevenLabs has no voice with that ID (404): copy the ID from My Voices > the voice",
            422: "ElevenLabs did not accept the request (422)",
            429: "ElevenLabs is busy or the plan's limit was hit (429): the browser voice says it for now"}.get(
        code, f"voice service said {code}") + (f" — {detail}" if detail else "")


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
        if has_voice(cfg):
            _status(False, str(e))
        raise
    return audio


def _speak(cfg, text, cache_dir, timeout, fresh):
    sc = cfg.get("speech") or {}
    if not has_voice(cfg):
        raise TTSError("the ElevenLabs voice is not set up: SETTINGS > Voice (API key and voice ID)")
    text = " ".join(str(text or "").split())[:600]
    if not text:
        raise TTSError("nothing to say")
    os.makedirs(cache_dir, exist_ok=True)
    vid = voice_id(cfg)
    sc = dict(sc, voice_id=vid)
    path = _cache_path(cache_dir, sc, text)
    if not fresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as fh:
            return fh.read()
    base = str(sc.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
    body = {"text": text, "model_id": sc.get("model") or "eleven_turbo_v2_5",
            "voice_settings": {"stability": float(sc.get("stability", 0.5)), "similarity_boost": float(sc.get("similarity", 0.8)),
                               "speed": float(sc.get("speed", 1.0))}}
    req = urllib.request.Request(f"{base}/v1/text-to-speech/{vid}?output_format=mp3_44100_64",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": _clean(sc["api_key"]), "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise TTSError(_plain(e.code, detail or str(e.reason)))
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
