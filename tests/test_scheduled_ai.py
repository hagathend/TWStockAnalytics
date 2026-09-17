import unittest
from unittest.mock import patch

from src import scheduled_ai
from src.storage import db
from tests._db_fixture import TempDBTestCase

_POSITIONS = [{"code": "2330", "name": "台積電"}, {"code": "2317", "name": "鴻海"}]
_WATCH = {"2317": "鴻海", "2454": "聯發科"}


class StockTargetsTest(unittest.TestCase):
    def targets(self, **settings):
        with patch.object(scheduled_ai.portfolio, "load_positions", return_value=_POSITIONS), \
                patch.object(scheduled_ai, "load_watchlist", return_value=_WATCH):
            return scheduled_ai.stock_targets(settings)

    def test_nothing_enabled(self):
        self.assertEqual([], self.targets())

    def test_holdings_only(self):
        self.assertEqual(["2330", "2317"], [t["code"] for t in self.targets(auto_analyze_holdings=True)])

    def test_both_dedup_holdings_first(self):
        result = self.targets(auto_analyze_holdings=True, auto_analyze_watchlist=True)
        self.assertEqual([("2330", "持股"), ("2317", "持股"), ("2454", "觀察名單")],
                         [(t["code"], t["source"]) for t in result])


class AnalyzeStocksTest(TempDBTestCase):
    def test_skips_already_analyzed_and_collects_failures(self):
        db.save_stock_analysis("2026-09-17", "2330", "台積電", "舊的分析")
        stocks = [{"code": "2330", "name": "台積電"}, {"code": "2317", "name": "鴻海"}, {"code": "2454", "name": "聯發科"}]
        replies = {"2317": (True, "分析內容"), "2454": (False, "額度不足")}
        with patch("src.stock_analysis.build_stock_analysis_prompt", side_effect=lambda code: code), \
                patch("src.codex_cli.generate_codex_text", side_effect=lambda prompt: replies[prompt]) as gen:
            result = scheduled_ai.analyze_stocks(stocks, "2026-09-17")
        self.assertEqual(["2317"], result["done"])
        self.assertEqual(["2330"], result["skipped"])
        self.assertEqual([("2454", "額度不足")], result["failed"])
        self.assertEqual(2, gen.call_count)
        self.assertEqual("分析內容", db.query_stock_analysis("2026-09-17", "2317")[0]["analysis"])


class RunAfterCollectTest(unittest.TestCase):
    def run_with(self, settings, news_ok=True, stock_result=None):
        logs = []
        with patch.object(scheduled_ai, "load_codex_settings", return_value=settings), \
                patch("src.ai_analysis.analyze_with_codex_deep", return_value={"ok": news_ok, "message": "新聞"}) as news, \
                patch("src.ai_analysis.news_top_n", return_value=20), \
                patch.object(scheduled_ai, "stock_targets", return_value=[{"code": "2330", "name": "台積電"}] if stock_result else []), \
                patch.object(scheduled_ai, "analyze_stocks", return_value=stock_result) as stocks:
            ok = scheduled_ai.run_after_collect("2026-09-17", log=logs.append)
        return ok, news.called, stocks.called, logs

    def test_news_disabled_no_stocks(self):
        ok, news_called, stocks_called, _ = self.run_with({"auto_analyze_after_collect": False})
        self.assertTrue(ok)
        self.assertFalse(news_called)
        self.assertFalse(stocks_called)

    def test_stock_failure_marks_not_ok_but_news_still_runs(self):
        ok, news_called, stocks_called, logs = self.run_with(
            {"auto_analyze_after_collect": True}, stock_result={"done": [], "skipped": [], "failed": [("2330", "x")]})
        self.assertFalse(ok)
        self.assertTrue(news_called and stocks_called)
        self.assertTrue(any("最多 20 檔" in line for line in logs))

    def test_news_failure_does_not_block_stocks(self):
        ok, _, stocks_called, _ = self.run_with(
            {"auto_analyze_after_collect": True}, news_ok=False, stock_result={"done": ["2330"], "skipped": [], "failed": []})
        self.assertFalse(ok)
        self.assertTrue(stocks_called)


if __name__ == "__main__":
    unittest.main()
