import unittest
from unittest.mock import MagicMock, patch

from src import news_relevance as nr
from src.collectors import news_crawler

INDEX = {
    "2330": "台積電", "2454": "聯發科", "1459": "聯發", "3711": "日月光投控", "2025": "千興", "2027": "大成鋼",
    "1303": "南亞", "2408": "南亞科", "3008": "大立光", "4716": "大立", "3038": "全台", "4938": "和碩",
    "4991": "環宇-KY", "5009": "榮剛", "2327": "國巨*",
}


class MentionedCompaniesTest(unittest.TestCase):
    def test_code_formats(self):
        self.assertEqual(["2330"], nr.mentioned_companies("晶圓代工(2330)再創高", INDEX))
        self.assertEqual(["2330"], nr.mentioned_companies("晶圓代工（2330-TW）", INDEX))
        self.assertEqual(["2454"], nr.mentioned_companies("IC 設計 2454.TW 走強", INDEX))
        self.assertEqual([], nr.mentioned_companies("營收 9999 億、代號(9999)不存在", INDEX))

    def test_bare_numbers_and_years_are_not_codes(self):
        # 2025、2027 是千興、大成鋼的代號，但在新聞裡通常是年份
        self.assertEqual([], nr.mentioned_companies("預估2027年營收成長，(2025)年基期低", INDEX))
        self.assertEqual(["2027"], nr.mentioned_companies("鋼價回升，大成鋼(2027)股價走強", INDEX))

    def test_longer_names_win(self):
        self.assertEqual(["2454"], nr.mentioned_companies("聯發科發表新晶片", INDEX))
        self.assertEqual(["2408"], nr.mentioned_companies("南亞科 DRAM 報價", INDEX))
        self.assertEqual(["3008", "1303"], nr.mentioned_companies("大立光擴產，南亞也受惠", INDEX))

    def test_ambiguous_names_skipped_unless_code_given(self):
        self.assertEqual([], nr.mentioned_companies("全台住宅地震險投保率", INDEX))
        self.assertEqual(["3038"], nr.mentioned_companies("全台(3038)營收創高", INDEX))

    def test_suffix_alias_and_order(self):
        self.assertEqual(["4991", "2327"], nr.mentioned_companies("環宇漲停，國巨鉭電容漲價", INDEX))
        self.assertEqual(["4938", "2330"], nr.mentioned_companies("和碩看好 AI，台積電(2330)", INDEX))


class SelectStockNewsTest(unittest.TestCase):
    ROWS = [
        {"title": "央行理監事會利率不變", "content": "楊金龍表示……"},
        {"title": "大盤大漲 500 點", "content": "台積電、聯發科、日月光投控領漲"},
        {"title": "和碩法說看好 AI", "content": "和碩表示……"},
        {"title": "健康幣上線", "content": "下載 App"},
        {"title": "聯發科新晶片、台積電代工", "content": "聯發科與台積電合作"},
    ]

    def test_filters_and_ranks(self):
        titles = [r["title"] for r in nr.select_stock_news(self.ROWS, INDEX, limit=10)]
        # 標題有點名公司的優先（再依提到的公司數），只在內文提到的排後面；沒提到公司的丟掉
        self.assertEqual(["聯發科新晶片、台積電代工", "和碩法說看好 AI", "大盤大漲 500 點"], titles)

    def test_limit_and_no_index(self):
        self.assertEqual(1, len(nr.select_stock_news(self.ROWS, INDEX, limit=1)))
        self.assertEqual(self.ROWS[:2], nr.select_stock_news(self.ROWS, {}, limit=2))


def _page(page, last_page, ids):
    response = MagicMock()
    response.json.return_value = {"items": {"current_page": page, "last_page": last_page, "data": [
        {"newsId": i, "title": f"新聞{i}", "publishAt": 1_790_000_000, "content": "&lt;p&gt;內文&lt;/p&gt;"} for i in ids]}}
    return response


class FetchCnyesPaginationTest(unittest.TestCase):
    def test_fetches_all_pages_and_dedups(self):
        pages = {1: _page(1, 3, [1, 2]), 2: _page(2, 3, [2, 3]), 3: _page(3, 3, [4])}
        with patch.object(news_crawler.requests, "get", side_effect=lambda *a, params, **k: pages[params["page"]]) as get:
            rows = news_crawler.fetch_cnyes_news(page_delay=0)
        self.assertEqual(3, get.call_count)
        self.assertEqual(["新聞1", "新聞2", "新聞3", "新聞4"], [r["title"] for r in rows])
        self.assertEqual("內文", rows[0]["content"])

    def test_max_pages_cap(self):
        with patch.object(news_crawler.requests, "get",
                          side_effect=lambda *a, params, **k: _page(params["page"], 50, [params["page"]])) as get:
            rows = news_crawler.fetch_cnyes_news(max_pages=2, page_delay=0)
        self.assertEqual(2, get.call_count)
        self.assertEqual(2, len(rows))



class GatherSkipsNonStockNewsTest(unittest.TestCase):
    """摘要前的過濾有真的接進深度分析：沒提到公司的鉅亨網新聞不會送去摘要"""

    def test_only_stock_news_summarized(self):
        from src import ai_analysis
        from src.storage import db
        from tests._db_fixture import TempDBTestCase, price_row

        case = TempDBTestCase()
        case.setUp()
        try:
            db.save_stock_price([price_row("2026-09-17", "2330", "台積電"), price_row("2026-09-17", "2317", "鴻海")])
            news = [("央行利率不變", "楊金龍表示", "u1"), ("台積電擴產", "台積電宣布", "u2"), ("健康幣上線", "下載 App", "u3"),
                    ("大盤上漲", "鴻海領漲", "u4")]
            db.save_news([{"date": "2026-09-17", "source": "cnyes", "title": t, "url": u, "summary": "", "content": c,
                           "related_code": None, "published_at": f"2026-09-17T1{i}:00:00", "collected_at": "x"}
                          for i, (t, c, u) in enumerate(news)])
            summarized = []
            error, summaries, _ = ai_analysis._gather_and_summarize(
                "2026-09-17", lambda title, content: summarized.append(title) or "摘要")
            self.assertIsNone(error)
            self.assertEqual(["台積電擴產", "大盤上漲"], summarized)
            codes = {r["title"]: r["related_code"] for r in db.query_news("2026-09-17")}
            self.assertEqual("2330", codes["台積電擴產"])  # 摘要後把標題點名的公司寫進關聯代號
            self.assertIsNone(codes["央行利率不變"])
        finally:
            case.tearDown()


class RelatedCodesTest(unittest.TestCase):
    def test_title_and_excerpt(self):
        self.assertEqual("4991", nr.related_codes("200G PD量產 環宇-KY Q3業績有望逐季加溫", None, INDEX))
        self.assertEqual("4991,2330", nr.related_codes("環宇-KY 業績加溫", "環宇-KY(4991)…客戶含台積電", INDEX))
        self.assertIsNone(nr.related_codes("央行理監事會", "利率不變", INDEX))

    def test_limit_and_merge(self):
        many = "台積電、聯發科、和碩、南亞科、大立光、環宇、榮剛"
        self.assertEqual(nr.MAX_RELATED_CODES, len(nr.related_codes(many, None, INDEX).split(",")))
        self.assertEqual("2330,4991", nr.merge_related("2330", "4991,2330"))
        self.assertEqual("4991", nr.merge_related(None, "4991"))
        self.assertIsNone(nr.merge_related(None, None))


class FillMissingRelatedCodesTest(unittest.TestCase):
    def test_fills_only_empty(self):
        from src.storage import db
        from tests._db_fixture import TempDBTestCase, price_row

        case = TempDBTestCase()
        case.setUp()
        try:
            db.save_stock_price([price_row("2026-09-18", "4991", "環宇-KY"), price_row("2026-09-18", "2330", "台積電")])
            db.save_news([{"date": "2026-09-18", "source": "cnyes", "title": t, "url": u, "summary": "", "content": "",
                           "related_code": code, "published_at": "2026-09-18T10:00:00", "collected_at": "x"}
                          for t, u, code in [("環宇-KY Q3 加溫", "u1", None), ("台積電擴產", "u2", "9999"),
                                             ("央行利率不變", "u3", None)]])
            self.assertEqual(1, nr.fill_missing_related_codes())
            codes = {r["url"]: r["related_code"] for r in db.query_news("2026-09-18")}
            self.assertEqual({"u1": "4991", "u2": "9999", "u3": None}, codes)
            self.assertEqual(["u1"], [r["url"] for r in db.query_news("2026-09-18", "4991")])
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
