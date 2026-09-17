"""台指期三大法人未平倉：判斷大盤多空的常用籌碼指標。

外資的「多空未平倉口數淨額」最常被參考：淨空單擴大代表外資在期貨端偏空或避險增加，淨空單縮小則相反。
這裡只陳述口數與變化，不下多空結論（期貨部位也可能是現貨的避險）。
"""

import time
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import taifex
from src.storage import db

DEFAULT_BACKFILL_MONTHS = 12
IDENTITY_LABELS = {"foreign": "外資", "trust": "投信", "dealer": "自營商"}


def collect_recent(days: int = 14) -> list[dict]:
    """每日收集：抓最近兩週（涵蓋漏收集的日子），存檔後回傳"""
    today = _date.today()
    rows = taifex.fetch_range(today - timedelta(days=days), today)
    db.save_futures_institutional(rows)
    return rows


def backfill(months: int = DEFAULT_BACKFILL_MONTHS, progress=None, sleep_seconds: float = 2.0,
             today: _date | None = None) -> dict:
    """按月分段下載（單次查詢區間太長會被期交所拒絕）；已有 15 天以上資料的過去月份跳過"""
    today = today or _date.today()
    counts = db.query_futures_month_counts()
    stats = {"filled": 0, "skipped": 0, "failed": []}
    year, month = today.year, today.month
    for i in range(months):
        start = _date(year, month, 1)
        end = min(_date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1), today)
        key = f"{year}-{month:02d}"
        if i > 0 and counts.get(key, 0) >= 15:
            stats["skipped"] += 1
        else:
            try:
                rows = taifex.fetch_range(start, end)
                db.save_futures_institutional(rows)
                stats["filled"] += 1
                if progress:
                    progress(f"{key} 期貨法人 {len(rows) // 3} 天")
            except Exception as exc:  # noqa: BLE001
                stats["failed"].append(f"{key}: {exc}")
            if sleep_seconds:
                time.sleep(sleep_seconds)
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return stats


def net_oi_frame(as_of: str | None = None, days: int = 120) -> pd.DataFrame:
    """每天一列：foreign／trust／dealer 的淨未平倉口數（由舊到新）"""
    end = as_of or _date.today().isoformat()
    since = (_date.fromisoformat(end) - timedelta(days=days)).isoformat()
    rows = db.query_futures_institutional(since, end)
    if not rows:
        return pd.DataFrame(columns=["date", *IDENTITY_LABELS])
    df = pd.DataFrame(rows).pivot_table(index="date", columns="identity", values="net_oi", aggfunc="last")
    return df.reindex(columns=list(IDENTITY_LABELS)).reset_index().sort_values("date").reset_index(drop=True)


def summary(as_of: str | None = None) -> dict | None:
    frame = net_oi_frame(as_of)
    if frame.empty:
        return None
    last = frame.iloc[-1]
    result = {"date": last["date"]}
    for key in IDENTITY_LABELS:
        result[key] = None if pd.isna(last[key]) else int(last[key])
        for n in (1, 5, 20):
            if len(frame) > n and pd.notna(last[key]) and pd.notna(frame[key].iloc[-1 - n]):
                result[f"{key}_change_{n}"] = int(last[key] - frame[key].iloc[-1 - n])
            else:
                result[f"{key}_change_{n}"] = None
    return result


def market_prompt_block(as_of: str | None = None) -> str:
    s = summary(as_of)
    if not s:
        return "（無期貨法人資料）"

    def change(key, n):
        value = s.get(f"{key}_change_{n}")
        return "資料不足" if value is None else f"{value:+,}"

    lines = [f"資料日 {s['date']}（臺股期貨多空未平倉口數淨額，正＝淨多單、負＝淨空單）"]
    for key, label in IDENTITY_LABELS.items():
        if s[key] is None:
            continue
        lines.append(f"{label} {s[key]:+,} 口（較前一日 {change(key, 1)}、5 日 {change(key, 5)}、20 日 {change(key, 20)}）")
    return "\n".join(lines)
