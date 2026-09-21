import hashlib
import io
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import config_app, updater

INSTALLER = b"fake installer bytes" * 100

RELEASE_PAYLOAD = {
    "tag_name": "v0.0.9",
    "html_url": "https://github.com/hagathend/TWStockAnalytics/releases/tag/v0.0.9",
    "body": "更新內容",
    "assets": [
        {"name": "source.zip", "browser_download_url": "https://example.invalid/source.zip"},
        {"name": "TWStockAnalytics-Setup-0.0.9.exe", "size": len(INSTALLER),
         "browser_download_url": "https://example.invalid/setup.exe",
         "digest": "sha256:" + hashlib.sha256(INSTALLER).hexdigest()},
    ],
}


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.is_newer("v0.0.10", "0.0.9"))  # 數字比較，不是字串比較
        self.assertTrue(updater.is_newer("0.1", "0.0.9"))
        self.assertFalse(updater.is_newer("v0.0.3", "0.0.3"))
        self.assertFalse(updater.is_newer("0.0.2", "0.0.3"))
        self.assertFalse(updater.is_newer("0.0.3.0", "0.0.3"))


class ReleaseParsingTests(unittest.TestCase):
    def test_picks_installer_asset(self):
        release = updater.summarize_release(RELEASE_PAYLOAD)
        self.assertEqual(release["version"], "0.0.9")
        self.assertEqual(release["asset_name"], "TWStockAnalytics-Setup-0.0.9.exe")
        self.assertEqual(release["sha256"], hashlib.sha256(INSTALLER).hexdigest())

    def test_release_without_installer_is_ignored(self):
        self.assertIsNone(updater.summarize_release({**RELEASE_PAYLOAD, "assets": RELEASE_PAYLOAD["assets"][:1]}))


class CheckForUpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(config_app, "_PATH", Path(self._tmp.name) / "app_settings.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_caches_for_a_day_and_reports_newer(self):
        release = updater.summarize_release(RELEASE_PAYLOAD)
        now = datetime(2026, 9, 16, 12, 0)
        with patch.object(updater, "_fetch_latest", return_value=release) as fetch, \
                patch.object(updater, "__version__", "0.0.3"):
            self.assertEqual(updater.check_for_update(now=now)["version"], "0.0.9")
            updater.check_for_update(now=now + timedelta(hours=5))
            self.assertEqual(fetch.call_count, 1)
            updater.check_for_update(now=now + timedelta(hours=25))
            self.assertEqual(fetch.call_count, 2)

    def test_same_version_is_not_an_update(self):
        release = updater.summarize_release(RELEASE_PAYLOAD)
        with patch.object(updater, "_fetch_latest", return_value=release), patch.object(updater, "__version__", "0.0.9"):
            self.assertIsNone(updater.check_for_update(force=True))

    def test_install_rechecks_for_newer_release(self):
        cached = updater.summarize_release(RELEASE_PAYLOAD)  # 一天前查到的 0.0.9
        newer = {**cached, "version": "0.1.0", "asset_name": "TWStockAnalytics-Setup-0.1.0.exe"}
        with patch.object(updater, "_fetch_latest", return_value=newer):
            self.assertEqual(updater.release_to_install(cached)["version"], "0.1.0")
        self.assertEqual(config_app.load_app_settings()["latest_release"]["version"], "0.1.0")
        with patch.object(updater, "_fetch_latest", side_effect=OSError("offline")):
            self.assertEqual(updater.release_to_install(cached)["version"], "0.0.9")  # 網路不通就裝原本那版
        with patch.object(updater, "_fetch_latest", return_value=None):
            self.assertEqual(updater.release_to_install(cached)["version"], "0.0.9")

    def test_network_error_is_silent(self):
        with patch.object(updater, "_fetch_latest", side_effect=OSError("offline")):
            self.assertIsNone(updater.check_for_update(force=True))


class DownloadTests(unittest.TestCase):
    def _response(self, data: bytes):
        resp = MagicMock()
        stream = io.BytesIO(data)
        resp.read.side_effect = stream.read
        resp.headers = {"Content-Length": str(len(data))}
        resp.__enter__.return_value = resp
        return resp

    def test_verified_download(self):
        release = updater.summarize_release(RELEASE_PAYLOAD)
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater.tempfile, "gettempdir", return_value=tmp), \
                patch.object(updater.urllib.request, "urlopen", return_value=self._response(INSTALLER)):
            ok, path = updater.download_installer(release)
            self.assertTrue(ok, path)
            self.assertEqual(Path(path).read_bytes(), INSTALLER)

    def test_corrupted_download_is_rejected_and_deleted(self):
        release = updater.summarize_release(RELEASE_PAYLOAD)
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater.tempfile, "gettempdir", return_value=tmp), \
                patch.object(updater.urllib.request, "urlopen", return_value=self._response(INSTALLER[:-5])):
            ok, message = updater.download_installer(release)
            self.assertFalse(ok)
            self.assertIn("驗證失敗", message)
            self.assertFalse((Path(tmp) / release["asset_name"]).exists())


if __name__ == "__main__":
    unittest.main()
