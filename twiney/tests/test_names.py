import unittest

from twiney.names import DIRECTORY, parse_user, spoken, tidy


class NameDirectoryTests(unittest.TestCase):
    def test_directory_names(self):
        self.assertEqual(spoken("AAPL"), "Apple")
        self.assertEqual(spoken("nvda"), "Nvidia")
        self.assertEqual(spoken("BRK B"), "Berkshire")
        self.assertEqual(spoken("SPY"), "the S&P")
        self.assertGreater(len(DIRECTORY), 500)

    def test_yours_win(self):
        self.assertEqual(spoken("AAPL", "APPLE INC", parse_user("aapl = Apple Computer")), "Apple Computer")

    def test_ibkr_name_tidied_when_not_in_the_directory(self):
        self.assertEqual(spoken("ZZZZ", "ADVANCED WIDGETS INC-CL A"), "Advanced Widgets")
        self.assertEqual(spoken("ZZZZ", ""), "ZZZZ")

    def test_tidy(self):
        cases = {"APPLE INC": "Apple", "ALPHABET INC-CL A": "Alphabet", "TAIWAN SEMICONDUCTOR-SP ADR": "Taiwan Semiconductor",
                 "AT&T INC": "AT&T", "PROCTER & GAMBLE CO/THE": "Procter and Gamble", "SOUNDHOUND AI INC-A": "Soundhound AI",
                 "VISA INC-CLASS A SHARES": "Visa", "THE HOME DEPOT INC": "Home Depot", "COCA-COLA CO": "Coca-Cola"}
        for raw, want in cases.items():
            self.assertEqual(tidy(raw), want, raw)

    def test_parse_user(self):
        self.assertEqual(parse_user("AAPL=Apple, brk b = Berkshire; junk\nSPY=the market"),
                         {"AAPL": "Apple", "BRK B": "Berkshire", "SPY": "the market"})


if __name__ == "__main__":
    unittest.main()
