"""外資持股比例與借券賣出餘額：回補、指標與提示詞。

- 外資持股比例變化以「百分點」表示（69.0% → 69.5% 是 +0.5 個百分點）
- 借券賣出餘額以「張」表示；「相當幾天成交量」＝餘額 ÷ 20 日平均成交量，數字大代表潛在回補買盤或賣壓大
- 回補以本地上市股價的交易日為準，逐日補缺漏（間隔 3 秒，避免被證交所封鎖）
"""

import time
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import twse_ownership
from src.storage import db

DEFAULT_BACKFILL_DAYS = 180
_POLITE_SECONDS = 3.0
_TABLES = {
    "foreign_holding": ("外資持股", twse_ownership.fetch_foreign_holding, "save_foreign_holding"),
    "sbl_short": ("借券賣出", twse_ownership.fetch_sbl, "save_sbl_short"),
}


def backfill(days: int = DEFAULT_BACKFILL_DAYS, progress=None, sleep_seconds: float = _POLITE_SECONDS,
             today: _date | None = None) -> dict:
    today = today or _date.today()
    since = (today - timedelta(days=days)).isoformat()
    trading_dates = [d for d in db.query_trading_dates("TWSE", since) if d < today.isoformat()]
    stats = {"filled": 0, "failed": []}
    for table, (label, fetch, save_name) in _TABLES.items():
        have = db.query_dates_in(table)
        for iso in reversed(trading_dates):  # 新的先補，中斷時最近的資料已經有了
            if iso in have:
                continue
            try:
                rows = fetch(iso.replace("-", ""))
                getattr(db, save_name)(rows)
                stats["filled"] += 1
                if progress:
                    progress(f"{iso} {label} {len(rows)} 檔")
            except Exception as exc:  # noqa: BLE001 - 單日失敗下次重跑會再補
                stats["failed"].append(f"{iso} {label}: {exc}")
            if sleep_seconds:
                time.sleep(sleep_seconds)
    return stats


def _change(series: pd.Series, n: int):
    if len(series) <= n or pd.isna(series.iloc[-1]) or pd.isna(series.iloc[-1 - n]):
        return None
    return float(series.iloc[-1] - series.iloc[-1 - n])


def code_summary(code: str, days: int = 120) -> dict | None:
    since = (_date.today() - timedelta(days=days)).isoformat()
    foreign = pd.DataFrame(db.query_foreign_holding_history(code, since))
    sbl = pd.DataFrame(db.query_sbl_history(code, since))
    if foreign.empty and sbl.empty:
        return None
    summary = {"foreign": foreign, "sbl": sbl, "foreign_pct": None, "foreign_change_5": None,
               "foreign_change_20": None, "foreign_date": None, "sbl_lots": None, "sbl_change_5": None,
               "sbl_change_20": None, "sbl_days_of_volume": None, "sbl_date": None}
    if not foreign.empty:
        summary.update(foreign_pct=float(foreign["foreign_pct"].iloc[-1]), foreign_date=foreign["date"].iloc[-1],
                       foreign_change_5=_change(foreign["foreign_pct"], 5),
                       foreign_change_20=_change(foreign["foreign_pct"], 20))
    if not sbl.empty:
        lots = sbl["balance"] / 1000
        summary.update(sbl_lots=float(lots.iloc[-1]), sbl_date=sbl["date"].iloc[-1],
                       sbl_change_5=_change(lots, 5), sbl_change_20=_change(lots, 20))
        volumes = [r["volume"] for r in db.query_code_history("stock_price", code, limit=20) if r.get("volume")]
        if len(volumes) >= 20:
            avg_volume = sum(volumes) / len(volumes)
            summary["sbl_days_of_volume"] = float(sbl["balance"].iloc[-1]) / avg_volume if avg_volume else None
    return summary


def latest_table() -> pd.DataFrame:
    """每檔最新外資持股比例與 20 個交易日變化（選股器用）"""
    rows = db.query_foreign_holding_changes(20)
    return pd.DataFrame(rows, columns=["code", "foreign_pct", "foreign_change_20"])


def summarize_for_prompt(code: str) -> str:
    s = code_summary(code)
    if not s:
        return "（無外資持股與借券資料，上櫃股目前不收集）"

    def pp(value):
        return "資料不足" if value is None else f"{value:+.2f} 個百分點"

    def lots(value):
        return "資料不足" if value is None else f"{value:+,.0f} 張"

    lines = []
    if s["foreign_pct"] is not None:
        lines.append(f"外資持股比例 {s['foreign_pct']:.2f}%（{s['foreign_date']}），"
                     f"5 日 {pp(s['foreign_change_5'])}、20 日 {pp(s['foreign_change_20'])}")
    if s["sbl_lots"] is not None:
        days = "" if s["sbl_days_of_volume"] is None else f"，約 {s['sbl_days_of_volume']:.1f} 天平均成交量"
        lines.append(f"借券賣出餘額 {s['sbl_lots']:,.0f} 張（{s['sbl_date']}）{days}，"
                     f"5 日 {lots(s['sbl_change_5'])}、20 日 {lots(s['sbl_change_20'])}")
    return "\n".join(lines)
