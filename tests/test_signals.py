import unittest
from datetime import date, timedelta

import pandas as pd

from _db_fixture import TempDBTestCase, inst_row, margin_row, price_row
from src import signals
from src.chip_metrics import prepare_history, signed_streak
from src.storage import db


def _dates(n):
    start = date(2026, 1, 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _history(closes, code="2330", volumes=None, highs=None, lows=None, foreign=None, trust=None,
             margin=None, name="台積電"):
    """用收盤價序列組出 prepare_history 格式的 DataFrame；高低點預設等於收盤價"""
    n = len(closes)
    rows = []
    for i, d in enumerate(_dates(n)):
        rows.append({
            "date": d, "code": code, "name": name,
            "open": closes[i], "high": highs[i] if highs else closes[i],
            "low": lows[i] if lows else closes[i], "close": closes[i], "change": 0.0,
            "volume": volumes[i] if volumes else 1_000_000, "turnover": 0,
            "foreign_net": foreign[i] if foreign else 0, "trust_net": trust[i] if trust else 0,
            "dealer_net": 0, "total_net": 0,
            "margin_balance": margin[i] if margin else None, "short_balance": None,
            "inst_collected": 1, "margin_collected": 1,
        })
    return prepare_history(rows)


def _last(df, key):
    return bool(df.sort_values("date").iloc[-1][key])


class MovingAverageSignalTests(unittest.TestCase):
    def test_steady_uptrend_is_bull_alignment(self):
        df = signals.compute_signals(_history([100 + i for i in range(70)]))
        self.assertTrue(_last(df, "ma_bull"))
        self.assertFalse(_last(df, "ma_bear"))

    def test_steady_downtrend_is_bear_alignment(self):
        df = signals.compute_signals(_history([200 - i for i in range(70)]))
        self.assertTrue(_last(df, "ma_bear"))

    def test_insufficient_history_no_alignment(self):
        df = signals.compute_signals(_history([100 + i for i in range(40)]))
        self.assertFalse(df["ma_bull"].any())

    def test_flat_price_is_squeeze(self):
        df = signals.compute_signals(_history([100.0] * 25))
        self.assertTrue(_last(df, "ma_squeeze"))
        trending = signals.compute_signals(_history([100 * 1.02 ** i for i in range(25)]))
        self.assertFalse(_last(trending, "ma_squeeze"))


class BreakoutAndGapTests(unittest.TestCase):
    def test_breakout_above_prior_20_day_high(self):
        closes = [100.0] * 25 + [105.0]
        df = signals.compute_signals(_history(closes))
        self.assertTrue(_last(df, "breakout_20d"))
        self.assertFalse(_last(df, "breakout_60d"))  # 歷史不足 60 天

    def test_equal_to_prior_high_is_not_breakout(self):
        df = signals.compute_signals(_history([100.0] * 26))
        self.assertFalse(_last(df, "breakout_20d"))

    def test_breakdown_below_prior_20_day_low(self):
        df = signals.compute_signals(_history([100.0] * 25 + [95.0]))
        self.assertTrue(_last(df, "breakdown_20d"))

    def test_gap_up_requires_low_above_previous_high(self):
        closes = [100.0, 106.0]
        df = signals.compute_signals(_history(closes, highs=[101.0, 107.0], lows=[99.0, 102.0]))
        self.assertTrue(_last(df, "gap_up"))
        overlap = signals.compute_signals(_history(closes, highs=[101.0, 107.0], lows=[99.0, 100.5]))
        self.assertFalse(_last(overlap, "gap_up"))


class VolumeSignalTests(unittest.TestCase):
    def test_volume_long_red(self):
        closes = [100.0] * 21 + [105.0]
        volumes = [1_000_000] * 21 + [3_000_000]
        df = signals.compute_signals(_history(closes, volumes=volumes))
        self.assertTrue(_last(df, "volume_long_red"))
        self.assertFalse(_last(df, "volume_long_black"))

    def test_small_move_with_big_volume_is_not_long_red(self):
        closes = [100.0] * 21 + [102.0]
        volumes = [1_000_000] * 21 + [3_000_000]
        df = signals.compute_signals(_history(closes, volumes=volumes))
        self.assertFalse(_last(df, "volume_long_red"))

    def test_volume_long_black(self):
        closes = [100.0] * 21 + [95.0]
        volumes = [1_000_000] * 21 + [3_000_000]
        self.assertTrue(_last(signals.compute_signals(_history(closes, volumes=volumes)), "volume_long_black"))


class ChipSignalTests(unittest.TestCase):
    def test_streak_series_matches_signed_streak(self):
        values = pd.Series([1, -2, -3, 0, 4, 5, 6, float("nan"), 7, -1, -1])
        series = signals._streak_series(values)
        for i in range(len(values)):
            self.assertEqual(series.iloc[i], signed_streak(values.iloc[: i + 1]), msg=f"index {i}")

    def test_foreign_buy_streak(self):
        foreign = [-1] + [1000] * 5
        df = signals.compute_signals(_history([100.0] * 6, foreign=foreign))
        self.assertTrue(_last(df, "foreign_buy_streak"))
        df4 = signals.compute_signals(_history([100.0] * 6, foreign=[-1, -1] + [1000] * 4))
        self.assertFalse(_last(df4, "foreign_buy_streak"))

    def test_trust_adoption_needs_streak_and_volume_share(self):
        # 投信 5 日買 60,000 股 / 成交 5,000,000 股 = 1.2%
        trust = [0, 0, 20_000, 20_000, 20_000]
        df = signals.compute_signals(_history([100.0] * 5, trust=trust))
        self.assertTrue(_last(df, "trust_adoption"))
        small = signals.compute_signals(_history([100.0] * 5, trust=[0, 0, 1000, 1000, 1000]))
        self.assertFalse(_last(small, "trust_adoption"))

    def test_margin_up_price_down(self):
        closes = [100.0, 100, 100, 100, 100, 95]
        margin = [1000, 1000, 1000, 1000, 1000, 1200]
        self.assertTrue(_last(signals.compute_signals(_history(closes, margin=margin)), "margin_up_price_down"))
        no_margin = signals.compute_signals(_history(closes))
        self.assertFalse(_last(no_margin, "margin_up_price_down"))


class MarketWideTests(unittest.TestCase):
    def _market(self):
        frames = []
        for k in range(20):  # 20 檔股票，第 k 檔 20 日報酬為 k%
            closes = [100.0] * 20 + [100.0 + k]
            frames.append(_history(closes, code=f"{1000 + k}", name=f"S{k}",
                                   volumes=[600_000 if k else 100_000] * 21))
        return signals.compute_signals(pd.concat(frames, ignore_index=True))

    def test_strong_rs_is_top_decile_of_same_day(self):
        latest = signals.latest_rows(self._market())
        strong = set(latest.loc[latest["strong_rs"], "code"])
        self.assertEqual(strong, {"1018", "1019"})

    def test_screen_filters_volume_and_combines_signals(self):
        df = self._market()
        result = signals.screen(df, ["breakout_20d"], min_avg_volume_lots=500)
        # 1000 報酬 0% 不突破，且均量 100 張會被濾掉；其餘 19 檔突破
        self.assertEqual(len(result), 19)
        self.assertEqual(result.iloc[0]["code"], "1019")  # 依相對強弱排序
        both = signals.screen(df, ["breakout_20d", "strong_rs"], min_avg_volume_lots=500)
        self.assertEqual(set(both["code"]), {"1018", "1019"})
        either = signals.screen(df, ["breakout_20d", "strong_rs"], min_avg_volume_lots=0, mode="any")
        self.assertEqual(len(either), 19)

    def test_latest_rows_excludes_stale_stocks(self):
        fresh = _history([100.0] * 3, code="1111")
        stale = _history([100.0] * 2, code="2222")
        latest = signals.latest_rows(signals.compute_signals(pd.concat([fresh, stale])))
        self.assertEqual(list(latest["code"]), ["1111"])


class WatchlistAlertTests(unittest.TestCase):
    def test_new_vs_continuing_signals(self):
        closes = [100.0] * 25 + [105.0, 110.0]  # 倒數第二天就突破，最後一天持續突破
        volumes = [1_000_000] * 26 + [5_000_000]  # 最後一天才爆量長紅
        df = signals.compute_signals(_history(closes, volumes=volumes))
        alerts = signals.watchlist_alerts(df, ["2330", "9999"])
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertIn("volume_long_red", alert["new"])
        self.assertIn("breakout_20d", alert["continuing"])
        text = signals.format_alerts_markdown(alerts)
        self.assertIn("爆量長紅", text)
        self.assertIn("| 2330 |", text)

    def test_no_alerts_message(self):
        self.assertIn("沒有觸發", signals.format_alerts_markdown([]))


class LoadSignalHistoryTests(TempDBTestCase):
    def test_as_of_excludes_future_rows(self):
        dates = ["2026-09-01", "2026-09-02", "2026-09-03"]
        db.save_stock_price([price_row(d, close=100 + i) for i, d in enumerate(dates)])
        db.save_institutional([inst_row(d, foreign=100) for d in dates])
        db.save_margin([margin_row(d) for d in dates])
        df = signals.load_signal_history(as_of="2026-09-02", lookback_days=30)
        self.assertEqual(df["date"].max(), "2026-09-02")
        self.assertEqual(int(df.iloc[-1]["foreign_streak"]), 2)


if __name__ == "__main__":
    unittest.main()
