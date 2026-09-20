import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config_screener as cs


class PresetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(cs, "_PATH", Path(self._tmp.name) / "screener_presets.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_save_load_overwrite_delete(self):
        self.assertEqual({}, cs.load_presets())
        cs.save_preset(" 高殖利率 ", {"scr_yield_min": 5.0, "scr_signals": ["突破20日新高"]})
        self.assertEqual({"高殖利率": {"scr_yield_min": 5.0, "scr_signals": ["突破20日新高"]}}, cs.load_presets())
        cs.save_preset("高殖利率", {"scr_yield_min": 6.0})
        self.assertEqual({"scr_yield_min": 6.0}, cs.load_presets()["高殖利率"])
        cs.delete_preset("高殖利率")
        self.assertEqual({}, cs.load_presets())
        cs.delete_preset("不存在")  # 不會出錯

    def test_blank_name_rejected(self):
        with self.assertRaises(cs.PresetError):
            cs.save_preset("  ", {})

    def test_corrupted_file_is_empty(self):
        cs._PATH.write_text("not json", encoding="utf-8")
        self.assertEqual({}, cs.load_presets())


if __name__ == "__main__":
    unittest.main()
