"""資料庫的儲存位置與容量：看目前用了多少、搬到別的資料夾、壓縮（VACUUM）回收空間。

- 位置記在 config.STORAGE_SETTINGS_PATH（{"db_dir": 資料夾}）；沒設定就是預設的資料夾
- 搬移用 SQLite 的 backup API 複製（資料庫開著也能得到一致的副本），完整性檢查通過才切換過去；
  原檔預設保留，勾選才刪除
- 切換是改 db.DB_PATH，這個程式立刻生效；每日排程等其他程式下次啟動時讀設定檔
- 各表大小是把每一欄的資料長度加總估算（這版 SQLite 沒有 dbstat），不含索引，僅供比較哪張表最大
"""

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from src import config
from src.storage import db

_SPACE_MARGIN = 1.1  # 搬移前要求目標磁碟至少有資料庫大小的 1.1 倍空間


def current_path() -> Path:
    return Path(db.DB_PATH)


def is_default() -> bool:
    return current_path().resolve() == (config.DEFAULT_DB_DIR / config.DB_FILE_NAME).resolve()


def _file_size(path: Path) -> int:
    """資料庫本體加上 WAL／journal 暫存檔"""
    total = 0
    for suffix in ("", "-wal", "-journal", "-shm"):
        candidate = Path(f"{path}{suffix}")
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


def usage() -> dict:
    path = current_path()
    info = {"path": str(path), "size": _file_size(path), "free_disk": None, "reclaimable": 0,
            "is_default": is_default(), "location_error": config.DB_LOCATION_ERROR}
    try:
        info["free_disk"] = shutil.disk_usage(path.parent).free
    except OSError:
        pass
    if path.is_file():
        with closing(sqlite3.connect(path)) as conn:
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            info["reclaimable"] = conn.execute("PRAGMA freelist_count").fetchone()[0] * page_size
    return info


def table_sizes() -> list[dict]:
    """[{table, rows, bytes}]，依估算大小由大到小"""
    path = current_path()
    if not path.is_file():
        return []
    result = []
    with closing(sqlite3.connect(path)) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            length = " + ".join(f'COALESCE(LENGTH("{c}"), 0)' for c in columns) or "0"
            rows, size = conn.execute(f'SELECT COUNT(*), SUM({length}) FROM "{table}"').fetchone()
            result.append({"table": table, "rows": rows, "bytes": int(size or 0)})
    return sorted(result, key=lambda r: r["bytes"], reverse=True)


def _write_setting(db_dir: Path | None):
    config.STORAGE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if db_dir is None or db_dir.resolve() == config.DEFAULT_DB_DIR.resolve():
        config.STORAGE_SETTINGS_PATH.unlink(missing_ok=True)
    else:
        config.STORAGE_SETTINGS_PATH.write_text(json.dumps({"db_dir": str(db_dir)}, ensure_ascii=False, indent=2),
                                                encoding="utf-8")


def move_database(target_dir: str, delete_old: bool = False) -> tuple[bool, str]:
    """把資料庫搬到 target_dir（資料夾不存在會建立）。回傳 (成功與否, 給使用者看的訊息)"""
    if not str(target_dir or "").strip():
        return False, "請輸入資料夾路徑"
    target_dir = Path(str(target_dir).strip().strip('"')).expanduser()
    if not target_dir.is_absolute():
        return False, "請輸入完整路徑，例如 D:\\TWStockData"
    source = current_path()
    target = target_dir / config.DB_FILE_NAME
    if target.resolve() == source.resolve():
        return False, "資料庫已經在這個資料夾"
    if target.exists():
        return False, f"目標資料夾已經有 {config.DB_FILE_NAME}，為避免覆蓋請換一個資料夾，或先把那個檔案移走"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target_dir).free
    except OSError as exc:
        return False, f"無法使用這個資料夾：{exc}"
    size = _file_size(source)
    if free < size * _SPACE_MARGIN:
        return False, f"目標磁碟空間不足：需要約 {format_bytes(size * _SPACE_MARGIN)}，只剩 {format_bytes(free)}"

    try:
        # sqlite3 連線的 with 只會 commit 不會關閉，檔案會一直被占用（Windows 上就刪不掉原檔），所以用 closing
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(target)) as check:
            status = check.execute("PRAGMA quick_check").fetchone()[0]
        if status != "ok":
            raise sqlite3.DatabaseError(f"完整性檢查失敗：{status}")
    except (sqlite3.Error, OSError) as exc:
        target.unlink(missing_ok=True)
        return False, f"複製資料庫失敗，已取消搬移（原本的資料庫沒有變動）：{exc}"

    try:
        _write_setting(target_dir)
    except OSError as exc:
        target.unlink(missing_ok=True)
        return False, f"無法寫入位置設定，已取消搬移：{exc}"
    db.DB_PATH = target
    config.DB_LOCATION_ERROR = None

    message = f"已搬到 {target}"
    if delete_old:
        try:
            for suffix in ("", "-wal", "-journal", "-shm"):
                Path(f"{source}{suffix}").unlink(missing_ok=True)
            message += "，原本的檔案已刪除"
        except OSError as exc:
            message += f"；原本的檔案刪除失敗（可以自己手動刪除 {source}）：{exc}"
    else:
        message += f"；原本的檔案保留在 {source}，確認沒問題後可以自己刪除"
    return True, message


def vacuum() -> tuple[bool, str]:
    """重整資料庫、回收刪除資料後留下的空間（期間資料庫會被鎖住，資料量大時要一段時間）"""
    path = current_path()
    before = _file_size(path)
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, f"壓縮失敗（可能正在收集資料，稍後再試）：{exc}"
    after = _file_size(path)
    return True, f"壓縮完成：{format_bytes(before)} → {format_bytes(after)}"


def format_bytes(size: float | None) -> str:
    if size is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.0f} {unit}" if unit in ("B", "KB") else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} GB"
