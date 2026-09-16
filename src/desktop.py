"""桌面整合：給「不懂電腦的使用者」用的安裝版功能。

- 找到正確的 Python 執行檔（安裝版內附的 python，開發時的 .venv）
- 在背景啟動長時間工作（補歷史資料）而不跳出黑色命令列視窗
- 註冊／移除 Windows 每日排程（錯過時間會在開機後補跑）
- 開一個看得到的視窗讓使用者登入 Codex

外部指令一律回傳 (ok, 訊息)，不讓例外往上竄到 UI。
"""

import json
import os
import subprocess
import sys
from datetime import date as _date, timedelta
from pathlib import Path

from src.config import BASE_DIR, DATA_DIR, LOG_DIR

TASK_NAME = "TWStockAnalytics 每日收集"
DEFAULT_TASK_TIME = "20:00"
BACKFILL_DAYS = 180

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_BACKFILL_STATE = DATA_DIR / "backfill_job.json"


def python_executable(windowless: bool = False) -> str:
    """目前這套環境的 python。windowless=True 時優先用 pythonw.exe（排程執行時不跳視窗）"""
    current = Path(sys.executable)
    if windowless:
        candidate = current.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    else:
        candidate = current.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return str(current)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                capture_output=True, text=True, creationflags=_NO_WINDOW)
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ─────────────── 補歷史資料（背景工作） ───────────────

def backfill_status() -> dict:
    """{"running": bool, "started_at": str|None, "log": Path}"""
    try:
        state = json.loads(_BACKFILL_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    return {
        "running": _pid_alive(int(state.get("pid") or 0)),
        "started_at": state.get("started_at"),
        "log": LOG_DIR / "backfill.log",
    }


def start_backfill(days: int = BACKFILL_DAYS) -> tuple[bool, str]:
    if backfill_status()["running"]:
        return False, "歷史資料正在下載中"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "backfill.log", "a", encoding="utf-8")  # noqa: SIM115 - 交給子行程持有
    try:
        process = subprocess.Popen(
            [python_executable(), str(BASE_DIR / "scripts" / "backfill_history.py"), "--days", str(days)],
            # 英文版 Windows 預設編碼 cp1252，子行程印中文會當掉，一律用 UTF-8
            cwd=str(BASE_DIR), env={**os.environ, "PYTHONUTF8": "1"},
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        return False, f"無法啟動下載：{exc}"
    finally:
        log.close()
    _BACKFILL_STATE.write_text(json.dumps({"pid": process.pid, "started_at": _date.today().isoformat()}),
                               encoding="utf-8")
    return True, "已開始在背景下載歷史資料，可以先使用其他功能"


def expected_trading_days(days: int = BACKFILL_DAYS, today: _date | None = None) -> int:
    """補收集範圍內的平日數（約略的交易日目標，不扣國定假日）"""
    today = today or _date.today()
    start = today - timedelta(days=days)
    return sum(1 for i in range(days) if (start + timedelta(days=i)).weekday() < 5)


# ─────────────── Windows 每日排程 ───────────────

def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_register_task_script(time_text: str = DEFAULT_TASK_TIME) -> str:
    """產生註冊排程的 PowerShell 指令。

    用 Register-ScheduledTask 而不是 schtasks：只有它能設定 StartWhenAvailable，
    晚上 8 點電腦沒開的話，下次開機會自動補跑，不懂電腦的使用者不必自己記得手動收集。"""
    script = BASE_DIR / "scripts" / "run_daily_collect.py"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$action = New-ScheduledTaskAction -Execute {_ps_quote(python_executable(windowless=True))} "
        f"-Argument {_ps_quote(chr(34) + str(script) + chr(34))} -WorkingDirectory {_ps_quote(BASE_DIR)}",
        f"$trigger = New-ScheduledTaskTrigger -Daily -At {_ps_quote(time_text)}",
        "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)",
        f"Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Action $action -Trigger $trigger "
        "-Settings $settings -Description '台股分析：每日收集盤後資料與新聞並執行 AI 分析' -Force | Out-Null",
    ])


def _run_powershell(script: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def register_daily_task(time_text: str = DEFAULT_TASK_TIME) -> tuple[bool, str]:
    ok, output = _run_powershell(build_register_task_script(time_text))
    return (True, f"已設定每天 {time_text} 自動收集") if ok else (False, f"設定排程失敗：{output[-500:]}")


def unregister_daily_task() -> tuple[bool, str]:
    ok, output = _run_powershell(
        f"Unregister-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Confirm:$false")
    return (True, "已取消每日自動收集") if ok else (False, f"取消排程失敗：{output[-500:]}")


def daily_task_status() -> dict:
    """{"exists": bool, "time": "20:00"|None}"""
    ok, output = _run_powershell(
        f"$t = Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -ErrorAction SilentlyContinue; "
        "if ($t) { ([datetime]$t.Triggers[0].StartBoundary).ToString('HH:mm') }")
    time_text = output.strip() if ok else ""
    return {"exists": bool(time_text), "time": time_text or None}


# ─────────────── Codex 登入 ───────────────

def open_codex_login(executable: str) -> tuple[bool, str]:
    """開一個看得到的命令列視窗執行 codex login（會自動打開瀏覽器讓使用者登入 ChatGPT 帳號）"""
    try:
        subprocess.Popen([executable, "login"], creationflags=_NEW_CONSOLE)
    except OSError as exc:
        return False, f"無法開啟 Codex 登入：{exc}"
    return True, "已開啟登入視窗，請在跳出的瀏覽器完成登入，完成後回來按「重新檢查」"
