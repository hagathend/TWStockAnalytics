import unittest
from datetime import date

import pandas as pd

from src import dividend_history as dh


def _policy(year, ex, cash=0.0, stock=0.0):
    return {"year": year, "CashEarningsDistribution": cash, "CashStatutorySurplus": 0, "StockEarningsDistribution": stock,
            "StockStatutorySurplus": 0, "CashExDividendTradingDate": ex if cash else "",
            "StockExDividendTradingDate": ex if stock else ""}


PRICES = [{"date": d, "close": c} for d, c in [
    ("2025-07-01", 100), ("2025-07-02", 95), ("2025-07-03", 97), ("2025-07-04", 100.5), ("2025-07-07", 99),
    ("2026-03-17", 50), ("2026-03-18", 51),
]]
RESULTS = [{"date": "2025-07-02", "before_price": 100.0}, {"date": "2026-03-17", "before_price": 55.0},
           {"date": "2026-03-18", "before_price": 50.0, "stock_and_cache_dividend": 1.0, "stock_or_cache_dividend": "息"},
           {"date": "2026-03-17", "before_price": 55.0, "stock_and_cache_dividend": 2.0, "stock_or_cache_dividend": "息"}]


class DividendHistoryTest(unittest.TestCase):
    def setUp(self):
        self.events = dh.build_events(
            [_policy("113年", "2025-07-02", cash=5.0, stock=1.0), _policy("114年第1季", "2026-03-17", cash=2.0),
             _policy("114年第2季", "", cash=2.5), _policy("112年", "2024-07-01")],  # 最後一筆沒配，略過
            RESULTS, PRICES)

    def test_events(self):
        self.assertEqual(len(self.events), 4)
        extra = self.events[self.events["ex_date"] == "2026-03-18"].iloc[0]  # 政策還沒進來，用除息結果補
        self.assertEqual((extra["cash"], extra["fill_days"]), (1.0, 1))
        first = self.events.iloc[0]
        self.assertEqual(first["fiscal_year"], 2024)
        self.assertAlmostEqual(first["yield_pct"], (5 + 0.1 * 100) / 100 * 100)  # 股票股利 1 元＝0.1 股
        self.assertEqual(first["fill_days"], 3)          # 除息日算第 1 天，第 3 個交易日收盤回到 100
        self.assertTrue(pd.isna(self.events.iloc[1]["fill_days"]))  # 還沒回到 55
        self.assertTrue(pd.isna(self.events.iloc[-1]["ex_date"]))    # 已公告、尚未除息，排最後

    def test_annual_payout_and_streak(self):
        annual = dh.annual_table(self.events, {2025: 9.0})
        row = annual.set_index("fiscal_year").loc[2025]
        self.assertAlmostEqual(row["cash"], 4.5)
        self.assertAlmostEqual(row["payout_pct"], 50.0)
        self.assertTrue(annual.set_index("fiscal_year")["payout_pct"].isna()[2024])
        self.assertEqual(dh.consecutive_years(annual, 2026), 2)

    def test_trailing_cash(self):
        self.assertAlmostEqual(dh.trailing_cash(self.events, date(2026, 6, 30)), 5.0 + 2.0 + 1.0)
        self.assertAlmostEqual(dh.trailing_cash(self.events, date(2026, 12, 31)), 3.0)

    def test_western_year(self):
        self.assertEqual(dh._western_year("114年第2季"), 2025)
        self.assertIsNone(dh._western_year(""))

    def test_empty(self):
        self.assertTrue(dh.annual_table(dh.build_events([], [], [])).empty)


if __name__ == "__main__":
    unittest.main()
