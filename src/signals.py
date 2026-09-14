"""技術／籌碼事件訊號：選股篩選器、觀察名單警示、訊號回測共用。

設計重點：訊號是對「整段歷史的每一列」計算的布林欄位，而不是只算最新一天——
這樣選股器取每檔最後一列、回測取過去每一天，用的是同一套定義，不會出現
「畫面上看到的訊號」跟「回測驗證的訊號」其實算法不同的問題。

資料來源是本地資料庫（db.query_market_history），價格欄位為 high/low/close，
成交量單位為「股」。任何需要 N 天歷史的訊號，歷史不足時一律為 False（不硬算）。
"""

from datetime import date as _date, timedelta

import pandas as pd

from src.chip_metrics import prepare_history
from src.storage import db

# 訊號代號 → 顯示名稱。順序即 UI 顯示順序。
SIGNALS = {
    "ma_bull": "均線多頭排列（5>10>20>60）",
    "ma_bear": "均線空頭排列（5<10<20<60）",
    "ma_squeeze": "均線糾結（5/10/20日線差距 < 1%）",
    "breakout_20d": "突破20日新高",
    "breakout_60d": "突破60日新高",
    "breakdown_20d": "跌破20日新低",
    "gap_up": "跳空上漲缺口",
    "gap_down": "跳空下跌缺口",
    "volume_long_red": "爆量長紅（量 > 20日均量2倍、漲 ≥ 4%）",
    "volume_long_black": "爆量長黑（量 > 20日均量2倍、跌 ≥ 4%）",
    "strong_rs": "相對強勢（20日報酬前 10%）",
    "foreign_buy_streak": "外資連買 ≥ 5 天",
    "trust_adoption": "投信認養（連買 ≥ 3 天、5日買超佔量 ≥ 1%）",
    "margin_up_price_down": "融資增、股價跌（5日）",
}

# 偏空的訊號，UI 上用不同顏色或標記提示（不代表賣出建議）
BEARISH_SIGNALS = {"ma_bear", "breakdown_20d", "gap_down", "volume_long_black", "margin_up_price_down"}

_SQUEEZE_THRESHOLD_PCT = 1.0
_VOLUME_SURGE_MULTIPLE = 2.0
_LONG_CANDLE_PCT = 4.0
_STRONG_RS_QUANTILE = 0.9
_FOREIGN_STREAK_DAYS = 5
_TRUST_STREAK_DAYS = 3
_TRUST_VOLUME_RATIO_PCT = 1.0

# 60日均線 + 60日新高需要的日曆天數再多抓一些緩衝
DEFAULT_LOOKBACK_DAYS = 150


def _rolling(grouped, column: str, window: int, how: str) -> pd.Series:
    """每檔股票各自滾動計算；min_periods=window 保證歷史不足時為 NaN"""
    return grouped[column].transform(lambda s: getattr(s.rolling(window, min_periods=window), how)())


def _streak_series(values: pd.Series) -> pd.Series:
    """每一列「到這天為止」的連續同號天數（正＝連買、負＝連賣）。
    0 或缺值會中斷連續；與 chip_metrics.signed_streak 對最後一列的結果一致。"""
    result = []
    current = 0
    for value in values:
        if pd.isna(value) or value == 0:
            current = 0
        elif value > 0:
            current = current + 1 if current > 0 else 1
        else:
            current = current - 1 if current < 0 else -1
        result.append(current)
    return pd.Series(result, index=values.index)


def compute_signals(history: pd.DataFrame) -> pd.DataFrame:
    """對 prepare_history() 的結果逐列加上指標欄位與訊號布林欄位。"""
    if history.empty:
        return history
    df = history.sort_values(["code", "date"]).reset_index(drop=True)
    g = df.groupby("code", sort=False)

    for n in (5, 10, 20, 60):
        df[f"ma{n}"] = _rolling(g, "close", n, "mean")
    df["vol_ma20"] = _rolling(g, "volume", 20, "mean")
    df["prev_close"] = g["close"].shift(1)
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"] = g["low"].shift(1)
    # 「突破前 N 日高點」要跟前 N 天（不含今天）比，否則今天的高點永遠不會大於自己
    df["prior_high_20"] = g["prev_high"].transform(lambda s: s.rolling(20, min_periods=20).max())
    df["prior_high_60"] = g["prev_high"].transform(lambda s: s.rolling(60, min_periods=60).max())
    df["prior_low_20"] = g["prev_low"].transform(lambda s: s.rolling(20, min_periods=20).min())
    df["change_pct"] = (df["close"] / df["prev_close"] - 1) * 100
    df["return_20d"] = (df["close"] / g["close"].shift(20) - 1) * 100

    df["ma_bull"] = (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"]) & (df["ma20"] > df["ma60"])
    df["ma_bear"] = (df["ma5"] < df["ma10"]) & (df["ma10"] < df["ma20"]) & (df["ma20"] < df["ma60"])
    ma_short = df[["ma5", "ma10", "ma20"]]
    spread_pct = (ma_short.max(axis=1) - ma_short.min(axis=1)) / ma_short.min(axis=1) * 100
    df["ma_squeeze"] = ma_short.notna().all(axis=1) & (spread_pct < _SQUEEZE_THRESHOLD_PCT)

    df["breakout_20d"] = df["close"] > df["prior_high_20"]
    df["breakout_60d"] = df["close"] > df["prior_high_60"]
    df["breakdown_20d"] = df["close"] < df["prior_low_20"]
    df["gap_up"] = df["low"] > df["prev_high"]
    df["gap_down"] = df["high"] < df["prev_low"]

    # 20日均量用「前一天為止」的均量，避免今天的爆量把均量一起拉高而稀釋倍數
    prior_vol_ma20 = g["vol_ma20"].shift(1)
    surge = df["volume"] > prior_vol_ma20 * _VOLUME_SURGE_MULTIPLE
    df["volume_long_red"] = surge & (df["change_pct"] >= _LONG_CANDLE_PCT)
    df["volume_long_black"] = surge & (df["change_pct"] <= -_LONG_CANDLE_PCT)

    # 相對強弱：同一天全市場 20 日報酬排名
    rs_threshold = df.groupby("date")["return_20d"].transform(lambda s: s.quantile(_STRONG_RS_QUANTILE))
    df["rs_rank_pct"] = df.groupby("date")["return_20d"].rank(pct=True) * 100
    df["strong_rs"] = df["return_20d"].notna() & (df["return_20d"] >= rs_threshold)

    df["foreign_streak"] = g["foreign_net"].transform(_streak_series)
    df["trust_streak"] = g["trust_net"].transform(_streak_series)
    df["foreign_buy_streak"] = df["foreign_streak"] >= _FOREIGN_STREAK_DAYS
    trust_5d = _rolling(g, "trust_net", 5, "sum")
    volume_5d = _rolling(g, "volume", 5, "sum")
    df["trust_volume_ratio_5d"] = trust_5d / volume_5d * 100
    df["trust_adoption"] = (df["trust_streak"] >= _TRUST_STREAK_DAYS) & (
        df["trust_volume_ratio_5d"] >= _TRUST_VOLUME_RATIO_PCT
    )

    margin_base = g["margin_balance"].shift(5)
    close_base = g["close"].shift(5)
    df["margin_up_price_down"] = (df["margin_balance"] > margin_base) & (df["close"] < close_base)

    for key in SIGNALS:
        df[key] = df[key].fillna(False).astype(bool)
    return df


def load_signal_history(market: str = "TWSE", as_of: str | None = None,
                        lookback_days: int = DEFAULT_LOOKBACK_DAYS, codes=None) -> pd.DataFrame:
    """從本地資料庫讀歷史並計算訊號。as_of 指定時只用那天（含）以前的資料，報告看過去日期才不會偷看未來。

    注意：相對強弱是全市場排名，指定 codes 只讀部分股票時 strong_rs 會失真，
    所以觀察名單警示也是算全市場、再挑出觀察名單的股票。"""
    end = _date.fromisoformat(as_of) if as_of else _date.today()
    since = (end - timedelta(days=lookback_days)).isoformat()
    rows = db.query_market_history(market=market, since=since, codes=codes)
    history = prepare_history(rows)
    if history.empty:
        return history
    history = history[history["date"] <= end.isoformat()]
    return compute_signals(history)


def latest_rows(signal_df: pd.DataFrame) -> pd.DataFrame:
    """每檔股票最新一列。只保留「最新交易日」有資料的股票，已下市／停牌的舊資料不混進來。"""
    if signal_df.empty:
        return signal_df
    last_date = signal_df["date"].max()
    return signal_df[signal_df["date"] == last_date].reset_index(drop=True)


def active_signals(row) -> list[str]:
    return [key for key in SIGNALS if bool(row[key])]


def screen(signal_df: pd.DataFrame, required: list[str], min_avg_volume_lots: float = 500,
           mode: str = "all") -> pd.DataFrame:
    """選股篩選：取最新交易日，mode="all" 需同時符合所有勾選訊號，"any" 符合任一即可。
    min_avg_volume_lots 過濾20日均量過低（張）的冷門股，避免流動性太差的訊號洗版。"""
    latest = latest_rows(signal_df)
    if latest.empty:
        return latest
    mask = latest["vol_ma20"].fillna(0) >= min_avg_volume_lots * 1000
    if required:
        hits = latest[required]
        mask &= hits.all(axis=1) if mode == "all" else hits.any(axis=1)
    result = latest[mask].copy()
    result["signals"] = result.apply(lambda r: "、".join(SIGNALS[k] for k in active_signals(r)), axis=1)
    return result.sort_values("rs_rank_pct", ascending=False, na_position="last").reset_index(drop=True)


def watchlist_alerts(signal_df: pd.DataFrame, codes) -> list[dict]:
    """觀察名單個股的最新訊號，並標出哪些是「今天新出現」（前一交易日沒有）的訊號。"""
    if signal_df.empty:
        return []
    codes = set(codes)
    last_date = signal_df["date"].max()
    alerts = []
    for code, group in signal_df[signal_df["code"].isin(codes)].groupby("code"):
        group = group.sort_values("date")
        today = group.iloc[-1]
        if today["date"] != last_date:
            continue
        current = active_signals(today)
        previous = set(active_signals(group.iloc[-2])) if len(group) >= 2 else set()
        if not current:
            continue
        alerts.append({
            "code": code,
            "name": today["name"],
            "date": today["date"],
            "close": float(today["close"]),
            "change_pct": None if pd.isna(today["change_pct"]) else float(today["change_pct"]),
            "new": [k for k in current if k not in previous],
            "continuing": [k for k in current if k in previous],
        })
    return sorted(alerts, key=lambda a: (-len(a["new"]), a["code"]))


def format_alerts_markdown(alerts: list[dict]) -> str:
    """給每日報告用的 Markdown 表格"""
    if not alerts:
        return "_（觀察名單今天沒有觸發任何訊號）_"
    lines = ["| 代號 | 名稱 | 收盤 | 漲跌% | 今日新訊號 | 持續中訊號 |", "|---|---|---|---|---|---|"]
    for a in alerts:
        change = "-" if a["change_pct"] is None else f"{a['change_pct']:+.2f}%"
        new = "、".join(SIGNALS[k] for k in a["new"]) or "-"
        continuing = "、".join(SIGNALS[k] for k in a["continuing"]) or "-"
        lines.append(f"| {a['code']} | {a['name']} | {a['close']:g} | {change} | {new} | {continuing} |")
    return "\n".join(lines)
