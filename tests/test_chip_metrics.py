import math
import unittest

import pandas as pd

from _db_fixture import TempDBTestCase, inst_row, margin_row, price_row
from src.chip_metrics import (
    compute_all_chip_metrics,
    compute_chip_metrics,
    metrics_for_code,
    prepare_history,
    signed_streak,
    summarize_for_prompt,
)
from src.storage import db

NAN = float("nan")


def _dates(n, start_day=1):
    return [f"2026-08-{start_day + i:02d}" for i in range(n)]


class SignedStreakTests(unittest.TestCase):
    def test_consecutive_buys(self):
        self.assertEqual(signed_streak([1, 2, 3]), 3)

    def test_consecutive_sells_after_buy(self):
        self.assertEqual(signed_streak([-1, 5, -2, -3]), -2)

    def test_last_zero_is_no_streak(self):
        self.assertEqual(signed_streak([1, 2, 0]), 0)

    def test_empty(self):
        self.assertEqual(signed_streak([]), 0)

    def test_unknown_day_stops_counting(self):
        # 中間有一天沒收集（NaN），不能跨越未知的日子繼續往前算
        self.assertEqual(signed_streak([1, NAN, 1, 1]), 2)

    def test_last_unknown_is_zero(self):
        self.assertEqual(signed_streak([1, 1, NAN]), 0)


class PrepareHistoryTests(TempDBTestCase):
    def test_missing_net_is_zero_only_on_collected_days(self):
        # 8/01：市場有收集法人資料，但 2330 不在名單 → 應補 0
        # 8/02：市場整天都沒收集法人資料 → 應保持 NaN（未知）
        db.save_stock_price([price_row("2026-08-01"), price_row("2026-08-02")])
        db.save_institutional([inst_row("2026-08-01", code="1101", foreign=5)])

        df = prepare_history(db.query_market_history(codes=["2330"]))
        day1 = df[df["date"] == "2026-08-01"].iloc[0]
        day2 = df[df["date"] == "2026-08-02"].iloc[0]
        self.assertEqual(day1["foreign_net"], 0)
        self.assertTrue(math.isnan(day2["foreign_net"]))


class ChipMetricsTests(TempDBTestCase):
    def _load(self, code="2330"):
        return prepare_history(db.query_market_history(codes=[code]))

    def test_streaks_and_window_sums(self):
        dates = _dates(25)
        # 外資：前 22 天賣 1000 股、最後 3 天買 2000 股；投信每天買 500 股
        foreign = [-1000] * 22 + [2000] * 3
        db.save_stock_price([price_row(d, volume=100_000) for d in dates])
        db.save_institutional([inst_row(d, foreign=f, trust=500) for d, f in zip(dates, foreign)])
        db.save_margin([margin_row(d) for d in dates])

        m = compute_chip_metrics(self._load())
        self.assertEqual(m["foreign_streak"], 3)
        self.assertEqual(m["trust_streak"], 25)
        self.assertEqual(m["foreign_net_5d"], 2000 * 3 + (-1000) * 2)
        self.assertEqual(m["foreign_net_20d"], 2000 * 3 + (-1000) * 17)
        self.assertEqual(m["trust_net_5d"], 2500)
        # 5日法人合計佔成交量：(4000 + 2500) / 500000
        self.assertAlmostEqual(m["inst_volume_ratio_5d"], 6500 / 500_000 * 100)
        self.assertEqual(m["days"], 25)

    def test_insufficient_history_returns_none_not_partial_sum(self):
        dates = _dates(3)
        db.save_stock_price([price_row(d) for d in dates])
        db.save_institutional([inst_row(d, foreign=1000) for d in dates])

        m = compute_chip_metrics(self._load())
        self.assertIsNone(m["foreign_net_5d"])
        self.assertIsNone(m["margin_change_5d"])
        self.assertEqual(m["foreign_streak"], 3)

    def test_margin_up_price_down_signal(self):
        dates = _dates(6)
        closes = [100, 99, 98, 97, 96, 95]
        balances = [1000, 1100, 1200, 1300, 1400, 1500]
        db.save_stock_price([price_row(d, close=c) for d, c in zip(dates, closes)])
        db.save_institutional([inst_row(d) for d in dates])
        db.save_margin([margin_row(d, margin_balance=b, short_balance=150) for d, b in zip(dates, balances)])

        m = compute_chip_metrics(self._load())
        self.assertEqual(m["margin_change_5d"], 500)
        self.assertAlmostEqual(m["margin_change_5d_pct"], 50.0)
        self.assertAlmostEqual(m["price_change_5d_pct"], -5.0)
        self.assertIn("融資增、股價跌", m["margin_price_signal"])
        self.assertAlmostEqual(m["short_margin_ratio"], 10.0)

    def test_stock_without_margin_data(self):
        dates = _dates(6)
        db.save_stock_price([price_row(d) for d in dates])
        db.save_institutional([inst_row(d) for d in dates])

        m = compute_chip_metrics(self._load())
        self.assertIsNone(m["margin_balance"])
        self.assertIsNone(m["short_margin_ratio"])
        self.assertIn("無資料", summarize_for_prompt(m))

    def test_all_metrics_one_row_per_stock(self):
        dates = _dates(5)
        for code in ("2330", "2317", "2454"):
            db.save_stock_price([price_row(d, code=code) for d in dates])
            db.save_institutional([inst_row(d, code=code, trust=100) for d in dates])

        result = compute_all_chip_metrics(prepare_history(db.query_market_history()))
        self.assertEqual(sorted(result["code"]), ["2317", "2330", "2454"])
        self.assertTrue((result["trust_streak"] == 5).all())

    def test_summary_text_contains_key_numbers(self):
        dates = _dates(6)
        db.save_stock_price([price_row(d) for d in dates])
        db.save_institutional([inst_row(d, foreign=3000) for d in dates])
        db.save_margin([margin_row(d) for d in dates])

        text = summarize_for_prompt(compute_chip_metrics(self._load()))
        self.assertIn("連買 6 天", text)
        self.assertIn("+15 張", text)  # 5日外資 15000 股 = 15 張


if __name__ == "__main__":
    unittest.main()


class MetricsForCodeTests(TempDBTestCase):
    def test_finds_tpex_stock_when_not_listed_on_twse(self):
        dates = _dates(3)
        db.save_stock_price([price_row(d, code="6488", name="環球晶", market="TPEx") for d in dates])
        db.save_institutional([inst_row(d, code="6488", foreign=1000, market="TPEx") for d in dates])
        metrics = metrics_for_code("6488", lookback_days=100_000)
        self.assertEqual(metrics["code"], "6488")
        self.assertEqual(metrics["foreign_streak"], 3)

    def test_unknown_code_returns_empty(self):
        self.assertEqual(metrics_for_code("9999", lookback_days=100_000), {})
        self.assertEqual(summarize_for_prompt({}), "（無籌碼歷史資料）")
