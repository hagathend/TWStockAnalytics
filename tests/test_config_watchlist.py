import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config_watchlist


class AddStocksTests(unittest.TestCase):
    def test_adds_new_and_reports_existing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config_watchlist, "_WATCHLIST_PATH", Path(tmp) / "watchlist.json"):
            config_watchlist.save_watchlist({"2330": "台積電"})
            added, existing = config_watchlist.add_stocks([("2330", "台積電"), ("2305", "全友"), ("6226", "光鼎")])
            self.assertEqual(added, ["2305", "6226"])
            self.assertEqual(existing, ["2330"])
            self.assertEqual(list(config_watchlist.load_watchlist()), ["2330", "2305", "6226"])

    def test_nothing_new_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config_watchlist, "_WATCHLIST_PATH", Path(tmp) / "watchlist.json"):
            config_watchlist.save_watchlist({"2330": "台積電"})
            with patch.object(config_watchlist, "save_watchlist") as save:
                self.assertEqual(config_watchlist.add_stocks([("2330", "台積電")]), ([], ["2330"]))
                save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
