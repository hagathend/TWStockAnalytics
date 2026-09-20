import unittest
from datetime import date
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import day_trading, rankings
from src.collectors import day_trading as collector
from src.storage import db

PAYLOAD = {"stat": "OK", "date": "20260916", "tables": [
    {"title": "統計", "fields": ["當日沖銷交易總成交股數"], "data": [["1,000"]]},
    {"title": "個股", "fields": ["證券代號", "證券名稱", "暫停現股賣出後現款買進當沖註記", "當日沖銷交易成交股數",
                                "當日沖銷交易買進成交金額", "當日沖銷交易賣出成交金額"],
     "data": [["2330", "台積電", "", "3,000,000", "7,000,000,000", "7,010,000,000"],
              ["0050", "元大台灣50", "", "1,000", "100", "100"]]},
]}


def _dt(d, code="2330", volume=3_000_000, market="TWSE"):
    return {"date": d, "market": market, "code": code, "name": "", "volume": volume, "buy_value": 100, "sell_value": 120}


class ParseTest(unittest.TestCase):
    def test_parse(self):
        rows = collector.parse(PAYLOAD, "20260916", "TWSE")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"date": "2026-09-16", "market": "TWSE", "code": "2330", "name": "台積電",
                                   "volume": 3_000_000, "buy_value": 7_000_000_000, "sell_value": 7_010_000_000})

    def test_date_mismatch_is_empty(self):
        # 尚未公布時官方會回前一個交易日，不能當成今天的資料
        self.assertEqual(collector.parse(PAYLOAD, "20260917", "TWSE"), [])


class DayTradingDBTest(TempDBTestCase):
    def test_history_ratio_and_latest(self):
        db.save_stock_price([price_row("2026-09-15", volume=10_000_000), price_row("2026-09-16", volume=6_000_000),
                             price_row("2026-09-16", code="0050", volume=1_000_000)])
        db.save_day_trading([_dt("2026-09-15"), _dt("2026-09-16"), _dt("2026-09-16", code="0050")])
        frame = day_trading.code_history("2330", today=date(2026, 9, 17))
        self.assertEqual(list(frame["day_trade_pct"]), [30.0, 50.0])
        latest = day_trading.latest_table()
        self.assertEqual(list(latest["code"]), ["2330"])  # ETF 不算
        self.assertAlmostEqual(latest["day_trade_pct"].iloc[0], 50.0)
        self.assertIn("當沖比 最新 50.0%", day_trading.summarize_for_prompt("2330"))

    def test_backfill_skips_existing_dates(self):
        db.save_stock_price([price_row("2026-09-15"), price_row("2026-09-16")])
        db.save_day_trading([_dt("2026-09-15")])
        calls = []

        def fake(market):
            def fetch(d):
                calls.append((market, d))
                return [_dt(f"{d[:4]}-{d[4:6]}-{d[6:]}", market=market)]
            return fetch

        with patch.dict(day_trading._MARKETS, {"TWSE": ("上市", fake("TWSE")), "TPEx": ("上櫃", fake("TPEx"))}):
            stats = day_trading.backfill(days=10, sleep_seconds=0, today=date(2026, 9, 16))
        self.assertEqual(sorted(calls), [("TPEx", "20260915"), ("TPEx", "20260916"), ("TWSE", "20260916")])
        self.assertEqual(stats["filled"], 3)

    def test_ranking(self):
        db.save_stock_price([price_row("2026-09-16", volume=6_000_000),
                             price_row("2026-09-16", code="2317", name="鴻海", volume=500_000)])
        db.save_day_trading([_dt("2026-09-16"), _dt("2026-09-16", code="2317", volume=400_000)])
        result = rankings.rank(rankings.daily_table("2026-09-16"), "當沖比")
        self.assertEqual(list(result["code"]), ["2330"])  # 鴻海只有 500 張，不列入
        self.assertAlmostEqual(result["day_trade_pct"].iloc[0], 50.0)


if __name__ == "__main__":
    unittest.main()
