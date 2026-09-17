"""把開發資料夾（git checkout）收集的資料搬到 Windows 安裝版。

安裝版的資料在 %LOCALAPPDATA%\\TWStockAnalytics\\data，開發資料夾在 <專案>\\data，兩邊互不相通。
這支腳本把開發資料夾的資料複製過去：

- 資料庫用 SQLite 備份 API 複製：開發版程式開著也能拿到一致的快照
- 安裝版原本的資料先整份備份到 data_backup_<時間>，再覆蓋
- 只搬使用者資料與設定；記錄檔、伺服器狀態檔不搬；安裝版的 app_settings.json（引導是否完成）保留
- 安裝版正在執行時拒絕搬移（會寫到一半）
- 搬完檢查資料庫完整性，並逐表比對筆數

用法（在專案根目錄，用開發環境的 python）：
    .venv\\Scripts\\python.exe scripts\\migrate_to_installed.py
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_NAME = "tw_stock.db"
SETTINGS_FILES = ["watchlist.json", "codex_settings.json", "report_settings.json", "scraping_settings.json"]


def default_target() -> Path:
    local = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "TWStockAnalytics" / "data"


def installed_app_running(target: Path) -> bool:
    """看安裝版記錄的伺服器還有沒有回應"""
    try:
        port = int(json.loads((target / "server.json").read_text(encoding="utf-8"))["port"])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as resp:
            return resp.status == 200
    except (OSError, ValueError, KeyError, TypeError):
        return False


def table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def backup_existing(target: Path, now: datetime) -> Path | None:
    if not target.exists() or not any(target.iterdir()):
        return None
    backup = target.parent / f"data_backup_{now:%Y%m%d_%H%M%S}"
    shutil.copytree(target, backup)
    return backup


def copy_database(source_db: Path, target_db: Path) -> None:
    """寫到暫存檔、驗證後再換上，途中失敗不會留下壞掉的資料庫"""
    temp = target_db.with_name(target_db.name + ".migrating")
    temp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dst = sqlite3.connect(temp)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("複製後的資料庫完整性檢查失敗")
    finally:
        dst.close()
        src.close()
    for suffix in ("-wal", "-shm"):  # 舊資料庫的 WAL 檔若留著，會被套用到新資料庫上
        Path(str(target_db) + suffix).unlink(missing_ok=True)
    os.replace(temp, target_db)


def migrate(source: Path, target: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    source_db = source / DB_NAME
    if not source_db.exists():
        raise FileNotFoundError(f"來源沒有資料庫：{source_db}")
    if source.resolve() == target.resolve():
        raise ValueError("來源與目標是同一個資料夾")
    if installed_app_running(target):
        raise RuntimeError("安裝版「台股分析」正在執行，請先在側邊欄按「結束程式」再搬移")

    backup = backup_existing(target, now)
    target.mkdir(parents=True, exist_ok=True)
    copy_database(source_db, target / DB_NAME)

    copied = [DB_NAME]
    for name in SETTINGS_FILES:
        if (source / name).exists():
            shutil.copy2(source / name, target / name)
            copied.append(name)

    source_counts, target_counts = table_counts(source_db), table_counts(target / DB_NAME)
    mismatched = {t: (source_counts[t], target_counts.get(t)) for t in source_counts
                  if source_counts[t] != target_counts.get(t)}
    if mismatched:
        raise RuntimeError(f"搬移後筆數不一致：{mismatched}（原資料已備份在 {backup}）")
    return {"backup": backup, "copied": copied, "counts": target_counts}


def main():
    parser = argparse.ArgumentParser(description="把開發資料夾的資料搬到 Windows 安裝版")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "data", help="來源資料夾（預設：專案的 data）")
    parser.add_argument("--target", type=Path, default=default_target(), help="目標資料夾（預設：安裝版資料位置）")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"來源：{args.source}\n目標：{args.target}")
    try:
        result = migrate(args.source, args.target)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"\n搬移失敗：{exc}")
        sys.exit(1)

    print("\n=== 搬移完成 ===")
    if result["backup"]:
        print(f"安裝版原本的資料已備份到：{result['backup']}")
    print(f"已複製：{', '.join(result['copied'])}")
    for table in ("stock_price", "institutional", "holdings", "stock_analysis"):
        if table in result["counts"]:
            print(f"  {table}: {result['counts'][table]:,} 筆")


if __name__ == "__main__":
    main()
