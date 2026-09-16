"""台股分析啟動器（桌面捷徑執行的就是這支，用 pythonw 執行，不會跳出黑色命令列視窗）。

1. 程式已經在跑 → 直接打開瀏覽器
2. 還沒跑 → 在背景啟動 Streamlit，等它準備好再打開瀏覽器，等待期間顯示「啟動中」小視窗
3. 啟動失敗 → 跳出訊息告訴使用者記錄檔在哪裡

伺服器位址與 PID 記在 資料夾/server.json；「結束程式」按鈕在 App 側邊欄。
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.config import DATA_DIR, LOG_DIR  # noqa: E402

STATE_FILE = DATA_DIR / "server.json"
PREFERRED_PORT = 8501
STARTUP_TIMEOUT_SECONDS = 120


def is_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def choose_port(preferred: int = PREFERRED_PORT, attempts: int = 50) -> int:
    for port in range(preferred, preferred + attempts):
        if port_is_free(port):
            return port
    with socket.socket() as sock:  # 全部被占用時交給系統挑一個
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def running_port() -> int | None:
    try:
        port = int(json.loads(STATE_FILE.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if is_healthy(port) else None


def start_server(port: int) -> subprocess.Popen:
    python = Path(sys.executable).with_name("python.exe")
    if not python.exists():
        python = Path(sys.executable)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "app.log", "a", encoding="utf-8")  # noqa: SIM115 - 交給子行程持有
    # 英文版 Windows 的預設編碼是 cp1252，程式印出中文會當掉，子行程一律用 UTF-8
    env = {**os.environ, "PYTHONUTF8": "1"}
    process = subprocess.Popen(
        [str(python), "-m", "streamlit", "run", str(BASE_DIR / "src" / "app.py"),
         "--server.port", str(port), "--server.address", "127.0.0.1", "--server.headless", "true",
         "--browser.gatherUsageStats", "false", "--global.developmentMode", "false"],
        cwd=str(BASE_DIR), env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log.close()
    STATE_FILE.write_text(json.dumps({"port": port, "pid": process.pid}), encoding="utf-8")
    return process


def wait_until_ready(process: subprocess.Popen, port: int, timeout: float = STARTUP_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if is_healthy(port):
            return True
        time.sleep(0.5)
    return False


def _show_error(message: str):
    try:
        import tkinter.messagebox as messagebox
        from tkinter import Tk

        root = Tk()
        root.withdraw()
        messagebox.showerror("台股分析", message)
        root.destroy()
    except Exception:  # noqa: BLE001 - 連錯誤視窗都開不了時，至少留在記錄檔
        (LOG_DIR / "launcher_error.log").write_text(message, encoding="utf-8")


def _run_with_splash(task):
    """有 tkinter 就顯示「啟動中」小視窗，工作完成自動關閉；沒有就直接執行"""
    try:
        from tkinter import Label, Tk
    except ImportError:
        return task()

    result = {}
    root = Tk()
    root.title("台股分析")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    Label(root, text="台股分析啟動中，請稍候…", padx=36, pady=22, font=("Microsoft JhengHei", 12)).pack()
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")

    def worker():
        result["value"] = task()
        root.after(0, root.destroy)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return result.get("value")


def main():
    port = running_port()
    if port:
        webbrowser.open(f"http://127.0.0.1:{port}")
        return

    def launch():
        chosen = choose_port()
        process = start_server(chosen)
        return chosen if wait_until_ready(process, chosen) else None

    port = _run_with_splash(launch)
    if port:
        webbrowser.open(f"http://127.0.0.1:{port}")
    else:
        _show_error(f"台股分析啟動失敗。\n\n請把這個記錄檔傳給提供程式的人：\n{LOG_DIR / 'app.log'}")


if __name__ == "__main__":
    main()
