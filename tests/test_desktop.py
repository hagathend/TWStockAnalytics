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


class PidAliveTests(unittest.TestCase):
    """tasklist 輸出系統編碼（繁中 Windows 是 Big5），曾因 UTF-8 解碼失敗讓 stdout 變成 None 而 TypeError"""

    def _run(self, stdout):
        from unittest.mock import MagicMock, patch
        from src import desktop

        with patch.object(desktop.os, "name", "nt"),                 patch.object(desktop.subprocess, "run", return_value=MagicMock(stdout=stdout)):
            return desktop._pid_alive(1234)

    def test_big5_no_match_output(self):
        self.assertFalse(self._run("資訊: 沒有執行中的工作符合指定的準則。".encode("cp950")))

    def test_running_process(self):
        self.assertTrue(self._run('"python.exe","1234","Console","1","50,000 K"'.encode("cp950")))

    def test_none_stdout_or_failure(self):
        from unittest.mock import patch
        from src import desktop

        self.assertFalse(self._run(None))
        with patch.object(desktop.os, "name", "nt"), patch.object(desktop.subprocess, "run", side_effect=OSError("x")):
            self.assertFalse(desktop._pid_alive(1234))

    def test_backfill_status_with_stale_pid(self):
        import json
        import tempfile
        from pathlib import Path as _Path
        from unittest.mock import patch
        from src import desktop

        with tempfile.TemporaryDirectory() as tmp:
            state = _Path(tmp) / "backfill_job.json"
            state.write_text(json.dumps({"pid": 999999, "started_at": "x"}), encoding="utf-8")
            with patch.object(desktop, "_BACKFILL_STATE", state):
                self.assertFalse(desktop.backfill_status()["running"])


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


class DailyTaskStatusTests(unittest.TestCase):
    def test_parses_status_lines(self):
        output = "20:30\n2026-09-21 20:30\n0\n2026-09-22 20:30"
        with patch.object(desktop, "_run_powershell", return_value=(True, output)):
            status = desktop.daily_task_status()
        self.assertEqual(status, {"exists": True, "time": "20:30", "last_run": "2026-09-21 20:30",
                                  "last_result": "0", "next_run": "2026-09-22 20:30"})

    def test_missing_task(self):
        with patch.object(desktop, "_run_powershell", return_value=(True, "")):
            self.assertFalse(desktop.daily_task_status()["exists"])

    def test_never_run_task(self):
        with patch.object(desktop, "_run_powershell", return_value=(True, "20:30\n-\n267011\n-")):
            status = desktop.daily_task_status()
        self.assertTrue(status["exists"])
        self.assertIsNone(status["last_run"])
        self.assertIsNone(status["next_run"])


class EnsureDailyTaskTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(config_app, "_PATH", Path(self._tmp.name) / "app_settings.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_restores_missing_task(self):
        config_app.save_app_settings({"daily_task_enabled": True, "daily_task_time": "21:00"})
        with patch.object(desktop, "register_daily_task", return_value=(True, "已設定")) as register:
            outcome = desktop.ensure_daily_task({"exists": False, "time": None})
        register.assert_called_once_with("21:00")
        self.assertEqual(outcome, (True, "已設定"))

    def test_does_nothing_when_task_exists_or_disabled(self):
        config_app.save_app_settings({"daily_task_enabled": True, "daily_task_time": "21:00"})
        with patch.object(desktop, "register_daily_task") as register:
            self.assertIsNone(desktop.ensure_daily_task({"exists": True, "time": "21:00"}))
            config_app.save_app_settings({"daily_task_enabled": False})
            self.assertIsNone(desktop.ensure_daily_task({"exists": False, "time": None}))
        register.assert_not_called()
