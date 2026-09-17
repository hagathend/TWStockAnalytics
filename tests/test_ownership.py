import unittest
from datetime import date, timedelta
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import ownership
from src.collectors import twse_ownership
from src.storage import db

# 欄位照抄 2026-09-16 實際回應
QFIIS = {"stat": "OK",
         "fields": ["證券代號", "證券名稱", "國際證券編碼", "發行股數", "外資及陸資尚可投資股數", "全體外資及陸資持有股數",
                    "外資及陸資尚可投資比率", "全體外資及陸資持股比率", "外資及陸資共用法令投資上限比率", "陸資法令投資上限比率",
                    "與前日異動原因(註)", "最近一次上市公司申報外資及陸資持股異動日期"],
         "data": [["2330", "台積電", "TW0002330008", "25,932,370,067", "7,988,871,297", "17,943,498,770", 30.8, 69.19,
                   "100.00", "100.00", "", ""],
                  ["00400A", "主動國泰動能高息", "TW", "1", "1", "1", 98.31, 1.68, "100.00", "100.00", "", ""]]}
SBL = {"stat": "OK",
       "fields": ["代號", "名稱", "前日餘額", "賣出", "買進", "現券", "今日餘額", "次一營業日限額", "前日餘額", "當日賣出",
                  "當日還券", "當日調整", "當日餘額", "次一營業日可限額", "備註"],
       "data": [["2330", "台積電", "0", "0", "0", "0", "0", "0", "16,618,514", "90,000", "2,024,000", "0", "14,684,514",
                 "6,202,543", " "]]}


class ParseTests(unittest.TestCase):
    def test_foreign_holding(self):
        rows = twse_ownership.parse_foreign_holding(QFIIS, "20260916", keep_code=db.is_stock_code)
        self.assertEqual(len(rows), 1)  # ETF 略過
        self.assertEqual(rows[0]["date"], "2026-09-16")
        self.assertAlmostEqual(rows[0]["foreign_pct"], 69.19)
        self.assertEqual(rows[0]["foreign_shares"], 17943498770)

    def test_sbl_takes_second_half_columns(self):
        row = twse_ownership.parse_sbl(SBL, "20260916")[0]
        self.assertEqual((row["prev_balance"], row["sold"], row["returned"], row["balance"]),
                         (16618514, 90000, 2024000, 14684514))
        self.assertEqual(row["prev_balance"] + row["sold"] - row["returned"] + row["adjusted"], row["balance"])

    def test_sbl_format_change_detected(self):
        with self.assertRaises(ValueError):
            twse_ownership.parse_sbl({"stat": "OK", "fields": ["股票代號", "x"], "data": []}, "20260916")


class OwnershipTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.dates = [(date.today() - timedelta(days=30 - i)).isoformat() for i in range(25)]
        db.save_stock_price([price_row(d, close=100.0, volume=2_000_000) for d in self.dates])
        db.save_foreign_holding([{"date": d, "code": "2330", "name": "台積電", "issued_shares": 1, "foreign_shares": 1,
                                  "foreign_pct": 60.0 + i * 0.1, "foreign_limit_pct": 100.0}
                                 for i, d in enumerate(self.dates)])
        db.save_sbl_short([{"date": d, "code": "2330", "name": "台積電", "prev_balance": 0, "sold": 0, "returned": 0,
                            "adjusted": 0, "balance": 10_000_000 + i * 100_000, "next_limit": 0}
                           for i, d in enumerate(self.dates)])

    def test_code_summary(self):
        s = ownership.code_summary("2330")
        self.assertAlmostEqual(s["foreign_pct"], 62.4)
        self.assertAlmostEqual(s["foreign_change_20"], 2.0)
        self.assertAlmostEqual(s["sbl_lots"], 12_400)
        self.assertAlmostEqual(s["sbl_change_5"], 500)
        self.assertAlmostEqual(s["sbl_days_of_volume"], 12_400_000 / 2_000_000)
        text = ownership.summarize_for_prompt("2330")
        self.assertIn("外資持股比例 62.40%", text)
        self.assertIn("20 日 +2.00 個百分點", text)
        self.assertIn("約 6.2 天平均成交量", text)

    def test_latest_table_change(self):
        table = ownership.latest_table().set_index("code")
        self.assertAlmostEqual(table.loc["2330", "foreign_change_20"], 2.0)

    def test_backfill_only_missing_dates(self):
        extra = (date.today() - timedelta(days=3)).isoformat()
        db.save_stock_price([price_row(extra, close=100.0)])
        calls = []
        fake = lambda label: (lambda ymd: calls.append((label, ymd)) or [])  # noqa: E731
        with patch.dict(ownership._TABLES, {"foreign_holding": ("外資持股", fake("f"), "save_foreign_holding"),
                                            "sbl_short": ("借券賣出", fake("s"), "save_sbl_short")}):
            stats = ownership.backfill(60, sleep_seconds=0)
        self.assertEqual(sorted(calls), [("f", extra.replace("-", "")), ("s", extra.replace("-", ""))])
        self.assertEqual(stats["filled"], 2)

    def test_no_data(self):
        self.assertIsNone(ownership.code_summary("9999"))
        self.assertIn("無外資持股", ownership.summarize_for_prompt("9999"))


if __name__ == "__main__":
    unittest.main()
