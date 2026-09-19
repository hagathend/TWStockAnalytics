from src import rankings
from src.storage import db
from tests._db_fixture import TempDBTestCase, inst_row, price_row

DAY = "2026-09-16"


def _price(code, name, close, change, volume, market="TWSE"):
    row = price_row(DAY, code, name, close=close, volume=volume, market=market)
    row["change"] = change
    return row


class RankingsTest(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_stock_price([
            _price("2330", "台積電", 110.0, 10.0, 5_000_000),        # +10%
            _price("2317", "鴻海", 95.0, -5.0, 20_000_000),          # -5%
            _price("6488", "環球晶", 300.0, 3.0, 1_000_000, "TPEx"),  # +1.01%
            _price("0050", "元大台灣50", 100.0, 1.0, 9_000_000),     # ETF 不列入
        ])
        db.save_institutional([inst_row(DAY, "2330", foreign=3_000_000, trust=-500_000),
                               inst_row(DAY, "2317", foreign=-1_000_000, trust=200_000)])
        db.save_foreign_holding([
            {"date": DAY, "code": "2330", "name": "台積電", "issued_shares": 100_000_000, "foreign_shares": 0,
             "foreign_pct": 0, "foreign_limit_pct": 100},
            {"date": DAY, "code": "2317", "name": "鴻海", "issued_shares": 50_000_000, "foreign_shares": 0,
             "foreign_pct": 0, "foreign_limit_pct": 100},
        ])
        db.save_valuation([
            {"date": DAY, "market": "TWSE", "code": "2330", "name": "台積電", "pe_ratio": 20, "dividend_yield": 2.5, "pb_ratio": 5},
            {"date": DAY, "market": "TWSE", "code": "2317", "name": "鴻海", "pe_ratio": 12, "dividend_yield": 95.0, "pb_ratio": 1},
        ])
        self.table = rankings.daily_table(DAY)

    def test_daily_table_columns(self):
        self.assertEqual({"2330", "2317", "6488"}, set(self.table["code"]))  # 不含 ETF
        tsmc = self.table.set_index("code").loc["2330"]
        self.assertAlmostEqual(10.0, tsmc["change_pct"])
        self.assertAlmostEqual(5000, tsmc["volume_lots"])
        self.assertAlmostEqual(5.0, tsmc["turnover_rate"])  # 500 萬股 ÷ 1 億股
        self.assertAlmostEqual(3000, tsmc["foreign_lots"])
        self.assertTrue(self.table.set_index("code").loc[["6488"], "turnover_rate"].isna().all())  # 上櫃沒有發行股數

    def test_rank_directions_and_filters(self):
        self.assertEqual(["2330", "6488"], list(rankings.rank(self.table, "漲幅")["code"]))
        self.assertEqual(["2317"], list(rankings.rank(self.table, "跌幅")["code"]))
        self.assertEqual(["2317", "2330", "6488"], list(rankings.rank(self.table, "成交量")["code"]))
        self.assertEqual(["2330"], list(rankings.rank(self.table, "外資買超")["code"]))
        self.assertEqual(["2317"], list(rankings.rank(self.table, "外資賣超")["code"]))
        self.assertEqual(["2317", "2330"], list(rankings.rank(self.table, "週轉率")["code"]))  # 40% vs 5%
        self.assertEqual(["2330"], list(rankings.rank(self.table, "殖利率")["code"]))  # 95% 視為異常值排除
        self.assertEqual(["6488"], list(rankings.rank(self.table, "漲幅", "上櫃")["code"]))
        self.assertEqual(1, len(rankings.rank(self.table, "成交量", limit=1)))

    def test_empty_day(self):
        self.assertTrue(rankings.daily_table("2026-01-01").empty)
