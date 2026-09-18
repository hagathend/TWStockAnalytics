import unittest
from datetime import date, timedelta

from src import prediction_views as pv
from src.storage import db
from tests._db_fixture import TempDBTestCase, price_row

DATES = [(date(2026, 8, 3) + timedelta(days=i)).isoformat() for i in range(30)]


def _p(i, direction, code="2330", name="台積電", **extra):
    return {"date": DATES[i], "code": code, "name": name, "direction": direction, **extra}


class GroupViewsTest(unittest.TestCase):
    def shape(self, rows, trading=DATES):
        return [(v["direction"], v["start_idx"], v["end_idx"], v["end_reason"], len(v["analyses"]))
                for v in pv.group_views(rows, trading)]

    def test_same_direction_merges_into_one_view(self):
        rows = [_p(0, "偏多"), _p(1, "偏多"), _p(2, "偏多")]
        self.assertEqual([("偏多", 0, 10, pv.REASON_EXPIRED, 3)], self.shape(rows))

    def test_direction_change_ends_view(self):
        rows = [_p(0, "偏多"), _p(1, "偏多"), _p(4, "中性"), _p(5, "偏空")]
        self.assertEqual([("偏多", 0, 4, pv.REASON_CHANGED, 2), ("中性", 4, 5, pv.REASON_CHANGED, 1),
                          ("偏空", 5, 15, pv.REASON_EXPIRED, 1)], self.shape(rows))

    def test_same_direction_after_window_starts_new_view(self):
        rows = [_p(0, "偏多"), _p(9, "偏多"), _p(10, "偏多"), _p(12, "偏多")]
        self.assertEqual([("偏多", 0, 10, pv.REASON_EXPIRED, 2), ("偏多", 10, 20, pv.REASON_EXPIRED, 2)],
                         self.shape(rows))

    def test_change_after_window_counts_as_expired_not_flip(self):
        rows = [_p(0, "偏多"), _p(14, "偏空")]
        self.assertEqual([("偏多", 0, 10, pv.REASON_EXPIRED, 1), ("偏空", 14, 24, pv.REASON_EXPIRED, 1)],
                         self.shape(rows))

    def test_active_when_not_enough_trading_days(self):
        rows = [_p(0, "偏多"), _p(2, "偏多")]
        self.assertEqual([("偏多", 0, None, None, 2)], self.shape(rows, DATES[:6]))

    def test_weekend_analysis_uses_previous_trading_day(self):
        trading = [DATES[0], DATES[3], DATES[4]]  # DATES[1]、[2] 不是交易日
        views = pv.group_views([{"date": DATES[2], "code": "2330", "name": "", "direction": "偏多"}], trading)
        self.assertEqual(0, views[0]["start_idx"])


class BuildViewsTest(TempDBTestCase):
    def setUp(self):
        super().setUp()
        # 2330 每天漲 1 元（100 起）；2317 持平當大盤基準
        rows = [price_row(d, close=100.0 + i) for i, d in enumerate(DATES[:14])]
        rows += [price_row(d, code="2317", name="鴻海", close=50.0) for d in DATES[:14]]
        db.save_stock_price(rows)

    def save(self, i, direction, **extra):
        db.save_prediction(DATES[i], "2330", "台積電", {"direction": direction, **extra})

    def test_scoring_statuses_and_summary(self):
        self.save(0, "偏多", support=95.0)
        self.save(1, "偏多", support=97.0)
        self.save(5, "偏空")   # 偏多持續 5 天後翻空
        self.save(6, "中性")   # 偏空只持續 1 天 → 太短不計
        views = pv.build_views()
        by_start = {v["start_date"]: v for v in views}
        bull, bear, neutral = by_start[DATES[0]], by_start[DATES[5]], by_start[DATES[6]]

        self.assertEqual(("done", 5, 2, pv.REASON_CHANGED), (bull["status"], bull["days"], bull["analyses"], bull["end_reason"]))
        self.assertAlmostEqual(5.0, bull["return_pct"])
        self.assertTrue(bull["hit"])
        self.assertAlmostEqual(2.5, bull["market_return"])  # 同期上市個股平均：2330 +5%、2317 持平
        self.assertAlmostEqual(2.5, bull["excess"])
        self.assertEqual(97.0, bull["support"])  # 取觀點內最新一次分析的支撐
        self.assertEqual(("too_short", None), (bear["status"], bear["hit"]))
        self.assertEqual(("active", None, "進行中"), (neutral["status"], neutral["end_date"], neutral["end_reason"]))
        self.assertEqual(7, neutral["days"])  # 到最新交易日（第 13 天）為止

        summary = pv.summarize(views)
        self.assertEqual((3, 1, 1, 1, 2), (summary["total"], summary["active"], summary["done"],
                                           summary["too_short"], summary["flips"]))
        self.assertEqual(1, summary["directional"]["count"])
        self.assertEqual(100.0, summary["directional"]["hit_rate"])
        self.assertNotIn("中性", summary["by_direction"])

        stats = pv.flip_stats(views)[0]
        self.assertEqual((4, 3, 2, 1, 1), (stats["analyses"], stats["views"], stats["flips"], stats["scored"], stats["hits"]))
        self.assertAlmostEqual(2 / 3 * 100, stats["flip_rate"])

        current = pv.current_views(views)
        self.assertEqual([DATES[6]], [v["start_date"] for v in current])

    def test_neutral_counted_separately(self):
        self.save(0, "中性")
        self.save(3, "偏多")
        summary = pv.summarize(pv.build_views())
        self.assertEqual(1, summary["directional"]["count"])   # 只有偏多那段算方向性命中率
        self.assertEqual(["偏多", "中性"], list(summary["by_direction"]))
        self.assertEqual(1, summary["by_direction"]["中性"]["count"])
        self.assertFalse(summary["by_direction"]["中性"]["hit_rate"])  # 3 天漲 3% 不在 ±3% 內

    def test_missing_price(self):
        db.save_prediction(DATES[0], "9999", "不存在", {"direction": "偏多"})
        self.assertEqual("no_data", pv.build_views()[0]["status"])


if __name__ == "__main__":
    unittest.main()
