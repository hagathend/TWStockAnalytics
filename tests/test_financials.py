import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from _db_fixture import TempDBTestCase
from src import financials, fundamentals
from src.collectors import mops_financials
from src.storage import db

INCOME_HTML = """<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th><th>營業毛利（毛損）</th>
<th>營業毛利（毛損）淨額</th><th>營業利益（損失）</th><th>淨利（淨損）歸屬於母公司業主</th><th>基本每股盈餘（元）</th></tr>
<tr><td>2330</td><td>台積電</td><td>1,134,103,440</td><td>751,295,421</td><td>751,295,421</td><td>658,966,142</td>
<td>572,479,752</td><td>22.08</td></tr></table>
<table><tr><th>公司代號</th><th>公司名稱</th><th>利息淨收益</th><th>淨利（損）歸屬於母公司業主</th><th>基本每股盈餘</th></tr>
<tr><td>2881</td><td>富邦金</td><td>1</td><td>97,391,130</td><td>6.67</td></tr></table>
<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th><th>營業毛利（毛損）淨額</th><th>營業利益（損失）</th>
<th>淨利（淨損）歸屬於母公司業主</th><th>基本每股盈餘（元）</th></tr>
<tr><td>1234</td><td>停業</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td></tr></table>"""
BALANCE_HTML = """<table><tr><th>公司代號</th><th>公司名稱</th><th>流動資產</th><th>資產總計</th><th>流動負債</th><th>負債總計</th>
<th>歸屬於母公司業主之權益合計</th><th>權益總計</th>
<th>母公司暨子公司所持有之母公司庫藏股股數（單位：股）</th></tr>
<tr><td>2330</td><td>台積電</td><td>3,000</td><td>8,000</td><td>1,500</td><td>2,100</td><td>5,890,960,252</td><td>5,932,388,921</td><td>0</td></tr></table>"""
CASHFLOW_HTML = """<table><tr><th>公司代號</th><th>公司名稱</th><th>營業活動之淨現金流入（流出）</th><th>投資活動之淨現金流入（流出）</th>
<th>籌資活動之淨現金流入（流出）</th><th>期末現金及約當現金餘額</th></tr>
<tr><td>2330</td><td>台積電</td><td>900</td><td>-600</td><td>-100</td><td>5,000</td></tr></table>"""


class ParseTests(unittest.TestCase):
    def test_income_variants(self):
        rows = {r["code"]: r for r in map(mops_financials.normalize_income, mops_financials.parse_tables(INCOME_HTML))}
        self.assertEqual(rows["2330"]["eps"], 22.08)
        self.assertEqual(rows["2330"]["gross_profit"], 751295421)
        self.assertEqual(rows["2881"]["net_income"], 97391130)  # 「淨利（損）」寫法
        self.assertEqual(rows["2881"]["eps"], 6.67)             # 「基本每股盈餘」沒有（元）
        self.assertIsNone(rows["2881"]["revenue"])
        self.assertIsNone(rows["1234"]["eps"])                   # "--"

    def test_balance_ignores_treasury_column(self):
        row = mops_financials.normalize_balance(mops_financials.parse_tables(BALANCE_HTML)[0])
        self.assertEqual(row["equity"], 5890960252)
        self.assertEqual((row["total_assets"], row["total_liabilities"]), (8000, 2100))
        self.assertEqual((row["current_assets"], row["current_liabilities"]), (3000, 1500))

    def test_fetch_quarter_merges_equity(self):
        pages = {"t163sb04": INCOME_HTML, "t163sb05": BALANCE_HTML, "t163sb20": CASHFLOW_HTML}
        with patch.object(mops_financials, "_post", side_effect=lambda report, *a: pages[report]):
            rows = {r["code"]: r for r in mops_financials.fetch_quarter(2026, 1, "TWSE")}
        self.assertEqual(rows["2330"]["equity"], 5890960252)
        self.assertIsNone(rows["2881"]["equity"])
        self.assertEqual((rows["2330"]["operating_cf"], rows["2330"]["investing_cf"]), (900, -600))
        self.assertIsNone(rows["2881"]["operating_cf"])
        self.assertEqual((rows["2330"]["year"], rows["2330"]["quarter"]), (2026, 1))


def _q(year, quarter, revenue, gross, operating, net, eps, equity=1000.0, code="2330"):
    return {"year": year, "quarter": quarter, "market": "TWSE", "code": code, "name": "台積電", "revenue": revenue,
            "gross_profit": gross, "operating_income": operating, "net_income": net, "eps": eps, "equity": equity}


class QuarterlyFrameTests(unittest.TestCase):
    def test_single_quarter_values_margins_roe_ttm(self):
        rows = [
            _q(2025, 3, 300, 150, 90, 60, 3.0),
            _q(2025, 4, 400, 200, 120, 80, 4.0),
            _q(2026, 1, 100, 60, 40, 30, 1.5),
            _q(2026, 2, 250, 140, 90, 70, 3.5),   # 累計值；單季＝營收 150、毛利 80、營益 50、EPS 2.0
        ]
        frame = financials.quarterly_frame(rows).set_index("label")
        q2 = frame.loc["2026Q2"]
        self.assertAlmostEqual(q2["revenue_q"], 150)
        self.assertAlmostEqual(q2["eps_q"], 2.0)
        self.assertAlmostEqual(q2["gross_margin"], 80 / 150 * 100)
        self.assertAlmostEqual(q2["operating_margin"], 50 / 150 * 100)
        self.assertAlmostEqual(q2["roe_annualized"], 70 / 1000 * 2 * 100)
        # 2025Q3 單季要靠 2025Q2 累計，沒有 → None；所以近四季 EPS 需要的四個單季不齊
        self.assertTrue(frame["eps_ttm"].isna().all())
        self.assertAlmostEqual(frame.loc["2025Q4", "eps_q"], 1.0)

    def test_ttm_with_complete_quarters(self):
        rows = [_q(2025, q, 100 * q, 50 * q, 30 * q, 20 * q, 1.0 * q) for q in (1, 2, 3, 4)] + \
               [_q(2026, 1, 100, 50, 30, 20, 2.0)]
        frame = financials.quarterly_frame(rows)
        self.assertAlmostEqual(frame.iloc[-1]["eps_ttm"], 1 + 1 + 1 + 2)

    def test_gap_breaks_ttm(self):
        rows = [_q(2025, 1, 1, 1, 1, 1, 1.0), _q(2025, 2, 2, 2, 2, 2, 2.0), _q(2025, 3, 3, 3, 3, 3, 3.0),
                _q(2026, 1, 1, 1, 1, 1, 1.0)]
        self.assertTrue(financials.quarterly_frame(rows)["eps_ttm"].isna().all())

    def test_latest_published_quarter(self):
        self.assertEqual(financials.latest_published_quarter(date(2026, 9, 17)), (2026, 2))
        self.assertEqual(financials.latest_published_quarter(date(2026, 3, 20)), (2025, 3))
        self.assertEqual(financials.latest_published_quarter(date(2026, 4, 2)), (2025, 4))
        self.assertEqual(financials.latest_published_quarter(date(2026, 12, 1)), (2026, 3))


class RatioTests(unittest.TestCase):
    def test_balance_sheet_dupont_and_cashflow(self):
        extra = [
            {"total_assets": 4000, "total_liabilities": 1000, "current_assets": 1500, "current_liabilities": 600,
             "operating_cf": 40, "investing_cf": -30, "financing_cf": -5},
            {"total_assets": 5000, "total_liabilities": 1500, "current_assets": 2000, "current_liabilities": 1000,
             "operating_cf": 140, "investing_cf": -50, "financing_cf": -20},
        ]
        rows = [{**_q(2026, 1, 100, 60, 40, 30, 1.5, equity=2500), **extra[0]},
                {**_q(2026, 2, 250, 140, 90, 70, 3.5, equity=2500), **extra[1]}]
        q2 = financials.quarterly_frame(rows).iloc[-1]
        self.assertAlmostEqual(q2["debt_ratio"], 30)
        self.assertAlmostEqual(q2["current_ratio"], 200)
        self.assertAlmostEqual(q2["roa_annualized"], 70 / 5000 * 2 * 100)
        self.assertAlmostEqual(q2["net_income_q"], 40)
        self.assertAlmostEqual(q2["operating_cf_q"], 100)
        self.assertAlmostEqual(q2["free_cf_q"], 100 - 20)
        self.assertAlmostEqual(q2["ocf_to_net_income"], 140 / 70)
        # 杜邦三因子相乘＝累計淨利 ÷ 權益 × 年化
        dupont = q2["net_margin"] / 100 * q2["asset_turnover"] * q2["equity_multiplier"] * 100
        self.assertAlmostEqual(dupont, q2["roe_annualized"])

    def test_old_rows_without_new_columns(self):
        frame = financials.quarterly_frame([_q(2026, 1, 100, 60, 40, 30, 1.5)])
        self.assertTrue(frame["debt_ratio"].isna().all())

    def test_negative_income_no_cash_quality(self):
        row = {**_q(2026, 1, 100, 60, -40, -30, -1.5), "operating_cf": -10}
        self.assertTrue(pd.isna(financials.quarterly_frame([row]).iloc[0]["ocf_to_net_income"]))


class FinancialsDBTests(TempDBTestCase):
    def test_backfill_refresh_latest_and_prompt(self):
        calls = []

        def fake(year, quarter, market):
            calls.append((year, quarter, market))
            return [_q(year, quarter, 100 * quarter, 50 * quarter, 30 * quarter, 20 * quarter, 1.0 * quarter)] if market == "TWSE" else []

        with patch.object(financials.mops_financials, "fetch_quarter", side_effect=fake):
            financials.backfill(2, sleep_seconds=0, today=date(2026, 9, 17))
            self.assertEqual(sorted(set(calls)), [(2026, 1, "TPEx"), (2026, 1, "TWSE"), (2026, 2, "TPEx"), (2026, 2, "TWSE")])
        text = fundamentals.summarize_for_prompt("2330")
        self.assertIn("2026Q2：單季 EPS 1.00 元", text)
        table = financials.latest_table().set_index("code")
        self.assertAlmostEqual(table.loc["2330", "roe_annualized"], 40 / 1000 * 2 * 100)


if __name__ == "__main__":
    unittest.main()
