import unittest

import pandas as pd

from src import backtest, signals


class SignalGuideTest(unittest.TestCase):
    def test_every_signal_has_group_and_help(self):
        grouped = [k for keys in signals.SIGNAL_GROUPS.values() for k in keys]
        self.assertEqual(sorted(grouped), sorted(signals.SIGNALS))
        self.assertEqual(set(signals.SIGNAL_HELP), set(signals.SIGNALS))
        self.assertEqual(set(signals.GROUP_QUESTIONS), set(signals.SIGNAL_GROUPS))

    def test_summarize(self):
        same = signals.summarize(["ma_bull", "breakout_60d", "trust_adoption"])
        self.assertEqual(same["tone"], "up")
        self.assertIn("格局、事件、籌碼", same["status"])
        self.assertEqual(same["short"], "多3／空0")
        mixed = signals.summarize(["breakout_20d", "margin_up_price_down"])
        self.assertIn("分歧", mixed["status"])
        self.assertIn("偏空訊號同向", signals.summarize(["ma_bear", "gap_down"])["status"])
        self.assertIn("單一", signals.summarize(["gap_up"])["status"])
        self.assertIn("盤整", signals.summarize(["ma_squeeze"])["status"])
        self.assertEqual(signals.summary_text([]), "")


def _stats(events, excess):
    return {"events": events, "excess_mean": excess}


class ScorecardTest(unittest.TestCase):
    def test_describe(self):
        self.assertIn("一致", backtest.describe("偏多", {5: _stats(30, 1.2), 20: _stats(30, 2.0)}))
        self.assertIn("相反", backtest.describe("偏多", {5: _stats(30, -1.2), 20: _stats(30, -0.9)}))
        self.assertIn("一致", backtest.describe("偏空", {5: _stats(30, -1.2), 20: _stats(30, -0.1)}))  # 偏空跑輸才一致
        self.assertIn("差不多", backtest.describe("偏多", {5: _stats(30, 0.2), 20: _stats(30, -0.3)}))
        self.assertIn("時間拉長", backtest.describe("偏多", {5: _stats(30, 1.0), 20: _stats(30, -1.0)}))
        self.assertIn("樣本不足", backtest.describe("偏多", {5: _stats(3, 5.0), 20: _stats(2, 5.0)}))
        self.assertIn("不分多空", backtest.describe("中性", {5: _stats(30, 0.8)}))

    def test_scorecard_shape(self):
        rows = []
        for code in ("A", "B"):
            for i in range(30):
                row = {"code": code, "date": f"2026-01-{i + 1:02d}", "open": 10 + i, "close": 10 + i,
                       "vol_ma20": 1e7}
                row.update({k: (i % 7 == 0) for k in signals.SIGNALS})
                rows.append(row)
        frame = backtest.add_forward_returns(pd.DataFrame(rows))
        card = backtest.scorecard(frame)
        self.assertEqual(len(card), len(signals.SIGNALS))
        self.assertEqual(list(card["group"].unique()), list(signals.SIGNAL_GROUPS))
        for column in ("events_5", "win_rate_20", "excess_20", "verdict"):
            self.assertIn(column, card)


if __name__ == "__main__":
    unittest.main()
