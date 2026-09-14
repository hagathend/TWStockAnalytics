import unittest
from datetime import date, timedelta

import pandas as pd

from src import backtest


def _frame(code, opens, closes, signal_days=(), volume=1_000_000):
    """最小欄位的訊號表：只放回測需要的欄位，signal_days 是 breakout_20d 為 True 的索引"""
    start = date(2026, 1, 1)
    n = len(closes)
    return pd.DataFrame({
        "date": [(start + timedelta(days=i)).isoformat() for i in range(n)],
        "code": code,
        "open": opens,
        "close": closes,
        "vol_ma20": volume,
        **{key: [False] * n for key in backtest.SIGNALS},
    }).assign(breakout_20d=[i in signal_days for i in range(n)])


class ForwardReturnTests(unittest.TestCase):
    def test_entry_next_open_exit_nth_close(self):
        df = _frame("A", opens=[10, 20, 30, 40], closes=[11, 21, 44, 41])
        out = backtest.add_forward_returns(df, horizons=(2,))
        # 第 0 天訊號：隔天開盤 20 進場，第 2 天收盤 44 出場 → +120%
        self.assertAlmostEqual(out.loc[0, "fwd_ret_2"], 120.0)
        # 最後兩天沒有未來資料
        self.assertTrue(out["fwd_ret_2"].iloc[-2:].isna().all())

    def test_no_leak_across_stocks(self):
        df = pd.concat([_frame("A", [10] * 3, [10] * 3), _frame("B", [99] * 3, [99] * 3)])
        out = backtest.add_forward_returns(df, horizons=(1,))
        a = out[out["code"] == "A"]
        self.assertTrue(a["fwd_ret_1"].iloc[-1:].isna().all())
        self.assertTrue((a["fwd_ret_1"].dropna() == 0).all())


class BacktestSignalTests(unittest.TestCase):
    def _market(self):
        # A：訊號在第 1 天出現並持續到第 2 天（連續兩天只算一次），之後上漲
        a = _frame("A", opens=[100, 100, 100, 110, 120, 130], closes=[100, 100, 105, 115, 125, 130],
                   signal_days=(1, 2))
        # B：無訊號、價格不動 → 基準報酬被拉低
        b = _frame("B", opens=[50] * 6, closes=[50] * 6)
        # C：有訊號但均量太低，應被流動性門檻排除
        c = _frame("C", opens=[10] * 6, closes=[10, 10, 5, 5, 5, 5], signal_days=(1,), volume=1000)
        return backtest.add_forward_returns(pd.concat([a, b, c]), horizons=(2,))

    def test_counts_only_new_triggers_and_filters_liquidity(self):
        stats = backtest.backtest_signal(self._market(), "breakout_20d", 2, min_avg_volume_lots=500)
        self.assertEqual(stats["events"], 1)
        # A 第 1 天訊號：第 2 天開盤 100 進場，第 3 天收盤 115 出場 → +15%
        self.assertAlmostEqual(stats["mean"], 15.0)
        self.assertEqual(stats["win_rate"], 100.0)
        # 同一天基準 = (A 15% + B 0%) / 2 = 7.5%，C 被流動性排除
        self.assertAlmostEqual(stats["baseline_mean"], 7.5)
        self.assertAlmostEqual(stats["excess_mean"], 7.5)

    def test_every_day_mode_counts_persistent_signal_twice(self):
        stats = backtest.backtest_signal(self._market(), "breakout_20d", 2, new_only=False)
        self.assertEqual(stats["events"], 2)

    def test_signal_without_events(self):
        stats = backtest.backtest_signal(self._market(), "gap_up", 2)
        self.assertEqual(stats["events"], 0)
        self.assertIsNone(stats["mean"])

    def test_backtest_all_has_every_signal(self):
        table = backtest.backtest_all(self._market(), 2)
        self.assertEqual(list(table["signal"]), list(backtest.SIGNALS))
        self.assertNotIn("returns", table.columns)

    def test_sample_period(self):
        start, end = backtest.sample_period(self._market(), 2)
        self.assertEqual(start, "2026-01-01")
        self.assertEqual(end, "2026-01-04")


if __name__ == "__main__":
    unittest.main()
