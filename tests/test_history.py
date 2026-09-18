import unittest
from unittest.mock import patch

from src import history
from src.storage import db
from tests._db_fixture import TempDBTestCase


def _news(date, title, url, source="鉅亨網", summary="", related_code=None):
    return {"date": date, "source": source, "title": title, "url": url, "summary": summary, "content": None,
            "related_code": related_code, "published_at": f"{date}T10:00:00", "collected_at": f"{date}T20:00:00"}


class SearchQueriesTest(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_news([
            _news("2026-09-01", "台積電法說會", "u1", summary="先進製程"),
            _news("2026-09-10", "航運運價上漲", "u2", source="Google News", related_code="2603"),
            _news("2026-09-20", "台積電擴產", "u3"),
        ])
        db.save_ai_picks("2026-09-01", [{"rank": 1, "code": "2330", "name": "台積電", "reason": "法說會"},
                                        {"rank": 2, "code": "2603", "name": "長榮", "reason": "運價"}])
        db.save_ai_picks("2026-09-10", [{"rank": 1, "code": "2603", "name": "長榮", "reason": "運價續漲"},
                                        {"rank": 2, "code": "2330", "name": "台積電", "reason": "擴產"}])
        db.save_ai_picks("2026-09-11", [{"rank": 3, "code": "2603", "name": "長榮", "reason": "旺季"}])
        db.save_stock_analysis("2026-09-10", "2330", "台積電", "技術面：多頭排列")
        db.save_market_analysis("2026-09-10", "短期展望：震盪")

    def test_news_range_keyword_source(self):
        self.assertEqual(["u2", "u1"], [r["url"] for r in db.search_news("2026-09-01", "2026-09-15")])
        self.assertEqual(["u3", "u1"], [r["url"] for r in db.search_news("2026-09-01", "2026-09-30", "台積電")])
        self.assertEqual(["u1"], [r["url"] for r in db.search_news("2026-09-01", "2026-09-30", "先進")])
        self.assertEqual(["u2"], [r["url"] for r in db.search_news("2026-09-01", "2026-09-30", "2603")])
        self.assertEqual(["u2"], [r["url"] for r in db.search_news("2026-09-01", "2026-09-30", source="Google News")])
        self.assertEqual({"鉅亨網", "Google News"}, set(db.query_news_sources()))

    def test_picks_and_frequency(self):
        picks = db.search_ai_picks("2026-09-01", "2026-09-30")
        self.assertEqual([("2026-09-11", 3), ("2026-09-10", 1), ("2026-09-10", 2), ("2026-09-01", 1), ("2026-09-01", 2)],
                         [(p["date"], p["rank"]) for p in picks])
        self.assertEqual(2, len(db.search_ai_picks("2026-09-01", "2026-09-30", "運價")))
        freq = history.pick_frequency(picks)
        self.assertEqual(["2603", "2330"], list(freq["code"]))
        top = freq.iloc[0]
        self.assertEqual((3, 1, "2026-09-01", "2026-09-11", "旺季"),
                         (top["count"], top["best_rank"], top["first_date"], top["last_date"], top["last_reason"]))
        self.assertTrue(history.pick_frequency([]).empty)

    def test_analysis_searches_and_bounds(self):
        self.assertEqual(1, len(db.search_stock_analysis("2026-09-01", "2026-09-30", "多頭")))
        self.assertEqual(0, len(db.search_stock_analysis("2026-09-11", "2026-09-30")))
        self.assertEqual(1, len(db.search_market_analysis("2026-09-01", "2026-09-30", "震盪")))
        self.assertEqual(0, len(db.search_market_analysis("2026-09-01", "2026-09-30", "大漲")))
        self.assertEqual(("2026-09-01", "2026-09-20"), db.query_history_date_bounds())


class SearchViewsTest(unittest.TestCase):
    VIEWS = [
        {"start_date": "2026-09-01", "code": "2330", "name": "台積電", "direction": "偏多", "status": "done"},
        {"start_date": "2026-09-05", "code": "2603", "name": "長榮", "direction": "偏空", "status": "active"},
        {"start_date": "2026-09-20", "code": "2330", "name": "台積電", "direction": "中性", "status": "active"},
    ]

    def search(self, *args, **kwargs):
        return [(v["start_date"], v["code"]) for v in history.search_views(*args, views=self.VIEWS, **kwargs)]

    def test_filters(self):
        self.assertEqual([("2026-09-01", "2330"), ("2026-09-05", "2603")], self.search("2026-09-01", "2026-09-10"))
        self.assertEqual([("2026-09-05", "2603")], self.search("2026-09-01", "2026-09-30", "長榮"))
        self.assertEqual([("2026-09-01", "2330")], self.search("2026-09-01", "2026-09-30", direction="偏多"))
        self.assertEqual([("2026-09-05", "2603"), ("2026-09-20", "2330")], self.search("2026-09-01", "2026-09-30", status="active"))

    def test_default_reads_views_from_db(self):
        with patch.object(history.prediction_views, "build_views", return_value=self.VIEWS) as build:
            self.assertEqual(3, len(history.search_views("2026-09-01", "2026-09-30")))
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
