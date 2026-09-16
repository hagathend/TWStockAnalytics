"""每日 20:00 執行的收集腳本，供 Windows 工作排程器呼叫。

用法（在專案根目錄執行）:
    python scripts/run_daily_collect.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import LOG_DIR  # noqa: E402

# 安裝版的排程用 pythonw 執行（不跳視窗），這時沒有 stdout，輸出改寫到記錄檔方便事後查問題
if sys.stdout is None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG_DIR / "daily_collect.log", "a", encoding="utf-8")  # noqa: SIM115

from src.collect_all import run_daily_collect  # noqa: E402

if __name__ == "__main__":
    from datetime import datetime

    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 開始每日收集 =====")
    result = run_daily_collect()
    print(result)
    from datetime import date
    from src.config_ai import load_codex_settings
    from src.ai_analysis import analyze_with_codex_deep

    if load_codex_settings().get("auto_analyze_after_collect", True):
        analysis = analyze_with_codex_deep(date.today().isoformat())
        print(analysis["message"])
        if not analysis["ok"]:
            sys.exit(1)
