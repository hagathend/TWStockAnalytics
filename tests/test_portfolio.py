import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import portfolio, stock_analysis
from src.storage import db


class LotsTextTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(portfolio.lots_text(3000), "3 張")
        self.assertEqual(portfolio.lots_text(2500), "2 張 500 股")
        self.assertEqual(portfolio.lots_text(300), "300 股")


class SummarizePositionTests(unittest.TestCase):
    def test_weighted_average_cost_and_pnl(self):
        records = [
            {"code": "2330", "name": "台積電", "shares": 1000, "cost_price": 100.0, "buy_date": "2026-09-01"},
            {"code": "2330", "name": "台積電", "shares": 3000, "cost_price": 120.0, "buy_date": "2026-08-01"},
        ]
        price = {"date": "2026-09-14", "name": "台積電", "close": 110.0, "change": 2.0}
        p = portfolio.summarize_position(records, price, today=date(2026, 9, 14))
        self.assertEqual(p["shares"], 4000)
        self.assertAlmostEqual(p["avg_cost"], 115.0)  # (100*1000 + 120*3000) / 4000
        self.assertEqual(p["first_buy_date"], "2026-08-01")
        self.assertEqual(p["holding_days"], 44)
        self.assertAlmostEqual(p["market_value"], 440_000)
        self.assertAlmostEqual(p["pnl"], -20_000)
        self.assertAlmostEqual(p["pnl_pct"], -20_000 / 460_000 * 100)

    def test_no_price_leaves_pnl_empty(self):
        records = [{"code": "9999", "name": "", "shares": 1000, "cost_price": 50.0, "buy_date": None}]
        p = portfolio.summarize_position(records, None)
        self.assertIsNone(p["pnl"])
        self.assertIsNone(p["holding_days"])
        self.assertEqual(p["name"], "9999")


class PortfolioDBTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_stock_price([price_row("2026-09-11", close=100.0), price_row("2026-09-14", close=110.0),
                             price_row("2026-09-14", code="6488", name="環球晶", close=400.0, market="TPEx")])

    def test_crud_and_positions_sorted_by_value(self):
        first = db.add_holding("2330", "台積電", 2000, 100.0, "2026-09-01")
        db.add_holding("6488", "環球晶", 1000, 500.0, "2026-09-02")
        db.add_holding("9999", "不存在", 1000, 10.0)
        positions = portfolio.load_positions()
        self.assertEqual([p["code"] for p in positions], ["6488", "2330", "9999"])

        totals = portfolio.portfolio_totals(positions)
        self.assertEqual(totals["unpriced"], 1)
        self.assertAlmostEqual(totals["market_value"], 400_000 + 220_000)
        self.assertAlmostEqual(totals["pnl"], (400_000 - 500_000) + (220_000 - 200_000))

        db.update_holding(first, 1000, 90.0, "2026-09-01", "減碼一張")
        self.assertEqual(db.query_holdings("2330")[0]["shares"], 1000)
        db.delete_holding(first)
        self.assertEqual(db.query_holdings("2330"), [])

    def test_latest_close_respects_as_of(self):
        self.assertEqual(db.query_latest_close("2330")["close"], 110.0)
        self.assertEqual(db.query_latest_close("2330", "2026-09-12")["close"], 100.0)
        self.assertIsNone(db.query_latest_close("0000"))

    def test_prompt_summary(self):
        self.assertIsNone(portfolio.summarize_for_prompt("2330"))
        db.add_holding("2330", "台積電", 1000, 100.0, "2026-09-01")
        db.add_holding("2330", "台積電", 500, 130.0, "2026-09-05")
        text = portfolio.summarize_for_prompt("2330")
        self.assertIn("持有 1 張 500 股，平均成本 110.00 元（共 2 筆買進）", text)
        self.assertIn("未實現損益 +0 元", text)
        self.assertIn("買進明細", text)

    def test_stock_prompt_adds_holding_section_only_when_held(self):
        with patch.object(stock_analysis, "_fetch_price_rows", return_value=[]):
            without = stock_analysis.build_stock_analysis_prompt("2330")
            db.add_holding("2330", "台積電", 1000, 100.0, "2026-09-01")
            with_holding = stock_analysis.build_stock_analysis_prompt("2330")
        self.assertNotIn("【我的持股】", without)
        self.assertIn("以下五項結果", without)
        self.assertIn("【我的持股】", with_holding)
        self.assertIn("持股應對", with_holding)
        self.assertIn("以下六項結果", with_holding)


class StripHoldingSectionTests(unittest.TestCase):
    def test_removes_last_section_in_various_heading_styles(self):
        for heading in ("持股應對：", "5. 持股應對：", "**持股應對**：", "- 持股應對：", "## 持股應對", "五、持股應對："):
            text = "\n".join([
                "技術面分析：均線偏多", "籌碼面分析：外資連買", "總結：留意量能",
                heading, "- 成本 2350，跌破 2300 重新評估", "- 未實現損益 +45,000",
            ])
            result = stock_analysis.strip_holding_section(text)
            self.assertNotIn("持股應對", result, heading)
            self.assertNotIn("2350", result, heading)
            self.assertIn("總結：留意量能", result, heading)

    def test_section_in_middle_keeps_following_sections(self):
        text = "\n".join(["技術面分析：A", "持股應對：成本 100", "細節 B", "總結：C"])
        self.assertEqual(stock_analysis.strip_holding_section(text), "技術面分析：A\n總結：C")

    def test_text_without_holding_section_unchanged(self):
        text = "技術面分析：A\n\n總結：C"
        self.assertEqual(stock_analysis.strip_holding_section(text), text)
        self.assertEqual(stock_analysis.strip_holding_section(None), "")


class ReportSettingsTests(unittest.TestCase):
    def test_default_excludes_holdings_and_persists(self):
        from src import config_ai
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config_ai, "_REPORT_CONFIG_PATH", Path(tmp) / "report_settings.json"), \
                patch.object(config_ai, "DATA_DIR", Path(tmp)):
            self.assertFalse(config_ai.load_report_settings()["include_holdings"])
            config_ai.save_report_settings({"include_holdings": True})
            self.assertTrue(config_ai.load_report_settings()["include_holdings"])


if __name__ == "__main__":
    unittest.main()
