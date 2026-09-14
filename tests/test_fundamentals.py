import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from _db_fixture import TempDBTestCase
from src import fundamentals
from src.collectors import fundamentals as collector
from src.storage import db

# 欄位格式取自實際 API 回應（2026-09-14）
BWIBBU_PAYLOAD = {
    "stat": "OK",
    "fields": ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "股利年度", "本益比", "股價淨值比", "財報年/季"],
    "data": [
        ["1101", "台泥", "23.90", "3.35", 114, "-", "0.77", "115/2"],
        ["1102", "亞泥", "35.00", "6.57", 114, "9.67", "0.67", "115/2"],
    ],
}
TPEX_PE_PAYLOAD = [{"Date": "1150914", "SecuritiesCompanyCode": "1240", "CompanyName": "茂生農經",
                    "PriceEarningRatio": "10.30", "DividendPerShare": "0.50000000",
                    "YieldRatio": "0.90", "PriceBookRatio": "1.63"}]
REVENUE_ITEM = {
    "出表日期": "1150913", "資料年月": "11508", "公司代號": "1101", "公司名稱": "台泥", "產業別": "水泥工業",
    "營業收入-當月營收": "13515534", "營業收入-上月營收": "13744103", "營業收入-去年當月營收": "12214776",
    "營業收入-上月比較增減(%)": "-1.6630332295967223", "營業收入-去年同月增減(%)": "10.649053245020621",
    "累計營業收入-當月累計營收": "98726969", "累計營業收入-去年累計營收": "96131621",
    "累計營業收入-前期比較增減(%)": "2.699785952844798", "備註": "-",
}


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


class CollectorParsingTests(unittest.TestCase):
    def test_twse_valuation_loss_company_pe_is_none(self):
        with patch.object(collector.requests, "get", return_value=_response(BWIBBU_PAYLOAD)):
            rows = collector.fetch_twse_valuation("20260914")
        self.assertEqual(rows[0]["date"], "2026-09-14")
        self.assertIsNone(rows[0]["pe_ratio"])
        self.assertEqual(rows[1]["pe_ratio"], 9.67)
        self.assertEqual(rows[1]["dividend_yield"], 6.57)
        self.assertEqual(rows[1]["pb_ratio"], 0.67)

    def test_twse_valuation_non_trading_day(self):
        payload = {"stat": "很抱歉，沒有符合條件的資料!"}
        with patch.object(collector.requests, "get", return_value=_response(payload)):
            self.assertEqual(collector.fetch_twse_valuation("20260913"), [])

    def test_tpex_valuation(self):
        session = MagicMock()
        session.get.return_value = _response(TPEX_PE_PAYLOAD)
        with patch.object(collector, "_tpex_session", return_value=session):
            rows = collector.fetch_tpex_valuation()
        self.assertEqual(rows[0]["date"], "2026-09-14")
        self.assertEqual(rows[0]["market"], "TPEx")
        self.assertEqual(rows[0]["pe_ratio"], 10.3)

    def test_month_revenue_parsing_and_invalid_rows_dropped(self):
        bad = dict(REVENUE_ITEM, **{"資料年月": ""})
        with patch.object(collector.requests, "get", return_value=_response([REVENUE_ITEM, bad])):
            rows = collector.fetch_twse_month_revenue()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["year_month"], "2026-08")
        self.assertEqual(row["revenue"], 13515534)
        self.assertAlmostEqual(row["yoy_pct"], 10.649, places=3)
        self.assertAlmostEqual(row["mom_pct"], -1.663, places=3)

    def test_roc_year_month(self):
        self.assertEqual(collector._roc_year_month("11508"), "2026-08")
        self.assertEqual(collector._roc_year_month("11512"), "2026-12")
        self.assertIsNone(collector._roc_year_month("abc"))


def _val(date, code, pe, dy=3.0, pb=1.0, market="TWSE"):
    return {"date": date, "market": market, "code": code, "name": code,
            "pe_ratio": pe, "dividend_yield": dy, "pb_ratio": pb}


def _rev(ym, code, yoy, revenue=1_000_000, market="TWSE"):
    return {"year_month": ym, "market": market, "code": code, "name": code, "industry": "",
            "revenue": revenue, "revenue_last_month": None, "revenue_last_year": None,
            "mom_pct": 1.0, "yoy_pct": yoy, "cum_revenue": None, "cum_revenue_last_year": None,
            "cum_yoy_pct": 5.0}


class FundamentalsDBTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_valuation([_val("2026-09-11", "1101", 20.0), _val("2026-09-14", "1101", 10.0),
                           _val("2026-09-14", "1102", None), _val("2026-09-12", "1240", 8.0, market="TPEx")])
        # 1101 已公布 8 月、1102 只公布到 7 月：逐檔取各自最新月份
        db.save_month_revenue([_rev("2026-07", "1101", 1.0), _rev("2026-08", "1101", 30.0),
                               _rev("2026-07", "1102", -5.0)])

    def test_latest_valuation_per_market_and_as_of(self):
        latest = {r["code"]: r for r in db.query_latest_valuation()}
        self.assertEqual(latest["1101"]["pe_ratio"], 10.0)
        self.assertIn("1240", latest)  # TPEx 日期不同也要取到
        past = {r["code"]: r for r in db.query_latest_valuation("2026-09-11")}
        self.assertEqual(past["1101"]["pe_ratio"], 20.0)

    def test_latest_fundamentals_and_filters(self):
        table = fundamentals.latest_fundamentals()
        by_code = table.set_index("code")
        self.assertEqual(by_code.loc["1101", "year_month"], "2026-08")
        self.assertEqual(by_code.loc["1102", "yoy_pct"], -5.0)

        self.assertEqual(list(fundamentals.apply_filters(table, pe_max=15)["code"].sort_values()), ["1101", "1240"])
        # 1102 虧損無本益比、1240 無營收資料 → 設了條件就不符合
        self.assertEqual(list(fundamentals.apply_filters(table, pe_max=15, yoy_min=10)["code"]), ["1101"])
        self.assertEqual(len(fundamentals.apply_filters(table)), 3)

    def test_attach_keeps_rows_without_fundamentals(self):
        df = pd.DataFrame({"code": ["1101", "9999"]})
        merged = fundamentals.attach_fundamentals(df, fundamentals.latest_fundamentals())
        self.assertEqual(len(merged), 2)
        self.assertTrue(pd.isna(merged.set_index("code").loc["9999", "pe_ratio"]))

    def test_prompt_summary(self):
        text = fundamentals.summarize_for_prompt("1101")
        self.assertIn("本益比 10.00", text)
        self.assertIn("2026-08 營收 1,000 百萬元", text)
        self.assertIn("年增 +30.0%", text)
        self.assertIn("無資料", fundamentals.summarize_for_prompt("1102"))  # 本益比 None
        self.assertIn("本益比／殖利率／淨值比: 無資料", fundamentals.summarize_for_prompt("0000"))

    def test_empty_database(self):
        with patch.object(db, "query_latest_valuation", return_value=[]), \
                patch.object(db, "query_latest_month_revenue", return_value=[]):
            table = fundamentals.latest_fundamentals()
        self.assertTrue(table.empty)
        self.assertIn("pe_ratio", table.columns)


class CollectFundamentalsTests(TempDBTestCase):
    def test_one_source_failure_does_not_stop_others(self):
        from src import collect_all
        with patch.object(collect_all.fundamentals, "fetch_twse_valuation", side_effect=RuntimeError("x")), \
                patch.object(collect_all.fundamentals, "fetch_tpex_valuation", return_value=[_val("2026-09-14", "1240", 8.0, market="TPEx")]), \
                patch.object(collect_all.fundamentals, "fetch_twse_month_revenue", return_value=[_rev("2026-08", "1101", 3.0)]), \
                patch.object(collect_all.fundamentals, "fetch_tpex_month_revenue", return_value=[]):
            result = collect_all.collect_fundamentals()
        self.assertEqual(result, {"valuation": 1, "month_revenue": 1})
        self.assertEqual(len(db.query_latest_month_revenue()), 1)


if __name__ == "__main__":
    unittest.main()
