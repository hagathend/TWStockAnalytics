import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import calendar_events, config_watchlist
from src.collectors import dividends
from src.storage import db

TWSE_PAYLOAD = {
    "stat": "OK",
    "fields": ["除權除息日期", "股票代號", "名稱", "除權息", "無償配股率", "現金增資配股率", "現金增資認購價", "現金股利",
               "詳細資料", "參考價<br>試算", "最近一次申報資料 季別/日期", "最近一次申報每股 (單位)淨值", "最近一次申報每股 (單位)盈餘"],
    "data": [["115年09月22日", "2330", "台積電", "息", "0.00000000", "0", "0", "5.00000000", "", "", "", "", ""],
             ["115年10月05日", "00406A", "主動中信台灣收益", "息", "0", "0", "0",
              "<p style= text-align:center;>待公告實際收益分配金額</p>", "", "", "", "", ""]],
}
TPEX_ITEMS = [{"ExRrightsExDividendDate": "1150925", "SecuritiesCompanyCode": "4549", "CompanyName": "桓達",
               "ExRrightsExDividend": "除權息", "StockDividendRatio": "0.01999998", "CashDividend": "1.50000000"}]


class ParseTests(unittest.TestCase):
    def test_twse(self):
        rows = dividends.parse_twse(TWSE_PAYLOAD)
        self.assertEqual(rows[0]["ex_date"], "2026-09-22")
        self.assertEqual(rows[0]["kind"], "息")
        self.assertEqual(rows[0]["cash_dividend"], 5.0)
        self.assertIsNone(rows[1]["cash_dividend"])  # 「待公告」文字

    def test_tpex(self):
        row = dividends.parse_tpex(TPEX_ITEMS)[0]
        self.assertEqual((row["ex_date"], row["kind"], row["cash_dividend"]), ("2026-09-25", "權息", 1.5))
        self.assertAlmostEqual(row["stock_ratio"], 0.01999998)


class CalendarTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._watch = patch.object(config_watchlist, "_WATCHLIST_PATH", Path(self._tmp.name) / "w.json")
        self._watch.start()
        config_watchlist.save_watchlist({"4549": "桓達"})
        db.save_dividend_events(dividends.parse_twse(TWSE_PAYLOAD) + dividends.parse_tpex(TPEX_ITEMS))
        db.save_stock_price([price_row("2026-09-16", close=100.0)])
        db.add_trade("2026-09-01", "2330", "台積電", "buy", 2000, 100.0)
        db.save_prediction("2026-09-14", "2330", "台積電", {"direction": "偏多"})

    def tearDown(self):
        self._watch.stop()
        self._tmp.cleanup()
        super().tearDown()

    def test_events_flags_and_expected_dividend(self):
        events = calendar_events.upcoming_events(date(2026, 9, 17), 30)
        tsmc = events[(events["code"] == "2330") & (events["kind"] == calendar_events.KIND_DIVIDEND)].iloc[0]
        self.assertTrue(tsmc["in_holdings"])
        self.assertIn("預估領 10,000 元", tsmc["detail"])
        self.assertTrue(events[events["code"] == "4549"].iloc[0]["in_watchlist"])
        revenue = events[events["kind"] == calendar_events.KIND_REVENUE]
        self.assertEqual(list(revenue["date"]), ["2026-10-10"])
        prediction = events[events["kind"] == calendar_events.KIND_PREDICTION].iloc[0]
        self.assertEqual(prediction["date"], "2026-09-28")  # 9/14 起算 10 個平日
        self.assertEqual(list(events["date"]), sorted(events["date"]))

    def test_without_holdings_hides_shares(self):
        events = calendar_events.upcoming_events(date(2026, 9, 17), 30, include_holdings=False)
        tsmc = events[(events["code"] == "2330") & (events["kind"] == calendar_events.KIND_DIVIDEND)].iloc[0]
        self.assertFalse(tsmc["in_holdings"])
        self.assertNotIn("預估領", tsmc["detail"])

    def test_report_markdown_only_relevant(self):
        text = calendar_events.report_markdown(date(2026, 9, 20), 7, include_holdings=True)
        self.assertIn("2330 台積電", text)
        self.assertIn("4549 桓達", text)
        self.assertNotIn("00406A", text)     # 不在持股或觀察名單
        self.assertNotIn("AI 預測", text)
        hidden = calendar_events.report_markdown(date(2026, 9, 20), 7, include_holdings=False)
        self.assertNotIn("2330", hidden)     # 不含持股時，持股的除權息不列


if __name__ == "__main__":
    unittest.main()
