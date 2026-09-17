"""每日排程執行的收集腳本，供 Windows 工作排程器呼叫（執行時間在「開始使用」或「AI 設定 › 每日排程」設定）。

收集完之後依設定執行 AI 分析：新聞焦點、持股個股、觀察名單個股（各自可開關，見 src/scheduled_ai.py）。

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
    from datetime import date, datetime

    from src.scheduled_ai import run_after_collect

    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 開始每日收集 =====")
    result = run_daily_collect()
    print(result)
    if not run_after_collect(date.today().isoformat()):
        sys.exit(1)
