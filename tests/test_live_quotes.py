import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import requests

from src import live_quotes
from src.collectors import realtime

PAYLOAD = {"rtcode": "0000", "msgArray": [
    {"c": "2330", "n": "台積電", "ex": "tse", "z": "2460.0000", "y": "2425.0000", "o": "2460.0000", "h": "2460.0000",
     "l": "2435.0000", "v": "35250", "d": "20260918", "t": "13:30:00", "b": "2455.0000_2450.0000_", "u": "2665", "w": "2185"},
    # 這 5 秒沒成交：z 是「-」，改用最佳買價
    {"c": "6488", "n": "環球晶", "ex": "otc", "z": "-", "y": "912.0000", "b": "944.0000_943.0000_", "v": "15354",
     "d": "20260918", "t": "10:01:05"},
    {"tv": "-", "s": "-", "c": "", "z": "-"},  # 查錯市場的頻道
]}


class RealtimeParseTest(unittest.TestCase):
    def test_parse(self):
        quotes = realtime.parse(PAYLOAD)
        self.assertEqual(set(quotes), {"2330", "6488"})
        tsmc = quotes["2330"]
        self.assertEqual((tsmc["price"], tsmc["change"], tsmc["market"]), (2460.0, 35.0, "TWSE"))
        self.assertAlmostEqual(tsmc["change_pct"], 35 / 2425 * 100)
        self.assertEqual(tsmc["date"], "2026-09-18")
        self.assertEqual((quotes["6488"]["price"], quotes["6488"]["market"]), (944.0, "TPEx"))

    def test_fetch_queries_both_markets_and_reports_errors(self):
        resp = MagicMock()
        resp.json.return_value = PAYLOAD
        with patch.object(realtime.requests, "get", return_value=resp) as get:
            ok, quotes = realtime.fetch_quotes(["2330", "6488", "2330"])
        self.assertTrue(ok)
        self.assertEqual(get.call_args.kwargs["params"]["ex_ch"], "tse_2330.tw|otc_2330.tw|tse_6488.tw|otc_6488.tw")
        with patch.object(realtime.requests, "get", side_effect=requests.ConnectionError("blocked")):
            ok, message = realtime.fetch_quotes(["2330"])
        self.assertFalse(ok)
        self.assertIn("即時報價讀取失敗", message)


class LiveQuotesTest(unittest.TestCase):
    def test_position_table(self):
        quotes = realtime.parse(PAYLOAD)
        positions = [{"code": "2330", "name": "台積電", "shares": 1500, "cost": 3_600_000, "avg_cost": 2400.0},
                     {"code": "9999", "name": "查無", "shares": 1000, "cost": 10_000, "avg_cost": 10.0}]
        table = live_quotes.position_table(positions, quotes).set_index("code")
        self.assertEqual(table.loc["2330", "market_value"], 2460 * 1500)
        self.assertEqual(table.loc["2330", "pnl"], 2460 * 1500 - 3_600_000)
        self.assertEqual(table.loc["2330", "day_pnl"], 35 * 1500)
        self.assertTrue(pd.isna(table.loc["9999", "pnl"]))

    def test_quote_table_keeps_order_and_missing(self):
        table = live_quotes.quote_table([("6488", "環球晶"), ("9999", "查無"), ("2330", "台積電")], realtime.parse(PAYLOAD))
        self.assertEqual(list(table["code"]), ["6488", "9999", "2330"])
        self.assertTrue(pd.isna(table.iloc[1]["price"]))
        self.assertEqual(live_quotes.latest_stamp(realtime.parse(PAYLOAD)), "2026-09-18 13:30:00")

    def test_trading_time(self):
        self.assertTrue(live_quotes.is_trading_time(datetime(2026, 9, 18, 10, 0)))      # 週五
        self.assertFalse(live_quotes.is_trading_time(datetime(2026, 9, 18, 13, 31)))
        self.assertFalse(live_quotes.is_trading_time(datetime(2026, 9, 19, 10, 0)))     # 週六


if __name__ == "__main__":
    unittest.main()
