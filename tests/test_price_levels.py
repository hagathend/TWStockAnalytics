import unittest
from unittest.mock import patch

import pandas as pd

from _db_fixture import TempDBTestCase
from src import price_levels, stock_analysis


def _frame(closes, spread=1.0, volumes=None):
    n = len(closes)
    return pd.DataFrame({
        "date": [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)],
        "high": [c + spread for c in closes], "low": [c - spread for c in closes], "close": closes,
        "volume": volumes or [1000] * n,
    })


def _zigzag():
    """在 100 與 120 之間來回震盪三次，最後收在 110"""
    up = [100 + i * 2 for i in range(11)]       # 100 → 120
    down = [120 - i * 2 for i in range(1, 11)]  # 118 → 100
    series = up + down + up[1:] + down + up[1:] + down + [102, 104, 106, 108, 110]
    return series


class SupportResistanceTests(unittest.TestCase):
    def test_zigzag_levels(self):
        levels = price_levels.support_resistance(_frame(_zigzag()))
        self.assertAlmostEqual(levels["close"], 110)
        self.assertAlmostEqual(levels["supports"][0]["price"], 99.0)   # 轉折低點 100 - 1
        self.assertAlmostEqual(levels["resistances"][0]["price"], 121.0)
        self.assertGreaterEqual(levels["resistances"][0]["touches"], 2)
        self.assertLess(levels["supports"][0]["distance_pct"], 0)

    def test_nearby_swings_merge(self):
        points = [(100.0, "d1", "low"), (101.0, "d2", "low"), (120.0, "d3", "high")]
        clusters = price_levels._cluster(points)
        self.assertEqual(len(clusters), 2)
        self.assertAlmostEqual(clusters[0]["price"], 100.5)
        self.assertEqual(clusters[0]["touches"], 2)
        self.assertEqual(clusters[0]["last_date"], "d2")

    def test_short_history(self):
        self.assertEqual(price_levels.support_resistance(_frame([100.0] * 5))["supports"], [])

    def test_zero_price_points_skipped(self):
        # 暫停交易日價格為 0，曾經讓合併價位時除以 0（3665 貿聯-KY 2026-06-10）
        clusters = price_levels._cluster([(0.0, "d0", "low"), (100.0, "d1", "low"), (101.0, "d2", "low")])
        self.assertEqual([(100.5, 2)], [(c["price"], c["touches"]) for c in clusters])

    def test_from_finmind_drops_zero_rows(self):
        rows = [{"date": "2026-06-09", "max": 10.0, "min": 9.0, "close": 9.5, "Trading_Volume": 100},
                {"date": "2026-06-10", "max": 0.0, "min": 0.0, "close": 0.0, "Trading_Volume": 0},
                {"date": "2026-06-11", "max": 11.0, "min": 10.0, "close": 10.5, "Trading_Volume": 200}]
        self.assertEqual(["2026-06-09", "2026-06-11"], list(price_levels.from_finmind(rows)["date"]))

    def test_finmind_fetch_drops_suspended_days(self):
        from src.collectors import finmind
        rows = [{"date": "2026-06-10", "open": 0, "max": 0, "min": 0, "close": 0},
                {"date": "2026-06-11", "open": 10, "max": 11, "min": 9, "close": 10}]
        with patch.object(finmind, "_request", return_value=rows):
            self.assertEqual(["2026-06-11"], [r["date"] for r in finmind.fetch_stock_price("3665", "a", "b")])


class VolumeProfileTests(unittest.TestCase):
    def test_poc_and_value_area(self):
        closes = [100.0] * 10 + [110.0] * 2 + [90.0] * 2
        volumes = [10_000] * 10 + [1000] * 4
        profile = price_levels.volume_profile(_frame(closes, spread=0.5, volumes=volumes), bins=20)
        self.assertAlmostEqual(profile["poc"], 100.0, delta=1.0)
        self.assertLessEqual(profile["value_area_low"], 100.0)
        self.assertGreaterEqual(profile["value_area_high"], 100.0)
        self.assertAlmostEqual(profile["bins"]["volume"].sum(), sum(volumes))

    def test_flat_or_empty(self):
        self.assertIsNone(price_levels.volume_profile(_frame([100.0] * 5, spread=0.0)))
        self.assertIsNone(price_levels.volume_profile(pd.DataFrame(columns=["high", "low", "close", "volume"])))


class PromptTests(TempDBTestCase):
    def test_finmind_conversion_and_prompt_block(self):
        rows = [{"date": d, "open": c, "max": h, "min": l, "close": c, "Trading_Volume": v}
                for d, h, l, c, v in _frame(_zigzag()).itertuples(index=False)]
        frame = price_levels.from_finmind(rows)
        text = price_levels.summarize_for_prompt(frame)
        self.assertIn("支撐：99.00", text)
        self.assertIn("成交量最密集價位", text)
        with patch.object(stock_analysis, "_fetch_price_rows", return_value=rows):
            prompt = stock_analysis.build_stock_analysis_prompt("2330")
        self.assertIn("【支撐壓力與成交量密集區】", prompt)
        self.assertIn("壓力：121.00", prompt)


if __name__ == "__main__":
    unittest.main()
