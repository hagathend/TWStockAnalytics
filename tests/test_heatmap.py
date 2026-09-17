import unittest

from _db_fixture import TempDBTestCase, price_row
from src import heatmap
from src.storage import db


def _rev(code, industry, ym="2026-08", market="TWSE"):
    return {"year_month": ym, "market": market, "code": code, "name": code, "industry": industry,
            "revenue": 1, "revenue_last_month": None, "revenue_last_year": None, "mom_pct": None,
            "yoy_pct": None, "cum_revenue": None, "cum_revenue_last_year": None, "cum_yoy_pct": None}


def _price(code, close, change, turnover, market="TWSE"):
    row = price_row("2026-09-16", code=code, name=f"S{code}", close=close, market=market)
    row["change"], row["turnover"] = change, turnover
    return row


class HeatmapTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_month_revenue([
            _rev("2330", "半導體業", "2026-07"), _rev("2330", "半導體業"), _rev("2303", "半導體業"),
            _rev("2881", "金融保險業"), _rev("5880", "金融業", market="TPEx"),
        ])
        db.save_stock_price([
            _price("2330", 110.0, 10.0, 3000),   # +10%
            _price("2303", 49.0, -1.0, 1000),    # -2%
            _price("2881", 50.0, 0.0, 500),      # 0%
            _price("1234", 20.0, 1.0, 200),      # 沒有產業別
            _price("0050", 150.0, 3.0, 9999),    # ETF 排除
            _price("2317", 100.0, 1.0, 0),       # 沒成交排除
            _price("5880", 30.0, 0.3, 100, market="TPEx"),
        ])

    def test_frame_filters_and_classifies(self):
        df = heatmap.industry_frame("2026-09-16", ("TWSE",)).set_index("code")
        self.assertEqual(sorted(df.index), ["1234", "2303", "2330", "2881"])
        self.assertAlmostEqual(df.loc["2330", "change_pct"], 10.0)
        self.assertEqual(df.loc["1234", "industry"], heatmap.UNCLASSIFIED)

    def test_summary_weighted_change_and_share(self):
        df = heatmap.industry_frame("2026-09-16", ("TWSE",))
        summary = heatmap.industry_summary(df).set_index("industry")
        semi = summary.loc["半導體業"]
        self.assertAlmostEqual(semi["avg_change"], 4.0)                        # (10 - 2) / 2
        self.assertAlmostEqual(semi["weighted_change"], (10 * 3000 - 2 * 1000) / 4000)
        self.assertAlmostEqual(semi["up_ratio"], 50.0)
        self.assertAlmostEqual(semi["turnover_share"], 4000 / 4700 * 100)
        self.assertEqual(heatmap.industry_summary(df).iloc[0]["industry"], "半導體業")  # 依加權漲跌排序

    def test_financial_aliases_merge_across_markets(self):
        df = heatmap.industry_frame("2026-09-16", ("TWSE", "TPEx"))
        self.assertEqual(set(df[df["code"].isin(["2881", "5880"])]["industry"]), {"金融保險業"})

    def test_treemap_parent_values_sum_children(self):
        df = heatmap.industry_frame("2026-09-16", ("TWSE",))
        fig = heatmap.build_treemap(df, heatmap.industry_summary(df))
        trace = fig.data[0]
        values = dict(zip(trace.ids, trace.values))
        self.assertEqual(values["ind:半導體業"], values["stk:2330"] + values["stk:2303"])
        colors = dict(zip(trace.ids, trace.marker.colors))
        self.assertEqual(colors["stk:2330"], heatmap.COLOR_CAP_PCT)  # +10% 飽和在 7%

    def test_empty_day(self):
        self.assertTrue(heatmap.industry_frame("2000-01-01").empty)
        self.assertTrue(heatmap.industry_summary(heatmap.industry_frame("2000-01-01")).empty)


if __name__ == "__main__":
    unittest.main()
