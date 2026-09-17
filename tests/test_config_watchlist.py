import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config_watchlist as cw


class WatchlistTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "watchlist.json"
        self._patch = patch.object(cw, "_WATCHLIST_PATH", self.path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class AddStocksTests(WatchlistTestCase):
    def test_adds_new_and_reports_existing(self):
        cw.save_groups({"A": {"2330": "台積電"}})
        added, existing = cw.add_stocks([("2330", "台積電"), ("2305", "全友"), ("6226", "光鼎")])
        self.assertEqual(added, ["2305", "6226"])
        self.assertEqual(existing, ["2330"])
        self.assertEqual(list(cw.load_watchlist()), ["2330", "2305", "6226"])

    def test_nothing_new_does_not_rewrite(self):
        cw.save_groups({"A": {"2330": "台積電"}})
        with patch.object(cw, "save_groups") as save:
            self.assertEqual(cw.add_stocks([("2330", "台積電")]), ([], ["2330"]))
            save.assert_not_called()

    def test_add_to_specific_group(self):
        cw.save_groups({"A": {}, "B": {"2330": "台積電"}})
        self.assertEqual(cw.add_stocks([("2330", "台積電"), ("2317", "鴻海")], "B"), (["2317"], ["2330"]))
        self.assertEqual(cw.load_groups()["A"], {})
        with self.assertRaises(cw.WatchlistError):
            cw.add_stocks([("2330", "台積電")], "不存在")


class GroupTests(WatchlistTestCase):
    def test_migrates_old_single_list_format(self):
        self.path.write_text(json.dumps({"2330": "台積電", "2317": "鴻海"}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(cw.load_groups(), {cw.DEFAULT_GROUP: {"2330": "台積電", "2317": "鴻海"}})
        self.assertEqual(cw.load_watchlist(), {"2330": "台積電", "2317": "鴻海"})

    def test_seed_when_missing(self):
        groups = cw.load_groups()
        self.assertEqual(list(groups), [cw.DEFAULT_GROUP])
        self.assertTrue(self.path.exists())

    def test_union_keeps_order_without_duplicates(self):
        cw.save_groups({"A": {"2330": "台積電", "2317": "鴻海"}, "B": {"2317": "鴻海", "2454": "聯發科"}})
        self.assertEqual(list(cw.load_watchlist()), ["2330", "2317", "2454"])

    def test_create_rename_delete(self):
        cw.save_groups({"A": {"2330": "台積電"}})
        cw.create_group(" 高殖利率 ")
        self.assertEqual(list(cw.load_groups()), ["A", "高殖利率"])
        with self.assertRaises(cw.WatchlistError):
            cw.create_group("A")
        with self.assertRaises(cw.WatchlistError):
            cw.create_group("  ")
        cw.rename_group("A", "半導體")
        self.assertEqual(list(cw.load_groups()), ["半導體", "高殖利率"])
        self.assertEqual(cw.load_groups()["半導體"], {"2330": "台積電"})
        with self.assertRaises(cw.WatchlistError):
            cw.rename_group("半導體", "高殖利率")
        cw.delete_group("半導體")
        self.assertEqual(list(cw.load_groups()), ["高殖利率"])
        with self.assertRaises(cw.WatchlistError):
            cw.delete_group("高殖利率")

    def test_remove_stock_from_group(self):
        cw.save_groups({"A": {"2330": "台積電"}, "B": {"2330": "台積電"}})
        cw.remove_stock("2330", "B")
        self.assertEqual(cw.load_groups(), {"A": {"2330": "台積電"}, "B": {}})
        self.assertIn("2330", cw.load_watchlist())


if __name__ == "__main__":
    unittest.main()
