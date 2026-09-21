import unittest
from datetime import date, timedelta

import pandas as pd

from src import signals


def _history(closes, volumes=None, foreign=None, margin=None, code="1101"):
    """合成一檔股票的歷史：高低價＝收盤 ±1%，開盤＝前一天收盤"""
    n = len(closes)
    volumes = volumes or [1_000_000] * n
    foreign = foreign or [0] * n
    margin = margin or [10_000] * n
    start = date(2026, 1, 1)
    rows = []
    for i, close in enumerate(closes):
        rows.append({"code": code, "name": "測試", "date": (start + timedelta(days=i)).isoformat(),
                     "open": closes[i - 1] if i else close, "high": close * 1.01, "low": close * 0.99, "close": close,
                     "volume": volumes[i], "foreign_net": foreign[i], "trust_net": 0, "margin_balance": margin[i]})
    return pd.DataFrame(rows)


def _last(df: pd.DataFrame) -> pd.Series:
    return signals.compute_signals(df).iloc[-1]


def _decline(start, end, days):
    step = (end - start) / (days - 1)
    return [start + step * i for i in range(days)]


class ReversalSignalTest(unittest.TestCase):
    def test_position_and_drawdown(self):
        row = _last(_history(_decline(100, 70, 60) + [75]))
        self.assertLess(row["position_60d"], 30)
        self.assertLess(row["drawdown_60d"], -20)

    def test_reclaim_ma20_low(self):
        closes = _decline(100, 70, 60) + [69, 68.5, 68, 68.2, 68.4] + [80]
        row = _last(_history(closes))
        self.assertTrue(row["reclaim_ma20_low"])
        # 高檔站回月線不算（位置在上半部）
        high = _decline(60, 100, 60) + [97, 96, 95.5, 95.8, 96] + [101]
        self.assertFalse(_last(_history(high))["reclaim_ma20_low"])

    def test_rsi_rebound_and_kd_golden_low(self):
        closes = [100] * 30 + _decline(100, 70, 15) + [80]
        row = _last(_history(closes))
        self.assertTrue(row["rsi_rebound"], row["rsi14"])
        self.assertTrue(row["kd_golden_low"], (row["K"], row["D"]))

    def test_bullish_divergence(self):
        closes = [100] * 40 + _decline(100, 70, 8) + [72, 74, 76, 77, 78] + _decline(77.5, 69.5, 12)
        row = _last(_history(closes))
        self.assertTrue(row["bullish_divergence"], row["rsi14"])
        # 一路急跌、RSI 同步破底就不是背離
        straight = [100] * 40 + _decline(100, 50, 30)
        self.assertFalse(_last(_history(straight))["bullish_divergence"])

    def test_volume_dry_up(self):
        closes = _decline(100, 75, 55) + [76, 76.2, 75.9, 76.1, 76]
        volumes = [1_000_000] * 55 + [200_000] * 5
        self.assertTrue(_last(_history(closes, volumes))["volume_dry_up"])
        # 量沒縮
        self.assertFalse(_last(_history(closes))["volume_dry_up"])

    def test_inst_accumulate_low(self):
        closes = _decline(100, 80, 60)
        foreign = [0] * 57 + [500, 800, 300]
        self.assertTrue(_last(_history(closes, foreign=foreign))["inst_accumulate_low"])
        self.assertFalse(_last(_history(closes))["inst_accumulate_low"])

    def test_margin_down_price_stable(self):
        closes = _decline(100, 75, 55) + [75, 75.5, 75.2, 76, 76.5]
        margin = [10_000] * 55 + [9_900, 9_800, 9_700, 9_600, 9_500]
        self.assertTrue(_last(_history(closes, margin=margin))["margin_down_price_stable"])
        self.assertFalse(_last(_history(closes))["margin_down_price_stable"])

    def test_new_group_registered(self):
        self.assertIn("低檔轉折", signals.SIGNAL_GROUPS)
        for key in signals.SIGNAL_GROUPS["低檔轉折"]:
            self.assertEqual(signals.direction_of(key), "偏多")


if __name__ == "__main__":
    unittest.main()
