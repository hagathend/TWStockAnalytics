"""每日 20:00 執行的收集腳本，供 Windows 工作排程器呼叫。

用法（在專案根目錄執行）:
    python scripts/run_daily_collect.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.collect_all import run_daily_collect  # noqa: E402

if __name__ == "__main__":
    result = run_daily_collect()
    print(result)
