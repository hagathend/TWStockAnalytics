import unittest
from datetime import date, timedelta
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import market_index
from src.collectors import twse_market
from src.storage import db

# 欄位照抄 FMTQIK 實際回應（2026-09）
PAYLOAD = {
    "stat": "OK",
    "fields": ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"],
    "data": [["115/09/01", "13,000,849,196", "1,187,571,567,117", "5,301,801", "46,948.72", "820.25"],
             ["115/09/02", "9,000,000,000", "900,000,000,000", "4,000,000", "46,500.00", "-448.72"]],
}


class ParseTests(unittest.TestCase):
    def test_parse(self):
        rows = twse_market.parse_payload(PAYLOAD)
        self.assertEqual(rows[0]["date"], "2026-09-01")
        self.assertAlmostEqual(rows[0]["taiex"], 46948.72)
        self.assertAlmostEqual(rows[1]["change"], -448.72)
        self.assertEqual(rows[0]["turnover"], 1187571567117)
        self.assertEqual(twse_market.parse_payload({"stat": "查無資料"}), [])


def _index_rows(values, start=date(2026, 6, 1)):
    rows, prev = [], None
    for i, v in enumerate(values):
        rows.append({"date": (start + timedelta(days=i)).isoformat(), "taiex": v,
                     "change": 0.0 if prev is None else v - prev, "volume": 1, "turnover": 1, "transactions": 1})
        prev = v
    return rows


class RelativeStrengthTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        n = 70
        start = date.today() - timedelta(days=n - 1)
        db.save_market_index(_index_rows([100.0 + i * 0.5 for i in range(n)], start))
        db.save_stock_price([price_row((start + timedelta(days=i)).isoformat(), close=50.0 + i) for i in range(n)])

    def test_normalized_lines_and_excess(self):
        frame = market_index.relative_strength("2330", days=120)
        self.assertEqual(len(frame), 70)
        self.assertAlmostEqual(frame["stock_index"].iloc[0], 100.0)
        self.assertAlmostEqual(frame["taiex_index"].iloc[-1], (100 + 69 * 0.5) / 100 * 100)
        excess = market_index.excess_returns(frame)
        stock20 = (119.0 / 99.0 - 1) * 100
        taiex20 = (134.5 / 124.5 - 1) * 100
        self.assertAlmostEqual(excess[20]["excess"], stock20 - taiex20)
        self.assertIsNotNone(excess[60])
        self.assertIn("超額", market_index.stock_prompt_block("2330"))

    def test_index_summary(self):
        s = market_index.index_summary()
        self.assertAlmostEqual(s["taiex"], 134.5)
        self.assertAlmostEqual(s["return_5"], (134.5 / 132.0 - 1) * 100)
        self.assertIn("加權指數 134.50", market_index.market_prompt_block())

    def test_missing_data(self):
        self.assertTrue(market_index.relative_strength("9999").empty)
        self.assertIn("無法計算", market_index.stock_prompt_block("9999"))


class BackfillTests(TempDBTestCase):
    def test_skips_complete_past_months_but_always_refreshes_current(self):
        db.save_market_index(_index_rows([100.0] * 20, date(2026, 8, 1)))  # 8 月已有 20 天
        calls = []

        def fake(year, month):
            calls.append((year, month))
            return []

        with patch.object(market_index.twse_market, "fetch_month", side_effect=fake):
            stats = market_index.backfill(3, sleep_seconds=0, today=date(2026, 9, 17))
        self.assertEqual(calls, [(2026, 9), (2026, 7)])
        self.assertEqual(stats["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
