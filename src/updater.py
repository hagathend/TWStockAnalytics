"""檢查 GitHub Releases 有沒有新版，並下載、執行新版安裝程式。

- 只有安裝版才檢查（開發資料夾用 git 更新就好）
- 一天最多問 GitHub 一次，結果快取在 app_settings.json；網路不通時安靜失敗，不影響使用
- 下載的安裝程式如果 GitHub 有提供 SHA-256（asset.digest），下載後比對，不符就不執行
"""

import hashlib
import json
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from src.config_app import load_app_settings, save_app_settings
from src.version import __version__

REPO = "hagathend/TWStockAnalytics"
_LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
_CHECK_INTERVAL = timedelta(hours=24)
_INSTALLER_PREFIX = "TWStockAnalytics-Setup-"


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.0.3' / '0.0.3' → (0, 0, 3)；無法解析的部分當 0"""
    parts = []
    for piece in (text or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str | None = None) -> bool:
    a, b = parse_version(latest), parse_version(current or __version__)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def summarize_release(payload: dict) -> dict | None:
    """GitHub API 回應 → 我們需要的欄位；沒有安裝程式檔案的 release 視為無效"""
    asset = next((a for a in payload.get("assets", [])
                  if a.get("name", "").startswith(_INSTALLER_PREFIX) and a["name"].endswith(".exe")), None)
    if not payload.get("tag_name") or not asset:
        return None
    digest = asset.get("digest") or ""
    return {
        "version": payload["tag_name"].lstrip("vV"),
        "page_url": payload.get("html_url"),
        "notes": payload.get("body") or "",
        "asset_name": asset["name"],
        "asset_url": asset["browser_download_url"],
        "asset_size": asset.get("size"),
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
    }


def _fetch_latest() -> dict | None:
    request = urllib.request.Request(_LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": "TWStockAnalytics-updater"})
    with urllib.request.urlopen(request, timeout=5) as resp:
        return summarize_release(json.load(resp))


def check_for_update(force: bool = False, now: datetime | None = None) -> dict | None:
    """有比目前更新的版本就回傳 release 資訊，否則 None。網路錯誤一律當作沒有更新。"""
    now = now or datetime.now()
    settings = load_app_settings()
    checked_at = settings.get("update_checked_at")
    fresh = False
    if checked_at and not force:
        try:
            fresh = now - datetime.fromisoformat(checked_at) < _CHECK_INTERVAL
        except ValueError:
            fresh = False
    if fresh:
        release = settings.get("latest_release")
    else:
        try:
            release = _fetch_latest()
        except (OSError, ValueError):
            return None
        save_app_settings({"update_checked_at": now.isoformat(timespec="seconds"), "latest_release": release})
    if release and is_newer(release["version"]):
        return release
    return None


def download_installer(release: dict, progress=None) -> tuple[bool, str]:
    """下載到暫存資料夾並驗證雜湊。回傳 (ok, 檔案路徑或錯誤訊息)。progress(已下載, 總大小)"""
    target = Path(tempfile.gettempdir()) / release["asset_name"]
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(release["asset_url"], headers={"User-Agent": "TWStockAnalytics-updater"})
        with urllib.request.urlopen(request, timeout=30) as resp, open(target, "wb") as out:
            total = int(resp.headers.get("Content-Length") or release.get("asset_size") or 0)
            done = 0
            while chunk := resp.read(1024 * 256):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as exc:
        return False, f"下載更新失敗，請稍後再試：{exc}"
    if release.get("sha256") and digest.hexdigest() != release["sha256"].lower():
        target.unlink(missing_ok=True)
        return False, "下載的檔案驗證失敗（可能下載不完整），請稍後再試"
    return True, str(target)


def run_installer(path: str) -> tuple[bool, str]:
    """執行新版安裝程式。安裝程式會自動關閉目前的程式，完成後可勾選「立即開啟」。"""
    try:
        subprocess.Popen([path, "/SP-"])
    except OSError as exc:
        return False, f"無法開啟安裝程式：{exc}"
    return True, "已開啟安裝程式，照畫面指示按「下一步」完成更新，程式會自動重新開啟"
