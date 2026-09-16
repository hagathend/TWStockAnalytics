import importlib.machinery
import socket
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src import config, config_app, desktop

_LAUNCHER = importlib.machinery.SourceFileLoader(
    "launcher", str(config.BASE_DIR / "launcher.pyw")).load_module()


class DataDirTests(unittest.TestCase):
    def test_dev_checkout_uses_project_data(self):
        with patch.object(config, "IS_INSTALLED", False), patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TWSTOCK_DATA_DIR", None)
            self.assertEqual(config._resolve_data_dir(), config.BASE_DIR / "data")

    def test_installed_uses_localappdata(self):
        with patch.object(config, "IS_INSTALLED", True), \
                patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}) as env:
            env.pop("TWSTOCK_DATA_DIR", None)
            self.assertEqual(config._resolve_data_dir(),
                             Path(r"C:\Users\x\AppData\Local") / "TWStockAnalytics" / "data")

    def test_env_override_wins(self):
        with patch.object(config, "IS_INSTALLED", True), patch.dict("os.environ", {"TWSTOCK_DATA_DIR": r"D:\x"}):
            self.assertEqual(config._resolve_data_dir(), Path(r"D:\x"))

    def test_repo_is_not_marked_installed(self):
        # .installed 只能由打包流程產生；開發資料夾誤放會讓資料位置跑掉
        self.assertFalse((config.BASE_DIR / ".installed").exists())


class ScheduleScriptTests(unittest.TestCase):
    def test_register_script(self):
        script = desktop.build_register_task_script("20:00")
        self.assertIn("-StartWhenAvailable", script)
        self.assertIn("-Daily -At '20:00'", script)
        self.assertIn("run_daily_collect.py", script)
        self.assertIn(f"-TaskName '{desktop.TASK_NAME}'", script)

    def test_quotes_paths_with_apostrophes(self):
        self.assertEqual(desktop._ps_quote("C:\\Users\\O'Neil"), "'C:\\Users\\O''Neil'")

    def test_expected_trading_days_counts_weekdays(self):
        # 2026-09-07（一）往前 7 天：08-31（一）～09-06（日）→ 5 個平日
        self.assertEqual(desktop.expected_trading_days(7, today=date(2026, 9, 7)), 5)


class LauncherTests(unittest.TestCase):
    def test_choose_port_skips_occupied(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            busy = sock.getsockname()[1]
            self.assertNotEqual(_LAUNCHER.choose_port(busy, attempts=5), busy)

    def test_running_port_ignores_stale_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "server.json"
            state.write_text('{"port": 1, "pid": 1}', encoding="utf-8")
            with patch.object(_LAUNCHER, "STATE_FILE", state):
                self.assertIsNone(_LAUNCHER.running_port())
            state.write_text("broken", encoding="utf-8")
            with patch.object(_LAUNCHER, "STATE_FILE", state):
                self.assertIsNone(_LAUNCHER.running_port())


class AppSettingsTests(unittest.TestCase):
    def test_defaults_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config_app, "_PATH", Path(tmp) / "a.json"):
            self.assertIsNone(config_app.load_app_settings()["onboarding_done"])
            config_app.save_app_settings({"disclaimer_accepted": True})
            config_app.save_app_settings({"onboarding_done": True})
            settings = config_app.load_app_settings()
            self.assertTrue(settings["disclaimer_accepted"])
            self.assertTrue(settings["onboarding_done"])


if __name__ == "__main__":
    unittest.main()
