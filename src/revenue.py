"""月營收歷史回補與營收訊號。

訊號（以每檔最新一個月為準）：
- 營收創 12 個月新高：當月營收 ≥ 前 11 個月的最高營收（需要連續 12 個月資料）
- 年增率連續成長月數：從最新月份往回數，年增率 > 0 的連續月數（中間缺月就停止計算）
"""

import time
from datetime import date as _date

import pandas as pd

from src.collectors import mops_revenue
from src.storage import db

DEFAULT_BACKFILL_MONTHS = 24
_POLITE_SECONDS = 2.0
_MIN_ROWS_COMPLETE = {"TWSE": 800, "TPEx": 650}  # 已有這麼多筆就視為該月已回補，不重抓


def _months_back(n: int, today: _date | None = None) -> list[tuple[int, int]]:
    """由新到舊的 (年, 月)，從上個月開始（本月營收還沒公布）"""
    today = today or _date.today()
    year, month = today.year, today.month
    result = []
    for _ in range(n):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        result.append((year, month))
    return result


def backfill(months: int = DEFAULT_BACKFILL_MONTHS, progress=None, sleep_seconds: float = _POLITE_SECONDS,
             today: _date | None = None) -> dict:
    counts = db.query_month_revenue_counts()
    stats = {"filled": 0, "skipped": 0, "failed": []}
    for year, month in _months_back(months, today):
        year_month = f"{year}-{month:02d}"
        for market in ("TWSE", "TPEx"):
            if counts.get((year_month, market), 0) >= _MIN_ROWS_COMPLETE[market]:
                stats["skipped"] += 1
                continue
            try:
                rows = mops_revenue.fetch_month(year, month, market)
            except Exception as exc:  # noqa: BLE001 - 單月失敗不影響其他月份，下次重跑會再補
                stats["failed"].append(f"{year_month} {market}: {exc}")
                continue
            finally:
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            db.save_month_revenue(rows)
            stats["filled"] += 1
            if progress:
                progress(f"{year_month} {market} 月營收 {len(rows)} 家")
    return stats


def compute_signals(history: pd.DataFrame) -> pd.DataFrame:
    """history：code, year_month, revenue, yoy_pct（全部月份）→ 每檔最新月份的訊號"""
    columns = ["code", "year_month", "revenue", "yoy_pct", "revenue_high_12m", "yoy_growth_streak"]
    if history.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for code, group in history.sort_values("year_month").groupby("code"):
        group = group.drop_duplicates("year_month", keep="last")
        periods = pd.PeriodIndex(group["year_month"], freq="M")
        latest = group.iloc[-1]
        # 往回數「連續」月份：月份中間有缺就停止
        consecutive = 1
        for i in range(len(group) - 1, 0, -1):
            if (periods[i] - periods[i - 1]).n != 1:
                break
            consecutive += 1
        window = group.tail(min(consecutive, 12))
        high_12m = None
        if len(window) >= 12 and pd.notna(latest["revenue"]):
            high_12m = bool(latest["revenue"] >= window["revenue"].iloc[:-1].max())
        streak = 0
        for yoy in reversed(group.tail(consecutive)["yoy_pct"].tolist()):
            if yoy is None or pd.isna(yoy) or yoy <= 0:
                break
            streak += 1
        rows.append({"code": code, "year_month": latest["year_month"], "revenue": latest["revenue"],
                     "yoy_pct": latest["yoy_pct"], "revenue_high_12m": high_12m, "yoy_growth_streak": streak})
    return pd.DataFrame(rows, columns=columns)


def latest_signals() -> pd.DataFrame:
    return compute_signals(pd.DataFrame(db.query_month_revenue_history(), columns=["code", "year_month", "revenue", "yoy_pct"]))


def code_history(code: str, months: int = 24) -> pd.DataFrame:
    rows = db.query_code_fundamentals(code, revenue_months=months)["revenue"]
    df = pd.DataFrame(rows)
    return df.sort_values("year_month").reset_index(drop=True) if not df.empty else df


def summarize_for_prompt(code: str) -> str | None:
    history = code_history(code)
    if history.empty:
        return None
    signals = compute_signals(history.assign(code=code))
    if signals.empty:
        return None
    s = signals.iloc[0]
    parts = [f"已累積 {len(history)} 個月營收"]
    if s["revenue_high_12m"] is not None:
        parts.append("最新月營收創近 12 個月新高" if s["revenue_high_12m"] else "最新月營收未創近 12 個月新高")
    parts.append(f"年增率連續成長 {int(s['yoy_growth_streak'])} 個月")
    return "；".join(parts)
