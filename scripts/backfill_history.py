"""一次性補收集上市（TWSE）歷史資料：股價、三大法人、融資融券。

選股篩選器、籌碼延伸指標、回測都需要一段連續歷史。可以中斷後重新執行，
已經補好的日期與已知的非交易日都會跳過，只補缺的部分。

用法（在專案根目錄執行）:
    .venv\\Scripts\\python.exe scripts\\backfill_history.py            # 預設補最近 180 天
    .venv\\Scripts\\python.exe scripts\\backfill_history.py --days 365 # 補一年
"""

import argparse
import io
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

from src import market_index, revenue  # noqa: E402
from src.backfill import DEFAULT_SLEEP_SECONDS, backfill_twse  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="補收集 TWSE 歷史資料")
    parser.add_argument("--days", type=int, default=180, help="往回補幾個日曆天（預設 180）")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS,
                        help="每個請求間隔秒數，太快會被 TWSE 暫時封鎖（預設 3）")
    parser.add_argument("--revenue-months", type=int, default=revenue.DEFAULT_BACKFILL_MONTHS,
                        help="月營收往回補幾個月（預設 24，0＝不補）")
    args = parser.parse_args()

    end = date.today() - timedelta(days=1)
    start = date.today() - timedelta(days=args.days)
    print(f"補收集範圍: {start} ~ {end}（間隔 {args.sleep} 秒）")

    stats = backfill_twse(start, end, sleep_seconds=args.sleep, progress=print)

    print("\n補收集加權指數：近 24 個月")
    index_stats = market_index.backfill(24, progress=print)
    stats["failed"] += index_stats["failed"]

    if args.revenue_months:
        print(f"\n補收集月營收：近 {args.revenue_months} 個月")
        revenue_stats = revenue.backfill(args.revenue_months, progress=print)
        print(f"月營收補齊 {revenue_stats['filled']} 份、跳過 {revenue_stats['skipped']} 份")
        stats["failed"] += revenue_stats["failed"]

    print("\n=== 完成 ===")
    print(f"補齊 {stats['filled']} 天、已完整跳過 {stats['skipped']} 天、非交易日 {stats['non_trading']} 天、"
          f"發出請求 {stats['requests']} 次")
    if stats["failed"]:
        print(f"失敗 {len(stats['failed'])} 天（重新執行會自動重試）: {stats['failed']}")
        sys.exit(1)
