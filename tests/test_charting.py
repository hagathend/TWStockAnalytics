import unittest
from datetime import date, timedelta

from src import charting


def _rows(start: date, days: int):
    rows, price, d = [], 100.0, start
    while len(rows) < days:
        if d.weekday() < 5:
            price += 1 if len(rows) % 3 else -1.5
            rows.append({"date": d.isoformat(), "open": price - 0.5, "max": price + 1, "min": price - 1,
                         "close": price, "Trading_Volume": 1000 + len(rows)})
        d += timedelta(days=1)
    return rows


class ToBarsTest(unittest.TestCase):
    def test_weekly_aggregation(self):
        rows = _rows(date(2026, 1, 5), 10)  # 兩個完整的週一到週五
        bars = charting.to_bars(rows, "週K")
        self.assertEqual(len(bars), 2)
        first = bars.iloc[0]
        week = rows[:5]
        self.assertEqual(first["date"], week[-1]["date"])
        self.assertEqual(first["open"], week[0]["open"])
        self.assertEqual(first["close"], week[-1]["close"])
        self.assertEqual(first["max"], max(r["max"] for r in week))
        self.assertEqual(first["min"], min(r["min"] for r in week))
        self.assertEqual(first["Trading_Volume"], sum(r["Trading_Volume"] for r in week))

    def test_monthly_aggregation_labels_last_trading_day(self):
        bars = charting.to_bars(_rows(date(2026, 1, 1), 60), "月K")
        self.assertEqual(bars.iloc[0]["date"], "2026-01-30")
        self.assertTrue(bars["date"].is_monotonic_increasing)

    def test_daily_keeps_rows(self):
        rows = _rows(date(2026, 1, 5), 7)
        self.assertEqual(len(charting.to_bars(rows, "日K")), 7)

    def test_empty(self):
        self.assertTrue(charting.to_bars([], "週K").empty)


class PrepareTest(unittest.TestCase):
    def test_trims_to_range_with_warm_moving_averages(self):
        today = date(2026, 9, 18)
        rows = _rows(today - timedelta(days=charting.fetch_days("日K", "3 個月")), 400)
        rows = [r for r in rows if r["date"] <= today.isoformat()]
        df = charting.prepare(rows, "日K", "3 個月", today=today)
        self.assertGreaterEqual(df["date"].iloc[0], (today - timedelta(days=90)).isoformat())
        self.assertFalse(df["MA_60"].isna().any())  # 暖身期足夠，畫面最左邊也有均線
        self.assertFalse(df["D"].isna().any())

    def test_weekly_moving_average_columns(self):
        today = date(2026, 9, 18)
        rows = [r for r in _rows(date(2024, 1, 1), 800) if r["date"] <= today.isoformat()]
        df = charting.prepare(rows, "週K", "1 年", today=today)
        self.assertIn("MA_10", df)
        self.assertFalse(df["MA_20"].isna().any())


class BuildTest(unittest.TestCase):
    def test_indicator_rows(self):
        rows = [r for r in _rows(date.today() - timedelta(days=400), 280) if r["date"] <= date.today().isoformat()]
        fig = charting.build_candlestick("9999", "測試", "日K", "6 個月", ["MACD", "KD"], rows=rows)
        names = {t.name for t in fig.data}
        self.assertTrue({"K", "D", "DIF", "MACD", "MA5日", "MA60日"} <= names)
        self.assertIn("yaxis4", fig.layout)  # 價格、成交量、KD、MACD 四列

    def test_no_rows(self):
        self.assertIsNone(charting.build_candlestick("9999", "測試", rows=[]))


if __name__ == "__main__":
    unittest.main()
