"""現股當沖：回補、個股當沖比走勢、全市場最新當沖比（選股與排行用）。

- 當沖比＝當沖成交股數 ÷ 當天總成交股數；比例很高代表短線客主導，股價容易暴漲暴跌
- 回補以本地上市股價的交易日為準（上市、上櫃休市日相同），新的先補，間隔 3 秒避免被封鎖；
  當天資料尚未公布時官方回的是前一天或空表，不存、下次再補
"""

import time
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import day_trading as collector
from src.storage import db

DEFAULT_BACKFILL_DAYS = 45
_POLITE_SECONDS = 3.0
_MARKETS = {"TWSE": ("上市當沖", collector.fetch_twse), "TPEx": ("上櫃當沖", collector.fetch_tpex)}


def backfill(days: int = DEFAULT_BACKFILL_DAYS, progress=None, sleep_seconds: float = _POLITE_SECONDS,
             today: _date | None = None) -> dict:
    today = today or _date.today()
    since = (today - timedelta(days=days)).isoformat()
    trading_dates = [d for d in db.query_trading_dates("TWSE", since) if d <= today.isoformat()]
    stats = {"filled": 0, "failed": []}
    for market, (label, fetch) in _MARKETS.items():
        have = db.query_day_trading_dates(market)
        for iso in reversed(trading_dates):
            if iso in have:
                continue
            try:
                rows = fetch(iso.replace("-", ""))
                db.save_day_trading(rows)
                if rows:
                    stats["filled"] += 1
                if progress:
                    progress(f"{iso} {label} {len(rows)} 檔")
            except Exception as exc:  # noqa: BLE001 - 單日失敗下次重跑會再補
                stats["failed"].append(f"{iso} {label}: {exc}")
            if sleep_seconds:
                time.sleep(sleep_seconds)
    return stats


def code_history(code: str, days: int = 120, today: _date | None = None) -> pd.DataFrame:
    today = today or _date.today()
    frame = pd.DataFrame(db.query_day_trading_history(code, (today - timedelta(days=days)).isoformat()))
    if frame.empty:
        return frame
    total = pd.to_numeric(frame["total_volume"], errors="coerce")
    frame["day_trade_pct"] = frame["day_trade_volume"] / total.where(total > 0) * 100
    return frame


def latest_table(date: str | None = None) -> pd.DataFrame:
    """指定日（預設最近一個有當沖資料的日子）每檔個股的當沖比%"""
    if date is None:
        dates = db.query_day_trading_dates("TWSE") | db.query_day_trading_dates("TPEx")
        if not dates:
            return pd.DataFrame(columns=["code", "day_trade_pct"])
        date = max(dates)
    frame = pd.DataFrame(db.query_day_trading_ratio(date))
    return frame[["code", "day_trade_pct"]] if not frame.empty else pd.DataFrame(columns=["code", "day_trade_pct"])


def summarize_for_prompt(code: str) -> str | None:
    frame = code_history(code, days=45)
    ratio = frame["day_trade_pct"].dropna() if not frame.empty else pd.Series(dtype=float)
    if ratio.empty:
        return None
    return (f"當沖比 最新 {ratio.iloc[-1]:.1f}%（{frame['date'].iloc[-1]}）、"
            f"5 日平均 {ratio.tail(5).mean():.1f}%、20 日平均 {ratio.tail(20).mean():.1f}%")
