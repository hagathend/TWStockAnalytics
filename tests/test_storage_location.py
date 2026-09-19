import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import config, storage_location
from src.storage import db


class StorageLocationTest(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="twstock-storage-"))
        self.default_dir = Path(self._tmpdir)
        self._patches = [
            patch.object(config, "DEFAULT_DB_DIR", self.default_dir),
            patch.object(config, "DB_FILE_NAME", "test.db"),
            patch.object(config, "STORAGE_SETTINGS_PATH", self.default_dir / "storage_settings.json"),
        ]
        for p in self._patches:
            p.start()
        db.save_stock_price([price_row("2026-09-16"), price_row("2026-09-17", close=101.0)])

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        super().tearDown()

    def test_usage_and_table_sizes(self):
        info = storage_location.usage()
        self.assertTrue(info["is_default"])
        self.assertGreater(info["size"], 0)
        sizes = {r["table"]: r for r in storage_location.table_sizes()}
        self.assertEqual(sizes["stock_price"]["rows"], 2)
        self.assertGreater(sizes["stock_price"]["bytes"], 0)

    def test_move_keep_old_then_back_is_refused(self):
        old = db.DB_PATH
        ok, message = storage_location.move_database(str(self.root / "new"))
        self.assertTrue(ok, message)
        self.assertEqual(Path(db.DB_PATH), self.root / "new" / "test.db")
        self.assertEqual(len(db.query_stock_price("2026-09-17")), 1)  # 新位置可以直接讀寫
        self.assertTrue(Path(old).exists())                            # 原檔保留
        setting = json.loads(config.STORAGE_SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(setting["db_dir"], str(self.root / "new"))
        self.assertFalse(storage_location.is_default())
        ok, message = storage_location.move_database(str(self.default_dir))  # 原位置還有檔案，不覆蓋
        self.assertFalse(ok)
        self.assertIn("已經有", message)

    def test_move_delete_old_and_back_to_default_clears_setting(self):
        old = Path(db.DB_PATH)
        ok, _ = storage_location.move_database(str(self.root / "a"), delete_old=True)
        self.assertTrue(ok)
        self.assertFalse(old.exists())
        ok, _ = storage_location.move_database(str(self.default_dir), delete_old=True)
        self.assertTrue(ok)
        self.assertFalse(config.STORAGE_SETTINGS_PATH.exists())  # 回到預設就不需要設定檔
        self.assertEqual(len(db.query_stock_price("2026-09-16")), 1)

    def test_invalid_targets(self):
        self.assertFalse(storage_location.move_database("")[0])
        self.assertFalse(storage_location.move_database("relative\\path")[0])
        self.assertIn("已經在", storage_location.move_database(str(self.default_dir))[1])
        with patch.object(storage_location.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 1)):
            ok, message = storage_location.move_database(str(self.root / "small"))
        self.assertFalse(ok)
        self.assertIn("空間不足", message)

    def test_failed_copy_leaves_original(self):
        old = db.DB_PATH
        with patch.object(storage_location.sqlite3, "connect", side_effect=sqlite3.OperationalError("disk I/O")):
            ok, message = storage_location.move_database(str(self.root / "x"))
        self.assertFalse(ok)
        self.assertIn("原本的資料庫沒有變動", message)
        self.assertEqual(db.DB_PATH, old)
        self.assertFalse((self.root / "x" / "test.db").exists())

    def test_vacuum_and_format(self):
        ok, message = storage_location.vacuum()
        self.assertTrue(ok, message)
        self.assertEqual(storage_location.format_bytes(512), "512 B")
        self.assertEqual(storage_location.format_bytes(242343936), "231.1 MB")


class ResolveDbPathTest(unittest.TestCase):
    def test_missing_custom_location_falls_back_with_error(self):
        tmp = Path(tempfile.mkdtemp(prefix="twstock-resolve-"))
        try:
            settings = tmp / "storage_settings.json"
            settings.write_text(json.dumps({"db_dir": str(tmp / "unplugged")}), encoding="utf-8")
            with patch.object(config, "STORAGE_SETTINGS_PATH", settings), patch.object(config, "DEFAULT_DB_DIR", tmp):
                path = config._resolve_db_path()
                self.assertEqual(path, tmp / config.DB_FILE_NAME)
                self.assertIn("找不到資料庫", config.DB_LOCATION_ERROR)
                (tmp / "unplugged").mkdir()
                (tmp / "unplugged" / config.DB_FILE_NAME).write_bytes(b"")
                self.assertEqual(config._resolve_db_path(), tmp / "unplugged" / config.DB_FILE_NAME)
        finally:
            config.DB_LOCATION_ERROR = None
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
