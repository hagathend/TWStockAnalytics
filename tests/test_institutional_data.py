import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from _db_fixture import TempDBTestCase, inst_row
from src.collectors import twse_official
from src.storage import db

# 欄位名稱照抄 TPEx tpex_3insti_daily_trading 實際回應（2026-09-16），含不一致的空白與大小寫
TPEX_ITEM = {
    "Date": "1150916",
    "SecuritiesCompanyCode": "6147",
    "CompanyName": "頎邦",
    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy": "1000",
    " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell": "5732049",
    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "-5731049",
    "Foreign Dealers-Total Buy": "0",
    "Foreign Dealers-TotalSell": "0",
    "ForeignDealers-Difference": "0",
    "ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy": "1000",
    "ForeignInvestorsIncludeMainlandAreaInvestors-TotalSell": "5732049",
    "ForeignInvestorsInclude MainlandAreaInvestors-Difference": "-5731049",
    "SecuritiesInvestmentTrustCompanies-TotalBuy": "2433100",
    "SecuritiesInvestmentTrustCompanies-TotalSell": "0",
    "SecuritiesInvestmentTrustCompanies-Difference": "2433100",
    "Dealers-TotalBuy": "600000",
    "Dealers-TotalSell": "71610",
    "Dealers-Difference": "528390",
    "Dealers -TotalSell": "71610",
    "TotalDifference": "-2769559",
}


class TpexInstitutionalParsingTests(unittest.TestCase):
    def test_dealer_is_not_confused_with_foreign_column(self):
        session = MagicMock()
        session.get.return_value.json.return_value = [TPEX_ITEM]
        with patch.object(twse_official, "_tpex_session", return_value=session):
            row = twse_official.fetch_tpex_institutional()[0]
        self.assertEqual(row["foreign_net"], -5731049)
        self.assertEqual(row["trust_net"], 2433100)
        self.assertEqual(row["dealer_net"], 528390)
        self.assertEqual(row["total_net"], -2769559)
        self.assertEqual(row["foreign_net"] + row["trust_net"] + row["dealer_net"], row["total_net"])

    def test_find_value_requires_exact_field(self):
        self.assertEqual(twse_official._find_value(TPEX_ITEM, "Dealers-Difference"), "528390")
        self.assertIsNone(twse_official._find_value(TPEX_ITEM, "Difference"))


class StockCodeTests(unittest.TestCase):
    def test_stock_codes(self):
        for code in ("2330", "2881A", "910322"):
            self.assertTrue(db.is_stock_code(code), code)
        for code in ("062330", "03006T", "020000", "0050", "00631L", "00406A", "700123", "", None):
            self.assertFalse(db.is_stock_code(code), code)

    def test_python_and_sql_rules_agree(self):
        codes = ["2330", "2881A", "910322", "062330", "03006T", "020000", "0050", "00631L", "00406A", "700123",
                 "2330a", "91032", "9103222", "0056", "00400A"]
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (code TEXT)")
        conn.executemany("INSERT INTO t VALUES (?)", [(c,) for c in codes])
        sql_kept = {r[0] for r in conn.execute(f"SELECT code FROM t WHERE {db.STOCK_CODE_SQL}")}
        conn.close()
        self.assertEqual(sql_kept, {c for c in codes if db.is_stock_code(c)})


class InstitutionalQueryTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        d = "2026-09-16"
        db.save_institutional([
            inst_row(d, code="2330", foreign=-8_000_000, trust=100_000, dealer=700_000),
            inst_row(d, code="062330", foreign=0, trust=0, dealer=-141_000),       # 權證
            inst_row(d, code="082330", foreign=-1000, trust=0, dealer=-900_000_000),  # 權證，避險量極大
            inst_row(d, code="00406A", foreign=0, trust=0, dealer=-150_000_000),   # ETF 造市
            inst_row(d, code="6147", foreign=-5_731_049, trust=2_433_100, dealer=528_390, market="TPEx"),
        ])

    def test_exact_code_lookup_ignores_warrants(self):
        row = db.query_institutional_for_code("2026-09-16", "2330")
        self.assertEqual(row["foreign_net"], -8_000_000)
        self.assertIsNone(db.query_institutional_for_code("2026-09-16", "9999"))
        # 模糊搜尋仍會帶出權證，這就是報告不能用它取第一筆的原因
        self.assertEqual(len(db.query_institutional("2026-09-16", "2330")), 3)

    def test_market_summary_counts_stocks_only(self):
        summary = db.query_market_institutional_summary("2026-09-16")
        self.assertEqual(summary["foreign_total"], -8_000_000 - 5_731_049)
        self.assertEqual(summary["dealer_total"], 700_000 + 528_390)

    def test_init_db_repairs_old_tpex_dealer_column(self):
        with db.get_conn() as conn:
            # 舊版解析錯誤：自營商欄位存成外資的數字
            conn.execute("UPDATE institutional SET dealer_net = foreign_net WHERE code = '6147'")
        db.init_db()
        row = db.query_institutional_for_code("2026-09-16", "6147")
        self.assertEqual(row["dealer_net"], 528_390)
        # 上市資料不受影響
        self.assertEqual(db.query_institutional_for_code("2026-09-16", "2330")["dealer_net"], 700_000)
        db.init_db()  # 再跑一次不會改變已正確的資料
        self.assertEqual(db.query_institutional_for_code("2026-09-16", "6147")["dealer_net"], 528_390)


if __name__ == "__main__":
    unittest.main()
