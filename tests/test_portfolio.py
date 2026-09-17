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


def _buy(tid, date, shares, price, fee=0, code="2330", reason=""):
    return {"id": tid, "date": date, "code": code, "name": "台積電", "side": "buy", "shares": shares,
            "price": price, "fee": fee, "tax": 0, "reason": reason}


def _sell(tid, date, shares, price, fee=0, tax=0, code="2330", reason=""):
    return {"id": tid, "date": date, "code": code, "name": "台積電", "side": "sell", "shares": shares,
            "price": price, "fee": fee, "tax": tax, "reason": reason}


class FeeTaxTests(unittest.TestCase):
    def test_fee_discount_floor_and_minimums(self):
        self.assertEqual(portfolio.estimate_fee(1000, 100.0), 142)          # 100,000 × 0.1425% = 142.5 → 142
        self.assertEqual(portfolio.estimate_fee(1000, 100.0, 0.28), 39)     # 39.9 → 39
        self.assertEqual(portfolio.estimate_fee(1000, 10.0, 0.28), 20)      # 整股最低 20
        self.assertEqual(portfolio.estimate_fee(10, 10.0, 0.28), 1)         # 零股最低 1

    def test_tax_stock_vs_etf(self):
        self.assertEqual(portfolio.estimate_tax("2330", 1000, 100.0), 300)
        self.assertEqual(portfolio.estimate_tax("0050", 1000, 100.0), 100)


class ReplayTests(unittest.TestCase):
    def test_average_cost_with_partial_sell(self):
        trades = [
            _buy(1, "2026-08-01", 1000, 100.0, fee=20),
            _buy(2, "2026-08-10", 1000, 120.0, fee=20),   # 成本 220,040，均價 110.02
            _sell(3, "2026-09-01", 500, 130.0, fee=10, tax=195),
        ]
        state = portfolio.replay(trades)["2330"]
        self.assertEqual(state["shares"], 1500)
        self.assertAlmostEqual(state["cost"], 220040 - 110.02 * 500)
        sale = state["realized"][0]
        self.assertAlmostEqual(sale["avg_cost"], 110.02)
        self.assertAlmostEqual(sale["pnl"], 500 * 130 - 10 - 195 - 110.02 * 500)
        self.assertEqual(sale["holding_days"], 31)
        self.assertEqual([b["id"] for b in sale["lot_buys"]], [1, 2])

    def test_selling_out_resets_lot(self):
        trades = [_buy(1, "2026-08-01", 1000, 100.0), _sell(2, "2026-08-05", 1000, 110.0),
                  _buy(3, "2026-09-01", 1000, 90.0), _sell(4, "2026-09-03", 1000, 95.0)]
        state = portfolio.replay(trades)["2330"]
        self.assertEqual(state["shares"], 0)
        second = state["realized"][1]
        self.assertEqual(second["opened_date"], "2026-09-01")      # 新的一段持有重新起算
        self.assertEqual([b["id"] for b in second["lot_buys"]], [3])
        self.assertAlmostEqual(second["pnl"], 5000.0)

    def test_oversell_rejected_and_order_by_date_not_input(self):
        with self.assertRaises(portfolio.TradeError):
            portfolio.replay([_buy(1, "2026-08-01", 1000, 100.0), _sell(2, "2026-08-02", 2000, 110.0)])
        # 先輸入賣出、後補登較早的買進 → 依日期重播就合理
        self.assertIsNone(portfolio.validate([_sell(1, "2026-08-05", 1000, 110.0), _buy(2, "2026-08-01", 1000, 100.0)]))

    def test_summarize_position(self):
        state = portfolio.replay([_buy(1, "2026-08-01", 1000, 100.0, fee=40), _buy(2, "2026-08-02", 3000, 120.0)])["2330"]
        price = {"date": "2026-09-14", "name": "台積電", "close": 110.0, "change": 2.0}
        p = portfolio.summarize_position(state, price, today=date(2026, 9, 14))
        self.assertEqual(p["shares"], 4000)
        self.assertAlmostEqual(p["avg_cost"], (100040 + 360000) / 4000)
        self.assertEqual(p["holding_days"], 44)
        self.assertAlmostEqual(p["pnl"], 440000 - 460040)


class PortfolioDBTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_stock_price([price_row("2026-09-11", close=100.0), price_row("2026-09-14", close=110.0),
                             price_row("2026-09-14", code="6488", name="環球晶", close=400.0, market="TPEx")])

    def test_positions_from_trades_sorted_by_value(self):
        db.add_trade("2026-09-01", "2330", "台積電", "buy", 2000, 100.0)
        db.add_trade("2026-09-02", "6488", "環球晶", "buy", 1000, 500.0)
        db.add_trade("2026-09-03", "9999", "不存在", "buy", 1000, 10.0)
        db.add_trade("2026-09-04", "2330", "台積電", "sell", 1000, 105.0, fee=20, tax=315)
        positions = portfolio.load_positions()
        self.assertEqual([p["code"] for p in positions], ["6488", "2330", "9999"])
        self.assertEqual(positions[1]["shares"], 1000)
        totals = portfolio.portfolio_totals(positions)
        self.assertEqual(totals["unpriced"], 1)
        realized = portfolio.realized_trades()
        self.assertAlmostEqual(realized[0]["pnl"], 105000 - 20 - 315 - 100000)
        self.assertEqual(portfolio.realized_trades(year=2025), [])

    def test_as_of_ignores_later_trades(self):
        db.add_trade("2026-09-01", "2330", "台積電", "buy", 1000, 100.0)
        db.add_trade("2026-09-12", "2330", "台積電", "sell", 1000, 105.0)
        self.assertEqual([p["code"] for p in portfolio.load_positions(as_of="2026-09-11")], ["2330"])
        self.assertEqual(portfolio.load_positions(), [])

    def test_holdings_migrated_once(self):
        with db.get_conn() as conn:
            conn.execute("DELETE FROM app_meta")
            conn.execute("INSERT INTO holdings (code, name, shares, cost_price, buy_date, note, created_at) "
                         "VALUES ('2330', '台積電', 1000, 100.0, '2026-09-01', '舊紀錄', '2026-09-01T10:00:00')")
        db.init_db()
        trades = db.query_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades[0]["side"], trades[0]["reason"], trades[0]["price"]), ("buy", "舊紀錄", 100.0))
        db.delete_trade(trades[0]["id"])
        db.init_db()  # 使用者刪光交易後不可重新匯入
        self.assertEqual(db.query_trades(), [])

    def test_latest_close_respects_as_of(self):
        self.assertEqual(db.query_latest_close("2330")["close"], 110.0)
        self.assertEqual(db.query_latest_close("2330", "2026-09-12")["close"], 100.0)
        self.assertIsNone(db.query_latest_close("0000"))

    def test_prompt_summary_includes_buy_reasons(self):
        self.assertIsNone(portfolio.summarize_for_prompt("2330"))
        db.add_trade("2026-09-01", "2330", "台積電", "buy", 1000, 100.0, reason="站回月線")
        db.add_trade("2026-09-05", "2330", "台積電", "buy", 500, 130.0)
        text = portfolio.summarize_for_prompt("2330")
        self.assertIn("持有 1 張 500 股，平均成本 110.00 元", text)
        self.assertIn("理由：站回月線", text)

    def test_review_prompt(self):
        db.add_trade("2026-09-11", "2330", "台積電", "buy", 1000, 100.0, reason="突破")
        sell_id = db.add_trade("2026-09-14", "2330", "台積電", "sell", 1000, 110.0, fee=20, tax=330, reason="達到目標價")
        prompt = portfolio.build_review_prompt(sell_id)
        self.assertIn("已實現損益 +9,650 元", prompt)
        self.assertIn("突破", prompt)
        self.assertIn("達到目標價", prompt)
        self.assertIn("期間收盤 100.00 → 110.00", prompt)
        self.assertIn("不要對這檔股票給出之後的買賣建議", prompt)
        self.assertIsNone(portfolio.build_review_prompt(99999))

    def test_stock_prompt_adds_holding_section_only_when_held(self):
        with patch.object(stock_analysis, "_fetch_price_rows", return_value=[]):
            without = stock_analysis.build_stock_analysis_prompt("2330")
            db.add_trade("2026-09-01", "2330", "台積電", "buy", 1000, 100.0)
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
