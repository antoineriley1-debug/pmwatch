"""THE DESK'S VOICE (ElevenLabs): the call goes to your voice, a voice NAME is looked up, a pasted key with a space
still works, auto switches to it once a key and voice are in, and a refusal is said in plain words."""
import http.server
import json
import tempfile
import threading
import unittest

from twiney import tts

VID = "AbCdEfGhIjKlMnOpQrSt"


class _H(http.server.BaseHTTPRequestHandler):
    seen = []

    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("xi-api-key") != "goodkey":
            return self._send(401, b'{"detail":"invalid key"}', "application/json")
        self._send(200, json.dumps({"voices": [{"name": "Rachel", "voice_id": "x" * 20}, {"name": "dan", "voice_id": VID}]}).encode(), "application/json")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _H.seen.append((self.path, self.headers.get("xi-api-key"), body["text"]))
        if self.headers.get("xi-api-key") != "goodkey":
            return self._send(401, b'{"detail":"invalid key"}', "application/json")
        if VID not in self.path:
            return self._send(404, b'{"detail":"voice not found"}', "application/json")
        self._send(200, b"ID3" + b"\0" * 100, "audio/mpeg")

    def log_message(self, *a):
        pass


class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def cfg(self, **kw):
        sc = {"engine": "auto", "api_key": "goodkey", "voice_id": VID, "base_url": self.base}
        sc.update(kw)
        return {"speech": sc}

    def setUp(self):
        _H.seen.clear(); tts._NAMES.clear()
        self.cache = tempfile.mkdtemp()

    def test_auto_uses_your_voice_once_key_and_voice_are_in(self):
        self.assertTrue(tts.ready(self.cfg()))
        self.assertFalse(tts.ready(self.cfg(api_key="")))
        self.assertFalse(tts.ready(self.cfg(engine="browser")))
        audio = tts.speak(self.cfg(), "AAPL coming into V-WAP $337.19", self.cache)
        self.assertTrue(audio.startswith(b"ID3"))
        self.assertIn(VID, _H.seen[0][0]); self.assertTrue(tts.STATUS["ok"])

    def test_a_voice_name_is_looked_up(self):
        audio = tts.speak(self.cfg(voice_id="Dan"), "hello", self.cache)
        self.assertTrue(audio.startswith(b"ID3")); self.assertIn(VID, _H.seen[-1][0])

    def test_pasted_key_with_spaces_works(self):
        tts.speak(self.cfg(api_key=" goodkey\n", voice_id=VID + " "), "hi", self.cache)
        self.assertEqual(_H.seen[-1][1], "goodkey")

    def test_refusals_in_plain_words(self):
        with self.assertRaises(tts.TTSError) as e:
            tts.speak(self.cfg(api_key="bad"), "hi", self.cache)
        self.assertIn("refused the API key", str(e.exception)); self.assertFalse(tts.STATUS["ok"])
        with self.assertRaises(tts.TTSError) as e:
            tts.speak(self.cfg(voice_id="nobody"), "hi", self.cache)
        self.assertIn("no voice named 'nobody'", str(e.exception)); self.assertIn("dan", str(e.exception))

    def test_cached_phrase_plays_without_asking_again_unless_testing(self):
        tts.speak(self.cfg(), "same", self.cache); tts.speak(self.cfg(), "same", self.cache)
        self.assertEqual(len(_H.seen), 1)
        tts.speak(self.cfg(), "same", self.cache, fresh=True)
        self.assertEqual(len(_H.seen), 2)


if __name__ == "__main__":
    unittest.main()
