import unittest
from datetime import date, timedelta

from _db_fixture import TempDBTestCase, price_row
from src import predictions, stock_analysis
from src.storage import db


class ParsePredictionTests(unittest.TestCase):
    def test_standard_line(self):
        text = "總結：偏多看待\n預測摘要：方向=偏多；支撐=2,350；壓力=2480.5；信心=中"
        self.assertEqual(predictions.parse_prediction(text),
                         {"direction": "偏多", "support": 2350.0, "resistance": 2480.5, "confidence": "中"})

    def test_fullwidth_and_markdown_variants(self):
        text = "- **預測摘要**：方向：偏空，支撐：95，壓力：110，信心：低"
        result = predictions.parse_prediction(text)
        self.assertEqual(result["direction"], "偏空")
        self.assertEqual(result["support"], 95.0)
        self.assertEqual(result["confidence"], "低")

    def test_missing_optional_fields(self):
        result = predictions.parse_prediction("預測摘要：方向=中性")
        self.assertEqual(result, {"direction": "中性", "support": None, "resistance": None, "confidence": None})

    def test_no_prediction(self):
        self.assertIsNone(predictions.parse_prediction("技術面分析：偏多\n總結：觀望"))
        self.assertIsNone(predictions.parse_prediction(None))


class IsHitTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertTrue(predictions.is_hit("偏多", 1.5))
        self.assertFalse(predictions.is_hit("偏多", 0.5))  # 雜訊等級的漲幅不算命中
        self.assertTrue(predictions.is_hit("偏空", -2))
        self.assertTrue(predictions.is_hit("中性", -2.9))
        self.assertFalse(predictions.is_hit("中性", 3.5))


def _dates(n, start=date(2026, 8, 3)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class EvaluateTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        dates = _dates(12)
        # 2330 從 100 漲到 111；大盤另一檔 2317 持平
        rows = [price_row(d, close=100.0 + i) for i, d in enumerate(dates)]
        rows += [price_row(d, code="2317", name="鴻海", close=50.0) for d in dates]
        for r in rows:
            r["low"], r["high"] = r["close"] - 1, r["close"] + 1
        db.save_stock_price(rows)
        self.dates = dates

    def test_done_prediction(self):
        db.save_prediction(self.dates[0], "2330", "台積電",
                           {"direction": "偏多", "support": 98.0, "resistance": 108.0, "confidence": "中"})
        result = predictions.evaluate_all()[0]
        self.assertEqual(result["status"], "done")
        self.assertAlmostEqual(result["return_5"], 5.0)
        self.assertAlmostEqual(result["return_10"], 10.0)
        self.assertAlmostEqual(result["market_return_10"], 5.0)  # (10% + 0%) / 2
        self.assertTrue(result["hit"])
        self.assertFalse(result["support_broken"])   # 最低 100（第 1 天 low=101-1）
        self.assertTrue(result["resistance_reached"])  # 最高 111

        summary = predictions.summarize([result])
        self.assertEqual(summary["hit_rate"], 100.0)
        self.assertAlmostEqual(summary["by_direction"]["偏多"]["avg_excess"], 5.0)

    def test_pending_prediction(self):
        db.save_prediction(self.dates[5], "2330", "台積電", {"direction": "偏空"})
        result = predictions.evaluate_all()[0]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["days_elapsed"], 6)
        self.assertAlmostEqual(result["return_5"], 5 / 105 * 100)
        self.assertIsNone(result["hit"])

    def test_no_price_data(self):
        db.save_prediction(self.dates[0], "9999", "不存在", {"direction": "偏多"})
        self.assertEqual(predictions.evaluate_all()[0]["status"], "no_data")


class SaveHookTests(TempDBTestCase):
    def test_save_analysis_records_and_clears_prediction(self):
        db.save_stock_price([price_row("2026-09-14", close=100.0)])
        result = stock_analysis.save_stock_analysis("2330", "總結：看多\n預測摘要：方向=偏多；支撐=95；壓力=110；信心=高",
                                                    date="2026-09-14")
        self.assertIn("已記錄預測摘要", result["message"])
        self.assertEqual(db.query_predictions("2330")[0]["direction"], "偏多")
        # 同一天重新分析但沒有預測摘要 → 舊預測移除
        stock_analysis.save_stock_analysis("2330", "總結：觀望", date="2026-09-14")
        self.assertEqual(db.query_predictions("2330"), [])

    def test_strip_holding_keeps_prediction_line(self):
        text = "總結：C\n持股應對：成本 100\n預測摘要：方向=中性"
        self.assertEqual(stock_analysis.strip_holding_section(text), "總結：C\n預測摘要：方向=中性")


if __name__ == "__main__":
    unittest.main()
