from src.storage import db
from tests._db_fixture import TempDBTestCase, margin_row


class MarginTotalsTest(TempDBTestCase):
    def test_sums_listed_stocks_only(self):
        db.save_margin([
            margin_row("2026-09-15", "2330", margin_balance=1000, short_balance=10),
            margin_row("2026-09-15", "2317", margin_balance=500, short_balance=5),
            margin_row("2026-09-15", "0050", margin_balance=9999, short_balance=99),          # ETF 不算
            margin_row("2026-09-15", "6488", margin_balance=700, short_balance=7, market="TPEx"),  # 上櫃不算
            margin_row("2026-09-16", "2330", margin_balance=1100, short_balance=12),
        ])
        rows = db.query_margin_totals("2026-09-01", "2026-09-30")
        self.assertEqual([("2026-09-15", 1500, 15, 2), ("2026-09-16", 1100, 12, 1)],
                         [(r["date"], r["margin_balance"], r["short_balance"], r["stocks"]) for r in rows])
        self.assertEqual(1, len(db.query_margin_totals("2026-09-01", "2026-09-15")))
