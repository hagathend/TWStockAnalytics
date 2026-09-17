import unittest
from datetime import date, timedelta

import pandas as pd

from _db_fixture import TempDBTestCase, price_row
from src import market_analysis, market_breadth
from src.storage import db


def _history(series: dict[str, list[float]], start=date(2026, 6, 1)):
    rows = []
    for code, closes in series.items():
        prev = None
        for i, close in enumerate(closes):
            rows.append({"date": (start + timedelta(days=i)).isoformat(), "code": code, "close": close,
                         "change": 0.0 if prev is None else close - prev, "turnover": 1000.0})
            prev = close
    return pd.DataFrame(rows)


class BreadthTests(unittest.TestCase):
    def test_new_highs_lows_and_warmup(self):
        n = 25
        flat = [100.0] * n
        rising = [100.0] * (n - 1) + [110.0]   # 最後一天創 20 日新高
        falling = [100.0] * (n - 1) + [90.0]   # 最後一天創 20 日新低
        breadth = market_breadth.compute_breadth(_history({"1101": flat, "2330": rising, "2317": falling}))
        last = breadth.iloc[-1]
        self.assertEqual((last["up"], last["down"], last["flat"]), (1, 1, 1))
        self.assertEqual(last["new_high_20"], 1)
        self.assertEqual(last["new_low_20"], 1)
        self.assertAlmostEqual(last["ad_ratio"], 1.0)
        # 前 20 天算不出 20 日新高，應為缺值而不是 0
        self.assertTrue(pd.isna(breadth.iloc[5]["new_high_20"]))
        self.assertTrue(pd.isna(last["new_high_60"]))  # 只有 25 天

    def test_equal_to_prior_high_is_not_new_high(self):
        breadth = market_breadth.compute_breadth(_history({"2330": [100.0] * 25}))
        self.assertEqual(breadth.iloc[-1]["new_high_20"], 0)

    def test_turnover_heat(self):
        history = _history({"2330": [100.0] * 22})
        history.loc[history.index[-1], "turnover"] = 3000.0
        breadth = market_breadth.compute_breadth(history)
        self.assertAlmostEqual(breadth.iloc[-1]["turnover_ma20_ratio"], 3.0)

    def test_prompt_text(self):
        breadth = market_breadth.compute_breadth(_history({"2330": [100.0] * 24 + [110.0], "2317": [100.0] * 25}))
        text = market_breadth.summarize_for_prompt(breadth)
        self.assertIn("收盤創 20 日新高 1 家", text)
        self.assertIn("近 5 日", text)
        self.assertEqual(market_breadth.summarize_for_prompt(pd.DataFrame()), "（無市場溫度計資料）")


class BreadthDBTests(TempDBTestCase):
    def test_excludes_etf_and_other_markets_and_feeds_market_prompt(self):
        rows = []
        for i in range(3):
            d = (date(2026, 9, 14) + timedelta(days=i)).isoformat()
            rows += [price_row(d, code="2330", close=100 + i), price_row(d, code="0050", close=50 + i),
                     price_row(d, code="6488", close=10 + i, market="TPEx")]
        for r in rows:
            r["change"] = 1.0
        db.save_stock_price(rows)
        breadth = market_breadth.breadth_until("2026-09-16")
        self.assertEqual(breadth.iloc[-1]["up"], 1)  # 只算上市個股 2330
        ok, prompt = market_analysis.build_market_analysis_prompt("2026-09-16")
        self.assertTrue(ok)
        self.assertIn("【市場溫度計】", prompt)


if __name__ == "__main__":
    unittest.main()
