import unittest
from datetime import date
from unittest.mock import patch

from src import futures
from src.collectors import taifex
from src.storage import db
from tests._db_fixture import TempDBTestCase

_CSV = ("﻿日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),"
        "多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,"
        "空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)\n"
        "2026/08/03,臺股期貨,自營商,1000,1,1200,1,-200,-1,3000,1,2500,1,500,100\n"
        "2026/08/03,臺股期貨,投信,50,1,10,1,40,1,70000,1,1000,1,69000,1\n"
        "2026/08/03,臺股期貨,外資及陸資,50000,1,52000,1,-2000,-1,20000,1,110038,1,\"-90,038\",-999\n"
        "合計,,,,,,,,,,,,,,\n")


def _rows(day, foreign, trust=70000, dealer=0):
    return [{"date": day, "commodity": "TXF", "identity": identity, "long_trade": 0, "short_trade": 0,
             "net_trade": 0, "long_oi": 0, "short_oi": 0, "net_oi": value, "net_oi_value": 0}
            for identity, value in (("foreign", foreign), ("trust", trust), ("dealer", dealer))]


class ParseTest(unittest.TestCase):
    def test_parse_csv(self):
        rows = taifex.parse_csv(_CSV)
        self.assertEqual(3, len(rows))
        foreign = next(r for r in rows if r["identity"] == "foreign")
        self.assertEqual("2026-08-03", foreign["date"])
        self.assertEqual(-90038, foreign["net_oi"])
        self.assertEqual(110038, foreign["short_oi"])
        dealer = next(r for r in rows if r["identity"] == "dealer")
        self.assertEqual(-200, dealer["net_trade"])


class FuturesTest(TempDBTestCase):
    def test_summary_changes(self):
        days = [f"2026-08-{d:02d}" for d in range(3, 28)]
        for i, day in enumerate(days):
            db.save_futures_institutional(_rows(day, -90000 + i * 100))
        s = futures.summary("2026-08-27")
        self.assertEqual("2026-08-27", s["date"])
        self.assertEqual(-87600, s["foreign"])
        self.assertEqual(100, s["foreign_change_1"])
        self.assertEqual(500, s["foreign_change_5"])
        self.assertEqual(2000, s["foreign_change_20"])
        self.assertEqual(0, s["trust_change_1"])
        block = futures.market_prompt_block("2026-08-27")
        self.assertIn("外資 -87,600 口", block)
        self.assertIn("20 日 +2,000", block)

    def test_summary_as_of_excludes_later_days(self):
        db.save_futures_institutional(_rows("2026-08-03", -1000))
        db.save_futures_institutional(_rows("2026-08-04", -2000))
        s = futures.summary("2026-08-03")
        self.assertEqual(-1000, s["foreign"])
        self.assertIsNone(s["foreign_change_1"])
        self.assertIn("資料不足", futures.market_prompt_block("2026-08-03"))

    def test_empty(self):
        self.assertIsNone(futures.summary("2026-08-03"))
        self.assertEqual("（無期貨法人資料）", futures.market_prompt_block("2026-08-03"))

    def test_backfill_skips_complete_past_months(self):
        for d in range(1, 17):
            db.save_futures_institutional(_rows(f"2026-07-{d:02d}", -1))
        calls = []

        def fake_fetch(start, end, commodity="TXF"):
            calls.append((start, end))
            return _rows(start.isoformat(), -5)

        with patch.object(taifex, "fetch_range", side_effect=fake_fetch):
            stats = futures.backfill(3, sleep_seconds=0, today=date(2026, 8, 20))
        self.assertEqual([(date(2026, 8, 1), date(2026, 8, 20)), (date(2026, 6, 1), date(2026, 6, 30))], calls)
        self.assertEqual({"filled": 2, "skipped": 1, "failed": []}, stats)

    def test_backfill_year_boundary(self):
        calls = []
        with patch.object(taifex, "fetch_range", side_effect=lambda s, e, c="TXF": calls.append((s, e)) or []):
            futures.backfill(2, sleep_seconds=0, today=date(2026, 1, 10))
        self.assertEqual([(date(2026, 1, 1), date(2026, 1, 10)), (date(2025, 12, 1), date(2025, 12, 31))], calls)


if __name__ == "__main__":
    unittest.main()
