import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from _db_fixture import TempDBTestCase
from src import fundamentals, revenue
from src.collectors import mops_revenue
from src.storage import db

# 結構照抄公開資訊觀測站月營收彙總頁（Big5 解碼後），含兩個產業表格
HTML = """<html><body>
<table><tr><th colspan=11>產業別：水泥工業</th></tr><tr><th>公司代號</th><th>公司名稱</th></tr>
<tr><td>1101</td><td>台泥</td><td>13,744,103</td><td>13,382,706</td><td>13,535,929</td><td>2.70</td><td>1.53</td>
<td>85,211,435</td><td>83,916,845</td><td>1.54</td><td>-</td></tr>
<tr><td>合計</td><td></td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td></td></tr></table>
<table><tr><th colspan=11>產業別：半導體業</th></tr>
<tr><td>2330</td><td>台積電</td><td>467,580,548</td><td>442,679,969</td><td>323,165,707</td><td>5.62</td><td>44.68</td>
<td>2,872,064,238</td><td>2,096,211,240</td><td>37.01</td><td>-</td></tr></table>
</body></html>"""


def _month(code, ym, rev, yoy):
    return {"code": code, "year_month": ym, "revenue": rev, "yoy_pct": yoy}


class ParseTests(unittest.TestCase):
    def test_parse_rows_and_industry(self):
        rows = mops_revenue.parse_page(HTML, "2026-07", "TWSE")
        self.assertEqual([r["code"] for r in rows], ["1101", "2330"])  # 「合計」列略過
        tsmc = rows[1]
        self.assertEqual(tsmc["industry"], "半導體業")
        self.assertEqual(tsmc["revenue"], 467580548)
        self.assertAlmostEqual(tsmc["yoy_pct"], 44.68)


class SignalTests(unittest.TestCase):
    def test_new_high_and_growth_streak(self):
        months = pd.period_range("2025-08", "2026-08", freq="M").strftime("%Y-%m")
        revs = [100, 90, 95, 80, 85, 100, 110, 105, 108, 109, 111, 112, 120]  # 最後一個月創 12 個月新高
        yoys = [5, -1, 2, 3, -2, 1, 2, 3, 4, 5, 6, 7, 8]                      # 從 2026-01 起連續成長 8 個月
        history = pd.DataFrame([_month("2330", m, r, y) for m, r, y in zip(months, revs, yoys)])
        s = revenue.compute_signals(history).iloc[0]
        self.assertTrue(s["revenue_high_12m"])
        self.assertEqual(s["yoy_growth_streak"], 8)

    def test_needs_twelve_consecutive_months(self):
        history = pd.DataFrame([_month("2330", "2026-01", 100, 5), _month("2330", "2026-03", 200, 6)])
        s = revenue.compute_signals(history).iloc[0]
        self.assertIsNone(s["revenue_high_12m"])
        self.assertEqual(s["yoy_growth_streak"], 1)   # 2 月缺資料，連續月數不跨過缺口

    def test_not_new_high(self):
        months = pd.period_range("2025-09", "2026-08", freq="M").strftime("%Y-%m")
        history = pd.DataFrame([_month("2330", m, 100 if m != "2026-01" else 150, 1) for m in months])
        self.assertFalse(revenue.compute_signals(history).iloc[0]["revenue_high_12m"])


def _rev_row(code, ym, rev, yoy, market="TWSE"):
    return {"year_month": ym, "market": market, "code": code, "name": code, "industry": "", "revenue": rev,
            "revenue_last_month": None, "revenue_last_year": None, "mom_pct": None, "yoy_pct": yoy,
            "cum_revenue": None, "cum_revenue_last_year": None, "cum_yoy_pct": None}


class BackfillTests(TempDBTestCase):
    def test_skips_complete_months_and_records_failures(self):
        db.save_month_revenue([_rev_row(f"{1000 + i}", "2026-08", 1, 1) for i in range(800)])
        calls = []

        def fake_fetch(year, month, market):
            calls.append((year, month, market))
            if market == "TPEx":
                raise RuntimeError("timeout")
            return [_rev_row("2330", f"{year}-{month:02d}", 5, 2)]

        with patch.object(revenue.mops_revenue, "fetch_month", side_effect=fake_fetch):
            stats = revenue.backfill(2, sleep_seconds=0, today=date(2026, 9, 17))
        self.assertNotIn((2026, 8, "TWSE"), calls)          # 已有 800 家，視為完整
        self.assertIn((2026, 7, "TWSE"), calls)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(len(stats["failed"]), 2)           # 兩個月的 TPEx
        self.assertEqual(db.query_month_revenue_counts()[("2026-07", "TWSE")], 1)

    def test_prompt_includes_trend(self):
        months = pd.period_range("2025-09", "2026-08", freq="M").strftime("%Y-%m")
        db.save_month_revenue([_rev_row("2330", m, 100 + i, 3) for i, m in enumerate(months)])
        text = fundamentals.summarize_for_prompt("2330")
        self.assertIn("營收趨勢：已累積 12 個月營收；最新月營收創近 12 個月新高；年增率連續成長 12 個月", text)


if __name__ == "__main__":
    unittest.main()
