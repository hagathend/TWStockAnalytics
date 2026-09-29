import unittest
from unittest.mock import patch

from _db_fixture import TempDBTestCase
from src import ai_analysis, scheduled_ai
from src.storage import db


def _news(title, content="內文", date="2026-09-29"):
    return {"date": date, "source": "cnyes", "title": title, "url": f"https://x/{title}", "summary": "",
            "content": content, "published_at": f"{date} 10:00", "related_code": None,
            "collected_at": f"{date} 20:00"}


class SummaryReuseTest(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_news([_news("台積電法說會"), _news("聯發科新品")])
        rows = {r["title"]: r["id"] for r in db.query_news("2026-09-29")}
        db.save_news_excerpt(rows["台積電法說會"], "既有摘要")  # 這篇之前已經摘要過

    def _gather(self, force=False):
        calls = []

        def summarize(title, content):
            calls.append(title)
            return f"新摘要:{title}"

        with patch.object(ai_analysis.news_relevance, "select_stock_news", side_effect=lambda rows, index, n: rows):
            error, summaries, excerpts = ai_analysis._gather_and_summarize("2026-09-29", summarize, force=force)
        return calls, error, summaries, excerpts

    def test_existing_excerpt_is_reused(self):
        calls, error, summaries, excerpts = self._gather()
        self.assertIsNone(error)
        self.assertEqual(calls, ["聯發科新品"])                       # 只摘要沒有 excerpt 的那一篇
        self.assertIn("既有摘要", "".join(summaries))
        self.assertEqual({e["excerpt"] for e in excerpts}, {"既有摘要", "新摘要:聯發科新品"})

    def test_force_redoes_everything(self):
        calls, *_ = self._gather(force=True)
        self.assertEqual(sorted(calls), ["台積電法說會", "聯發科新品"])


class AlreadyAnalyzedTest(TempDBTestCase):
    def test_skips_when_summary_and_picks_exist(self):
        date = "2026-09-29"
        self.assertIsNone(ai_analysis.already_analyzed(date))
        db.save_ai_analysis_summary(date, "codex-cli", "總結")
        self.assertIsNone(ai_analysis.already_analyzed(date))  # 只有總結還不算
        db.save_ai_picks(date, [{"rank": 1, "code": "2330", "name": "台積電", "reason": "法說"}])
        self.assertIsNotNone(ai_analysis.already_analyzed(date))

        with patch.object(ai_analysis, "_gather_and_summarize") as gather:
            result = ai_analysis.analyze_with_codex_deep(date)
        gather.assert_not_called()                              # 不會再送 Codex
        self.assertTrue(result["ok"] and result["skipped"])
        self.assertEqual(len(result["picks"]), 1)
        self.assertIn("已經分析過", result["message"])

    def test_scheduled_run_reuses_and_reports(self):
        date = "2026-09-29"
        db.save_ai_analysis_summary(date, "codex-cli", "總結")
        db.save_ai_picks(date, [{"rank": 1, "code": "2330", "name": "台積電", "reason": "法說"}])
        logs = []
        with patch.object(scheduled_ai, "load_codex_settings",
                          return_value={"auto_analyze_after_collect": True}), \
                patch.object(ai_analysis, "_gather_and_summarize") as gather:
            self.assertTrue(scheduled_ai.run_after_collect(date, log=logs.append))
        gather.assert_not_called()
        self.assertTrue(any("已經分析過" in line for line in logs))


class StockSkipTest(TempDBTestCase):
    def test_analyze_stocks_skips_today(self):
        date = "2026-09-29"
        from src.stock_analysis import save_stock_analysis
        save_stock_analysis("2330", "方向：偏多\n分析內容", date)
        calls = []
        with patch("src.codex_cli.generate_codex_text", side_effect=lambda *a, **k: (calls.append(a), (True, "新分析"))[1]):
            outcome = scheduled_ai.analyze_stocks([{"code": "2330", "name": "台積電"},
                                                   {"code": "2317", "name": "鴻海"}], date)
        self.assertEqual(outcome["skipped"], ["2330"])
        self.assertEqual(outcome["done"], ["2317"])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
