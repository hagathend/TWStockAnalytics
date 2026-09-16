"""Windows 桌面通知（右下角跳出的那種），不需要安裝任何套件。

用 PowerShell 呼叫 Windows 內建的 WinRT Toast API。通知必須掛在一個已註冊的應用程式識別碼（AUMID）底下，
這裡借用 Windows PowerShell 本身的識別碼，所以通知來源會顯示「Windows PowerShell」。
腳本用 -EncodedCommand（UTF-16 Base64）傳入，中文與引號都不會被命令列轉義弄壞。
"""

import base64
import subprocess
from xml.sax.saxutils import escape

_POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_MAX_LINES = 3  # Toast 內文最多顯示幾行，太長會被截掉


def build_toast_xml(title: str, lines: list[str]) -> str:
    body = "".join(f"<text>{escape(line)}</text>" for line in lines[:_MAX_LINES - 1])
    if len(lines) > _MAX_LINES - 1:
        body += f"<text>{escape(f'…等共 {len(lines)} 則，請開啟台股分析查看')}</text>"
    return (f'<toast><visual><binding template="ToastGeneric"><text>{escape(title)}</text>{body}'
            f"</binding></visual></toast>")


def build_script(title: str, lines: list[str]) -> str:
    xml = build_toast_xml(title, lines).replace("'", "''")
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null",
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null",
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument",
        f"$xml.LoadXml('{xml}')",
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)",
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_POWERSHELL_AUMID}').Show($toast)",
    ])


def show_toast(title: str, lines: list[str]) -> tuple[bool, str]:
    encoded = base64.b64encode(build_script(title, lines).encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"無法顯示通知：{exc}"
    if result.returncode != 0:
        return False, f"無法顯示通知：{(result.stderr or result.stdout).strip()[-300:]}"
    return True, "已送出通知"
