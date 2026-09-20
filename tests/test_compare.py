import unittest

import pandas as pd

from src import compare


def _closes(pairs):
    return pd.DataFrame(pairs, columns=["date", "close"])


class CompareTest(unittest.TestCase):
    def test_normalize_common_start_and_ffill(self):
        trend = compare.normalize({
            "A": _closes([("2026-01-01", 10), ("2026-01-02", 11), ("2026-01-03", 12), ("2026-01-05", 15)]),
            "B": _closes([("2026-01-02", 50), ("2026-01-03", 40), ("2026-01-05", 45)]),  # 晚一天開始
            "C": _closes([("2026-01-02", 20), ("2026-01-05", 30)]),                      # 1/3 停牌
        })
        self.assertEqual(trend.index[0], "2026-01-02")
        self.assertEqual(list(trend["A"]), [100, 12 / 11 * 100, 15 / 11 * 100])
        self.assertEqual(trend.loc["2026-01-03", "C"], 100)  # 停牌沿用前一天
        self.assertAlmostEqual(trend.loc["2026-01-05", "B"], 90)

    def test_empty(self):
        self.assertTrue(compare.normalize({"A": _closes([])}).empty)

    def test_metrics_table(self):
        trend = compare.normalize({"A": _closes([("d1", 10), ("d2", 12), ("d3", 9)]),
                                   "B": _closes([("d1", 5), ("d2", 5), ("d3", 6)])})
        fundamentals = pd.DataFrame({"code": ["A"], "pe_ratio": [15.0], "yoy_pct": [20.0], "unused": [1]})
        table = compare.metrics_table(["A", "B", "Z"], {"A": "甲", "B": "乙"}, trend, {"A": 9.0}, [fundamentals, None])
        self.assertEqual(list(table.columns), ["code", *compare.METRIC_LABELS])
        a = table.set_index("code").loc["A"]
        self.assertAlmostEqual(a["period_return"], -10)
        self.assertAlmostEqual(a["max_drawdown"], (9 / 12 - 1) * 100)
        self.assertEqual((a["name"], a["close"], a["pe_ratio"]), ("甲", 9.0, 15.0))
        z = table.set_index("code").loc["Z"]  # 抓不到股價的也要留一列
        self.assertTrue(pd.isna(z["period_return"]))


if __name__ == "__main__":
    unittest.main()
