import unittest

from _db_fixture import TempDBTestCase, price_row
from src import stock_search
from src.storage import db

NAMES = {"2330": "台積電", "2303": "聯電", "2454": "聯發科", "3022": "威強電", "2317": "鴻海", "6488": "環球晶",
         "0050": "元大台灣50", "2882": "國泰金", "2881": "富邦金", "8069": "元太"}


class SearchTest(unittest.TestCase):
    def test_exact_code_and_name(self):
        self.assertEqual(stock_search.search("2330", NAMES), {"code": "2330", "exact": True, "candidates": []})
        self.assertEqual(stock_search.search(" 威強電 ", NAMES)["code"], "3022")
        self.assertTrue(stock_search.search("台積電", NAMES)["exact"])

    def test_normalize_full_width_and_tai(self):
        self.assertEqual(stock_search.search("２３３０", NAMES)["code"], "2330")   # 全形數字
        self.assertEqual(stock_search.search("臺積電", NAMES)["code"], "2330")     # 臺／台
        self.assertEqual(stock_search.search("元大台灣５０", NAMES)["code"], "0050")

    def test_prefix_then_contains_shorter_first(self):
        result = stock_search.search("聯", NAMES)
        self.assertEqual(result["code"], "2303")                 # 「聯電」比「聯發科」短
        self.assertFalse(result["exact"])
        self.assertEqual(result["candidates"], [("2454", "聯發科")])
        # 有成交值時成交值大的優先
        popular = stock_search.search("聯", NAMES, {"2454": 5e10, "2303": 1e9})
        self.assertEqual(popular["code"], "2454")
        contains = stock_search.search("金", NAMES)
        self.assertEqual({contains["code"], *[c for c, _ in contains["candidates"]]}, {"2882", "2881"})

    def test_code_prefix(self):
        result = stock_search.search("233", NAMES)
        self.assertEqual(result["code"], "2330")

    def test_fuzzy_typo(self):
        self.assertEqual(stock_search.search("台積店", NAMES)["code"], "2330")
        self.assertEqual(stock_search.search("環球精", NAMES)["code"], "6488")

    def test_not_found(self):
        self.assertIsNone(stock_search.search("不存在的公司名稱", NAMES)["code"])
        self.assertIsNone(stock_search.search("", NAMES)["code"])


class SecurityNamesTest(TempDBTestCase):
    def test_includes_etf_excludes_warrant_and_uses_latest_name(self):
        db.save_stock_price([
            price_row("2026-09-18", code="2330", name="台積電"),
            price_row("2026-09-18", code="0050", name="元大台灣50"),
            price_row("2026-09-18", code="030001", name="某權證"),
            price_row("2026-09-17", code="6488", name="舊名稱", market="TPEx"),
            price_row("2026-09-19", code="6488", name="環球晶", market="TPEx"),  # 上櫃最新日期不同
        ])
        rows = {r["code"]: r["name"] for r in db.query_security_list("2026-09-01")}
        self.assertEqual(rows, {"2330": "台積電", "0050": "元大台灣50", "6488": "環球晶"})


if __name__ == "__main__":
    unittest.main()
