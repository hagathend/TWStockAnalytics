import unittest
from datetime import date
from unittest.mock import patch

from _db_fixture import TempDBTestCase, inst_row, margin_row, price_row
from src import backfill
from src.storage import db

FRI = date(2026, 9, 11)
MON = date(2026, 9, 14)


class IterWeekdaysTests(unittest.TestCase):
    def test_skips_weekend_newest_first(self):
        days = list(backfill.iter_weekdays(date(2026, 9, 11), date(2026, 9, 14)))
        self.assertEqual(days, [MON, FRI])


class FakeTWSE:
    """模擬 TWSE 三個 rwd 介面；trading 以外的日期回空清單（＝查無資料）"""

    def __init__(self, trading_days, fail_days=()):
        self.trading = {d.strftime("%Y%m%d") for d in trading_days}
        self.fail = {d.strftime("%Y%m%d") for d in fail_days}
        self.calls = []

    def _iso(self, yyyymmdd):
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"

    def price(self, yyyymmdd):
        self.calls.append(("price", yyyymmdd))
        if yyyymmdd in self.fail:
            raise ConnectionError("模擬連線中斷")
        return [price_row(self._iso(yyyymmdd))] if yyyymmdd in self.trading else []

    def inst(self, yyyymmdd):
        self.calls.append(("inst", yyyymmdd))
        return [inst_row(self._iso(yyyymmdd), foreign=100)] if yyyymmdd in self.trading else []

    def margin(self, yyyymmdd):
        self.calls.append(("margin", yyyymmdd))
        return [margin_row(self._iso(yyyymmdd))] if yyyymmdd in self.trading else []

    def patches(self):
        base = "src.collectors.twse_official."
        return [patch(base + "fetch_twse_price", side_effect=self.price),
                patch(base + "fetch_twse_institutional", side_effect=self.inst),
                patch(base + "fetch_twse_margin", side_effect=self.margin)]


class BackfillTests(TempDBTestCase):
    def _run(self, fake, start, end, today=date(2026, 9, 20)):
        for p in fake.patches():
            p.start()
            self.addCleanup(p.stop)
        return backfill.backfill_twse(start, end, sleep_seconds=0, today=today)

    def test_trading_day_fills_all_three_tables(self):
        fake = FakeTWSE(trading_days=[FRI])
        stats = self._run(fake, FRI, FRI)

        self.assertEqual(stats["filled"], 1)
        for table in ("stock_price", "institutional", "margin"):
            self.assertIn("2026-09-11", db.query_dates_with_data(table))

    def test_second_run_sends_no_requests(self):
        fake = FakeTWSE(trading_days=[FRI])
        self._run(fake, FRI, MON)
        first_calls = len(fake.calls)

        fake.calls.clear()
        stats = backfill.backfill_twse(FRI, MON, sleep_seconds=0, today=date(2026, 9, 20))
        self.assertGreater(first_calls, 0)
        self.assertEqual(fake.calls, [], "已完成的交易日與已知的非交易日都不應該再發請求")
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["non_trading"], 1)

    def test_past_empty_day_marked_non_trading_and_only_price_requested(self):
        fake = FakeTWSE(trading_days=[])
        self._run(fake, MON, MON)

        self.assertIn("2026-09-14", db.query_non_trading_dates())
        self.assertEqual(fake.calls, [("price", "20260914")], "非交易日不應該再去問法人與融資")

    def test_today_empty_is_not_marked_non_trading(self):
        # 今天盤後可能還沒公布，查無資料不能當成休市
        fake = FakeTWSE(trading_days=[])
        self._run(fake, MON, MON, today=MON)
        self.assertNotIn("2026-09-14", db.query_non_trading_dates())

    def test_network_error_is_retried_next_time(self):
        fake = FakeTWSE(trading_days=[FRI], fail_days=[FRI])
        stats = self._run(fake, FRI, FRI)
        self.assertEqual(stats["failed"], ["2026-09-11"])
        self.assertNotIn("2026-09-11", db.query_non_trading_dates(), "連線錯誤不等於休市")

        fake.fail.clear()
        stats = backfill.backfill_twse(FRI, FRI, sleep_seconds=0, today=date(2026, 9, 20))
        self.assertEqual(stats["filled"], 1)

    def test_only_missing_tables_are_fetched(self):
        db.save_stock_price([price_row("2026-09-11")])
        db.save_institutional([inst_row("2026-09-11")])
        fake = FakeTWSE(trading_days=[FRI])
        self._run(fake, FRI, FRI)
        self.assertEqual(fake.calls, [("margin", "20260911")])

    def test_fill_recent_gaps_excludes_today(self):
        fake = FakeTWSE(trading_days=[MON])
        for p in fake.patches():
            p.start()
            self.addCleanup(p.stop)
        backfill.fill_recent_gaps(lookback_days=3, sleep_seconds=0, today=MON)
        self.assertNotIn(("price", "20260914"), fake.calls, "今天的資料交給每日收集本身處理")


if __name__ == "__main__":
    unittest.main()
