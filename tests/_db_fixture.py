"""測試共用：每個測試用獨立的暫存 SQLite，不會碰到真實的 data/tw_stock.db。"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage import db


class TempDBTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="twstock-test-")
        self._db_patch = patch.object(db, "DB_PATH", Path(self._tmpdir) / "test.db")
        self._db_patch.start()
        db.init_db()

    def tearDown(self):
        self._db_patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)


def price_row(date, code="2330", name="台積電", close=100.0, volume=10_000_000, market="TWSE"):
    return {"date": date, "market": market, "code": code, "name": name, "open": close,
            "high": close, "low": close, "close": close, "change": 0.0,
            "volume": volume, "turnover": int(close * volume)}


def inst_row(date, code="2330", foreign=0, trust=0, dealer=0, market="TWSE"):
    return {"date": date, "market": market, "code": code, "name": "",
            "foreign_net": foreign, "trust_net": trust, "dealer_net": dealer,
            "total_net": foreign + trust + dealer}


def margin_row(date, code="2330", margin_balance=1000, short_balance=10, market="TWSE"):
    return {"date": date, "market": market, "code": code, "name": "",
            "margin_balance": margin_balance, "margin_buy": 0, "margin_sell": 0,
            "short_balance": short_balance, "short_sell": 0, "short_cover": 0}
