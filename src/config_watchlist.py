"""使用者自訂觀察名單的本地儲存：可以有多個名單組合（例如「半導體」「高殖利率」）。

存成 data/watchlist.json：{"groups": {"名單名稱": {"代號": "名稱", ...}, ...}}（名單順序即顯示順序）。
舊版格式是單一名單 {"代號": "名稱"}，讀取時自動轉成一個「我的觀察名單」。
第一次執行時會用 config.py 裡的預設 WATCHLIST 當種子。

收集、提醒、行事曆、報告這些「不分名單」的用途，用 load_watchlist() 取得所有名單的聯集。
"""

import json

from src.config import DATA_DIR, WATCHLIST as _DEFAULT_WATCHLIST

_WATCHLIST_PATH = DATA_DIR / "watchlist.json"
DEFAULT_GROUP = "我的觀察名單"


class WatchlistError(ValueError):
    pass


def _migrate(raw: dict) -> dict[str, dict[str, str]]:
    if isinstance(raw.get("groups"), dict):
        return {str(name): dict(stocks) for name, stocks in raw["groups"].items()}
    return {DEFAULT_GROUP: dict(raw)}


def load_groups() -> dict[str, dict[str, str]]:
    if not _WATCHLIST_PATH.exists():
        groups = {DEFAULT_GROUP: dict(_DEFAULT_WATCHLIST)}
        save_groups(groups)
        return groups
    with open(_WATCHLIST_PATH, "r", encoding="utf-8") as f:
        groups = _migrate(json.load(f))
    return groups or {DEFAULT_GROUP: {}}


def save_groups(groups: dict[str, dict[str, str]]):
    with open(_WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump({"groups": groups}, f, ensure_ascii=False, indent=2)


def load_watchlist() -> dict[str, str]:
    """所有名單的聯集（代號 → 名稱，依名單順序、先出現的為準）"""
    merged: dict[str, str] = {}
    for stocks in load_groups().values():
        for code, name in stocks.items():
            merged.setdefault(code, name)
    return merged


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise WatchlistError("名單名稱不能空白")
    return name


def create_group(name: str) -> str:
    name = _clean_name(name)
    groups = load_groups()
    if name in groups:
        raise WatchlistError(f"已經有「{name}」這個名單")
    groups[name] = {}
    save_groups(groups)
    return name


def rename_group(old: str, new: str) -> str:
    new = _clean_name(new)
    groups = load_groups()
    if old not in groups:
        raise WatchlistError(f"找不到「{old}」名單")
    if new != old and new in groups:
        raise WatchlistError(f"已經有「{new}」這個名單")
    # 保持原本的順序
    save_groups({(new if key == old else key): stocks for key, stocks in groups.items()})
    return new


def delete_group(name: str):
    groups = load_groups()
    if name not in groups:
        raise WatchlistError(f"找不到「{name}」名單")
    if len(groups) == 1:
        raise WatchlistError("至少要保留一個名單")
    groups.pop(name)
    save_groups(groups)


def _group_or_first(groups: dict, group: str | None) -> str:
    if group is None:
        return next(iter(groups))
    if group not in groups:
        raise WatchlistError(f"找不到「{group}」名單")
    return group


def add_stock(code: str, name: str, group: str | None = None):
    groups = load_groups()
    group = _group_or_first(groups, group)
    groups[group][code] = name
    save_groups(groups)


def remove_stock(code: str, group: str | None = None):
    groups = load_groups()
    group = _group_or_first(groups, group)
    groups[group].pop(code, None)
    save_groups(groups)


def add_stocks(stocks: list[tuple[str, str]], group: str | None = None) -> tuple[list[str], list[str]]:
    """一次加入多檔（選股工具複選用），只寫一次檔。回傳 (新加入的代號, 原本就在名單裡的代號)"""
    groups = load_groups()
    group = _group_or_first(groups, group)
    watchlist = groups[group]
    added, existing = [], []
    for code, name in stocks:
        if code in watchlist:
            existing.append(code)
        else:
            watchlist[code] = name
            added.append(code)
    if added:
        save_groups(groups)
    return added, existing
