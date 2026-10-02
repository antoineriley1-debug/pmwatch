import json, os, tempfile, unittest
from unittest import mock
from twiney import paths


class DataFolderTests(unittest.TestCase):
    """Your files live in the data folder: created from the examples, or copied in from an older build's program folder."""
    def test_config_and_plays_land_in_the_data_folder_and_survive(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as prog:
            with open(os.path.join(prog, "config.example.json"), "w") as fh:
                json.dump({"ibkr": {"port": 7497}}, fh)
            with mock.patch.dict(os.environ, {"TWINEY_HOME": home}):
                c = paths.ensure_config(prog); p = paths.ensure_plays(prog)
                self.assertEqual(os.path.dirname(c), home); self.assertEqual(os.path.dirname(p), home)
                self.assertEqual(json.load(open(c))["ibkr"]["port"], 7497)
                self.assertTrue(json.load(open(p))["plays"])
                # the user changes the port and the key: a "new build" (new program folder) keeps them
                json.dump({"ibkr": {"port": 7496}, "quantdata": {"api_key": "k"}}, open(c, "w"))
                with tempfile.TemporaryDirectory() as prog2:
                    c2 = paths.ensure_config(prog2)
                    self.assertEqual(c2, c); self.assertEqual(json.load(open(c2))["quantdata"]["api_key"], "k")
                self.assertEqual(paths.recordings_dir("recordings"), os.path.join(home, "recordings"))

    def test_an_older_builds_program_folder_config_is_carried_in(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as prog:
            json.dump({"ibkr": {"port": 7496}, "quantdata": {"api_key": "mine"}}, open(os.path.join(prog, "config.json"), "w"))
            with mock.patch.dict(os.environ, {"TWINEY_HOME": home}):
                c = paths.ensure_config(prog)
                self.assertEqual(os.path.dirname(c), home); self.assertEqual(json.load(open(c))["quantdata"]["api_key"], "mine")
