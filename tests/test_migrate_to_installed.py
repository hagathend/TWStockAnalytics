import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "migrate_to_installed", Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_installed.py")
migrate_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate_mod)


def _make_db(path: Path, rows: int):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, code TEXT)")
    conn.executemany("INSERT INTO holdings (code) VALUES (?)", [(str(i),) for i in range(rows)])
    conn.commit()
    conn.close()


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.source, self.target = root / "dev" / "data", root / "installed" / "data"
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        _make_db(self.source / "tw_stock.db", 5)
        (self.source / "watchlist.json").write_text('{"2330": "台積電"}', encoding="utf-8")
        (self.source / "server.json").write_text('{"port": 1}', encoding="utf-8")
        (self.source / "ai_settings.json").write_text('{"keys": {}}', encoding="utf-8")
        # 安裝版試裝後的狀態：空資料庫 + 引導已完成
        _make_db(self.target / "tw_stock.db", 0)
        (self.target / "app_settings.json").write_text('{"onboarding_done": true}', encoding="utf-8")
        (self.target / "tw_stock.db-wal").write_bytes(b"stale")

    def tearDown(self):
        self._tmp.cleanup()

    def test_copies_data_backs_up_target_and_keeps_installed_settings(self):
        result = migrate_mod.migrate(self.source, self.target, now=datetime(2026, 9, 16, 22, 0, 0))

        self.assertEqual(result["counts"]["holdings"], 5)
        self.assertEqual(json.loads((self.target / "watchlist.json").read_text(encoding="utf-8")), {"2330": "台積電"})
        self.assertFalse((self.target / "server.json").exists())      # 執行期狀態檔不搬
        self.assertFalse((self.target / "ai_settings.json").exists())  # 已停用的舊設定不搬
        self.assertFalse((self.target / "tw_stock.db-wal").exists())   # 舊 WAL 不可留著
        self.assertTrue((self.target / "app_settings.json").exists())  # 安裝版自己的設定保留

        backup = result["backup"]
        self.assertEqual(backup.name, "data_backup_20260916_220000")
        self.assertEqual(migrate_mod.table_counts(backup / "tw_stock.db")["holdings"], 0)

    def test_source_db_left_untouched(self):
        migrate_mod.migrate(self.source, self.target)
        self.assertEqual(migrate_mod.table_counts(self.source / "tw_stock.db")["holdings"], 5)

    def test_refuses_while_installed_app_running(self):
        with patch.object(migrate_mod, "installed_app_running", return_value=True):
            with self.assertRaises(RuntimeError):
                migrate_mod.migrate(self.source, self.target)
        self.assertEqual(migrate_mod.table_counts(self.target / "tw_stock.db")["holdings"], 0)

    def test_missing_source_db(self):
        (self.source / "tw_stock.db").unlink()
        with self.assertRaises(FileNotFoundError):
            migrate_mod.migrate(self.source, self.target)

    def test_same_folder_rejected(self):
        with self.assertRaises(ValueError):
            migrate_mod.migrate(self.source, self.source)


if __name__ == "__main__":
    unittest.main()
