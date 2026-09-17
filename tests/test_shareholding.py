import unittest

from _db_fixture import TempDBTestCase
from src import shareholding
from src.collectors import tdcc
from src.storage import db

# 格式照抄集保 opendata CSV（2026-09-11），第 16 級（差異數調整）應被略過
CSV_TEXT = "﻿資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n" + "\n".join([
    "20260911,2330,1,2471985,288386732,1.11",
    "20260911,2330,15,1485,21996993078,84.82",
    "20260911,2330,16,0,0,0.00",
    "20260911,2330,17,3019610,25932370067,100.00",
    "20260911,00878,1,100,100,1.00",
])


def _week(date, code, levels: dict, holders: int):
    """levels: {分級: 比例%}"""
    rows = [{"date": date, "code": code, "level": lvl, "holders": 10, "shares": 1000, "pct": pct}
            for lvl, pct in levels.items()]
    rows.append({"date": date, "code": code, "level": 17, "holders": holders, "shares": 0, "pct": 100.0})
    return rows


class ParseTests(unittest.TestCase):
    def test_parse_skips_adjustment_level_and_filters_codes(self):
        rows = tdcc.parse_csv(CSV_TEXT, keep_code=lambda c: c == "2330")
        self.assertEqual([r["level"] for r in rows], [1, 15, 17])
        big = rows[1]
        self.assertEqual(big["date"], "2026-09-11")
        self.assertEqual(big["holders"], 1485)
        self.assertAlmostEqual(big["pct"], 84.82)


class ShareholdingMetricTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        base = {1: 5.0, 2: 3.0, 8: 2.0, 9: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 80.0}
        later = {1: 4.5, 2: 2.8, 8: 1.7, 9: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 81.0}
        db.save_shareholding(_week("2026-09-04", "2330", base, 3_000_000)
                             + _week("2026-09-11", "2330", later, 2_970_000)
                             + _week("2026-09-11", "2317", {15: 60.0}, 1_000_000))

    def test_code_summary_levels_and_weekly_change(self):
        s = shareholding.code_summary("2330")
        self.assertEqual(s["date"], "2026-09-11")
        self.assertEqual(s["weeks"], 2)
        self.assertAlmostEqual(s["big1000_pct"], 81.0)
        self.assertAlmostEqual(s["big400_pct"], 84.0)            # 12–15 級
        self.assertAlmostEqual(s["retail_pct"], 4.5 + 2.8 + 1.7)  # 1–8 級
        self.assertAlmostEqual(s["big1000_pct_change"], 1.0)
        self.assertAlmostEqual(s["retail_pct_change"], -1.0)
        self.assertAlmostEqual(s["holders_change_pct"], -1.0)

    def test_single_week_has_no_change(self):
        s = shareholding.code_summary("2317")
        self.assertIsNone(s["big1000_pct_change"])
        self.assertIsNone(s["holders_change_pct"])
        self.assertIsNone(shareholding.code_summary("9999"))

    def test_latest_table_for_screener(self):
        table = shareholding.latest_table().set_index("code")
        self.assertAlmostEqual(table.loc["2330", "big1000_pct_change"], 1.0)
        self.assertTrue(table["big1000_pct_change"].isna()["2317"])

    def test_prompt_text(self):
        text = shareholding.summarize_for_prompt("2330")
        self.assertIn("千張以上大戶持股 81.00%（較上週 +1.00 個百分點）", text)
        self.assertIn("總股東人數 2,970,000 人（較上週 -1.00%）", text)
        self.assertIn("無集保", shareholding.summarize_for_prompt("9999"))

    def test_resave_same_week_does_not_duplicate(self):
        db.save_shareholding(_week("2026-09-11", "2317", {15: 61.0}, 1_000_000))
        self.assertEqual(len(db.query_shareholding_history("2317")), 1)
        self.assertAlmostEqual(shareholding.code_summary("2317")["big1000_pct"], 61.0)


if __name__ == "__main__":
    unittest.main()
