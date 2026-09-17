import unittest
from datetime import date, timedelta
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import fundamentals, pe_river
from src.storage import db

TODAY = date(2026, 9, 17)


def _seed(code="2330", days=100, pe_start=10.0, close=100.0):
    dates = [(TODAY - timedelta(days=days - i)).isoformat() for i in range(days)]
    db.save_stock_price([price_row(d, code=code, close=close) for d in dates])
    db.save_valuation([{"date": d, "market": "TWSE", "code": code, "name": code, "pe_ratio": pe_start + i * 0.1,
                        "dividend_yield": 1.0, "pb_ratio": 1.0} for i, d in enumerate(dates)])
    return dates


class RiverTests(TempDBTestCase):
    def test_bands_and_percentile(self):
        _seed()
        result = pe_river.river("2330", today=TODAY)
        self.assertEqual(result["days"], 100)
        self.assertAlmostEqual(result["current_pe"], 19.9)
        self.assertAlmostEqual(result["percentile"], 100.0)           # 本益比一路上升，目前最貴
        self.assertAlmostEqual(result["multiples"][50], 14.95, places=2)
        last = result["frame"].iloc[-1]
        self.assertAlmostEqual(last["eps"], 100 / 19.9)
        self.assertAlmostEqual(last["band_50"], last["eps"] * result["multiples"][50])
        self.assertIn("第 100 百分位", pe_river.summarize_for_prompt("2330"))

    def test_too_few_days_or_losses_excluded(self):
        _seed(days=50)
        self.assertIsNone(pe_river.river("2330", today=TODAY))
        _seed(code="1101", days=100)
        with db.get_conn() as conn:  # 讓大部分日子變成虧損（本益比 NULL）
            conn.execute("UPDATE valuation SET pe_ratio = NULL WHERE code = '1101' AND date < ?",
                         ((TODAY - timedelta(days=30)).isoformat(),))
        self.assertIsNone(pe_river.river("1101", today=TODAY))

    def test_latest_percentiles_table(self):
        _seed()
        dates = _seed(code="2317", pe_start=30.0)
        with db.get_conn() as conn:  # 2317 最新一天本益比掉到最低
            conn.execute("UPDATE valuation SET pe_ratio = 5 WHERE code = '2317' AND date = ?", (dates[-1],))
        table = pe_river.latest_percentiles(today=TODAY).set_index("code")
        self.assertAlmostEqual(table.loc["2330", "pe_percentile"], 100.0)
        self.assertAlmostEqual(table.loc["2317", "pe_percentile"], 1.0)

    def test_backfill_missing_dates_only(self):
        dates = _seed(days=5)
        extra = (TODAY - timedelta(days=10)).isoformat()  # 種子資料只涵蓋最近 5 天，這天缺本益比
        db.save_stock_price([price_row(extra, close=100.0)])
        calls = []
        with patch.object(pe_river.fundamentals_collector, "fetch_twse_valuation",
                          side_effect=lambda ymd: calls.append(ymd) or []):
            pe_river.backfill(30, sleep_seconds=0, today=TODAY)
        self.assertEqual(calls, [extra.replace("-", "")])
        self.assertNotIn(dates[0].replace("-", ""), calls)

    def test_fundamentals_prompt_includes_river(self):
        _seed(days=100)
        with patch.object(pe_river, "_date") as fake_date:
            fake_date.today.return_value = TODAY
            fake_date.fromisoformat = date.fromisoformat
            text = fundamentals.summarize_for_prompt("2330")
        self.assertIn("本益比河流", text)


if __name__ == "__main__":
    unittest.main()
