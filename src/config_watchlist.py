"""使用者自訂觀察名單的本地儲存（可在 UI 上自行新增/刪除股票）。

存成 data/watchlist.json，第一次執行時會用 config.py 裡的預設 WATCHLIST 當種子。
"""

import json

from src.config import DATA_DIR, WATCHLIST as _DEFAULT_WATCHLIST

_WATCHLIST_PATH = DATA_DIR / "watchlist.json"


def load_watchlist() -> dict:
    if not _WATCHLIST_PATH.exists():
        save_watchlist(dict(_DEFAULT_WATCHLIST))
        return dict(_DEFAULT_WATCHLIST)
    with open(_WATCHLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_watchlist(watchlist: dict):
    with open(_WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)


def add_stock(code: str, name: str):
    watchlist = load_watchlist()
    watchlist[code] = name
    save_watchlist(watchlist)


def remove_stock(code: str):
    watchlist = load_watchlist()
    watchlist.pop(code, None)
    save_watchlist(watchlist)
