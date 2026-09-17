"""加權指數歷史與個股相對強弱。

相對強弱（relative strength）：把個股與加權指數在同一天都換算成 100 起算，
兩條線的差距就是這段期間個股跑贏／跑輸大盤多少；也提供 N 日超額報酬（個股報酬 − 指數報酬）。
"""

import time
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import twse_market
from src.storage import db

DEFAULT_BACKFILL_MONTHS = 24
_POLITE_SECONDS = 3.0  # 證交所 rwd 介面請求太快會被暫時封鎖


def backfill(months: int = DEFAULT_BACKFILL_MONTHS, progress=None, sleep_seconds: float = _POLITE_SECONDS,
             today: _date | None = None) -> dict:
    """回補近 N 個月的加權指數（含本月）。已有完整資料的月份（非本月且 ≥ 15 個交易日）跳過。"""
    today = today or _date.today()
    counts = db.query_market_index_month_counts()
    stats = {"filled": 0, "skipped": 0, "failed": []}
    year, month = today.year, today.month
    for i in range(months):
        key = f"{year}-{month:02d}"
        if i > 0 and counts.get(key, 0) >= 15:
            stats["skipped"] += 1
        else:
            try:
                rows = twse_market.fetch_month(year, month)
                db.save_market_index(rows)
                stats["filled"] += 1
                if progress:
                    progress(f"{key} 加權指數 {len(rows)} 天")
            except Exception as exc:  # noqa: BLE001 - 單月失敗不影響其他月份
                stats["failed"].append(f"{key}: {exc}")
            if sleep_seconds:
                time.sleep(sleep_seconds)
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return stats


def relative_strength(code: str, days: int = 120, as_of: str | None = None) -> pd.DataFrame:
    """個股與指數對齊後的走勢：date, close, taiex, stock_index, taiex_index（期初＝100）"""
    end = _date.fromisoformat(as_of) if as_of else _date.today()
    start = (end - timedelta(days=days)).isoformat()
    prices = pd.DataFrame(db.query_price_range(code, start, end.isoformat()))
    index = pd.DataFrame(db.query_market_index(start, end.isoformat()))
    if prices.empty or index.empty:
        return pd.DataFrame(columns=["date", "close", "taiex", "stock_index", "taiex_index"])
    merged = prices[["date", "close"]].merge(index[["date", "taiex"]], on="date", how="inner").dropna()
    if merged.empty:
        return pd.DataFrame(columns=["date", "close", "taiex", "stock_index", "taiex_index"])
    merged["stock_index"] = merged["close"] / merged["close"].iloc[0] * 100
    merged["taiex_index"] = merged["taiex"] / merged["taiex"].iloc[0] * 100
    return merged.reset_index(drop=True)


def excess_returns(frame: pd.DataFrame, windows=(20, 60)) -> dict:
    """{N: {"stock": %, "taiex": %, "excess": 百分點}}；資料不足 N 個交易日的回傳 None"""
    result = {}
    for n in windows:
        if len(frame) <= n:
            result[n] = None
            continue
        stock = (frame["close"].iloc[-1] / frame["close"].iloc[-1 - n] - 1) * 100
        taiex = (frame["taiex"].iloc[-1] / frame["taiex"].iloc[-1 - n] - 1) * 100
        result[n] = {"stock": stock, "taiex": taiex, "excess": stock - taiex}
    return result


def index_summary(as_of: str | None = None) -> dict | None:
    """最新（不晚於 as_of）的加權指數與 5／20 日漲跌幅"""
    end = as_of or _date.today().isoformat()
    rows = db.query_market_index((_date.fromisoformat(end) - timedelta(days=60)).isoformat(), end)
    if not rows:
        return None
    last = rows[-1]
    summary = {"date": last["date"], "taiex": last["taiex"], "change": last["change"],
               "change_pct": last["change"] / (last["taiex"] - last["change"]) * 100
               if last["change"] is not None and last["taiex"] - last["change"] else None}
    for n in (5, 20):
        summary[f"return_{n}"] = (last["taiex"] / rows[-1 - n]["taiex"] - 1) * 100 if len(rows) > n else None
    return summary


def market_prompt_block(as_of: str | None = None) -> str:
    s = index_summary(as_of)
    if not s:
        return "（無加權指數資料）"

    def pct(v):
        return "資料不足" if v is None else f"{v:+.2f}%"

    return (f"{s['date']} 加權指數 {s['taiex']:,.2f}（{s['change']:+,.2f} 點，{pct(s['change_pct'])}）；"
            f"近 5 日 {pct(s['return_5'])}、近 20 日 {pct(s['return_20'])}")


def stock_prompt_block(code: str) -> str:
    frame = relative_strength(code)
    if frame.empty:
        return "（無加權指數或股價資料，無法計算相對強弱）"
    lines = []
    for n, item in excess_returns(frame).items():
        if item is None:
            lines.append(f"近 {n} 個交易日：資料不足")
        else:
            lines.append(f"近 {n} 個交易日：個股 {item['stock']:+.2f}%、加權指數 {item['taiex']:+.2f}%，"
                         f"超額 {item['excess']:+.2f} 個百分點")
    return "\n".join(lines)
