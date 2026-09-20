"""本益比河流圖：用自己過去的本益比區間，看目前股價是偏貴還是偏便宜。

- 推算 EPS：每天的「收盤價 ÷ 證交所公布的本益比」（證交所本益比使用近四季 EPS）
- 河流：推算 EPS × 期間本益比的 10／25／50／75／90 百分位 → 五條價格線
- 目前位置：最新本益比在期間內的百分位（0＝最便宜、100＝最貴）
虧損公司沒有本益比（NULL），那幾天不列入；有效天數太少時不畫，避免用幾天資料就判斷貴或便宜。
只有上市股能回補每日本益比歷史（證交所 BWIBBU_d 可指定日期；櫃買中心只有最新一天）。
"""

import time
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import fundamentals as fundamentals_collector
from src.storage import db

BAND_PERCENTILES = (10, 25, 50, 75, 90)
# 河流圖可以用本益比或股價淨值比：股價 ÷ 倍數＝推算的 EPS 或每股淨值
METRICS = {"pe": {"column": "pe_ratio", "label": "本益比", "base": "EPS"},
           "pb": {"column": "pb_ratio", "label": "股價淨值比", "base": "每股淨值"}}
MIN_VALID_DAYS = 60
DEFAULT_WINDOW_DAYS = 730
_POLITE_SECONDS = 3.0


def backfill(days: int = 180, progress=None, sleep_seconds: float = _POLITE_SECONDS, today: _date | None = None) -> dict:
    """依本地上市股價的交易日，逐日補缺漏的本益比資料"""
    today = today or _date.today()
    since = (today - timedelta(days=days)).isoformat()
    have = db.query_valuation_dates("TWSE")
    stats = {"filled": 0, "failed": []}
    for iso in reversed([d for d in db.query_trading_dates("TWSE", since) if d < today.isoformat()]):
        if iso in have:
            continue
        try:
            rows = fundamentals_collector.fetch_twse_valuation(iso.replace("-", ""))
            db.save_valuation(rows)
            stats["filled"] += 1
            if progress:
                progress(f"{iso} 本益比 {len(rows)} 檔")
        except Exception as exc:  # noqa: BLE001 - 單日失敗下次重跑會再補
            stats["failed"].append(f"{iso}: {exc}")
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return stats


def river(code: str, window_days: int = DEFAULT_WINDOW_DAYS, today: _date | None = None, metric: str = "pe") -> dict | None:
    """{"frame": DataFrame(date, close, pe, eps, band_10..band_90), "multiples": {10: x, ...},
        "current_pe", "percentile", "days"}；資料不足回傳 None。
    metric="pb" 時改用股價淨值比（欄位名稱不變：pe 是倍數、eps 是推算的每股淨值）"""
    today = today or _date.today()
    since = (today - timedelta(days=window_days)).isoformat()
    rows = db.query_pe_history(code, since, METRICS[metric]["column"])
    frame = pd.DataFrame(rows, columns=["date", "close", "pe"])
    frame = frame.dropna()
    frame = frame[(frame["pe"] > 0) & (frame["close"] > 0)]
    if len(frame) < MIN_VALID_DAYS:
        return None
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["eps"] = frame["close"] / frame["pe"]
    multiples = {p: float(frame["pe"].quantile(p / 100)) for p in BAND_PERCENTILES}
    for p, multiple in multiples.items():
        frame[f"band_{p}"] = frame["eps"] * multiple
    current = float(frame["pe"].iloc[-1])
    return {"frame": frame, "multiples": multiples, "current_pe": current,
            "percentile": float((frame["pe"] <= current).mean() * 100), "days": len(frame)}


def latest_percentiles(window_days: int = DEFAULT_WINDOW_DAYS, today: _date | None = None) -> pd.DataFrame:
    """每檔最新本益比在自身歷史的百分位（選股器用）；有效天數不足的不列"""
    today = today or _date.today()
    rows = db.query_valuation_pe_all("TWSE", (today - timedelta(days=window_days)).isoformat())
    df = pd.DataFrame(rows, columns=["date", "code", "pe"]).dropna()
    df = df[df["pe"] > 0]
    if df.empty:
        return pd.DataFrame(columns=["code", "pe_percentile"])
    df = df.sort_values(["code", "date"])
    counts = df.groupby("code")["pe"].transform("size")
    df = df[counts >= MIN_VALID_DAYS]
    if df.empty:
        return pd.DataFrame(columns=["code", "pe_percentile"])
    latest = df.groupby("code").tail(1).set_index("code")["pe"]
    merged = df.join(latest.rename("latest_pe"), on="code")
    percentile = (merged["pe"] <= merged["latest_pe"]).groupby(merged["code"]).mean() * 100
    return percentile.rename("pe_percentile").reset_index()


def summarize_for_prompt(code: str) -> str | None:
    result = river(code)
    if not result:
        return None
    m = result["multiples"]
    return (f"本益比河流：目前 {result['current_pe']:.1f} 倍，位於近 {result['days']} 個交易日的第 "
            f"{result['percentile']:.0f} 百分位（10～90 百分位區間 {m[10]:.1f}～{m[90]:.1f} 倍，中位數 {m[50]:.1f} 倍）")
