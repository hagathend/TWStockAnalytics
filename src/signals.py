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
# 不分多空的訊號（只代表「快要選方向」）
NEUTRAL_SIGNALS = {"ma_squeeze"}

# 四類訊號各自回答不同的問題；判讀時先看格局、再看事件，量能用來確認力道，籌碼看是誰在買賣
SIGNAL_GROUPS = {
    "格局": ["ma_bull", "ma_bear", "ma_squeeze"],
    "事件": ["breakout_20d", "breakout_60d", "breakdown_20d", "gap_up", "gap_down"],
    "量能": ["volume_long_red", "volume_long_black", "strong_rs"],
    "籌碼": ["foreign_buy_streak", "trust_adoption", "margin_up_price_down"],
}
GROUP_QUESTIONS = {"格局": "現在是什麼趨勢", "事件": "今天發生什麼轉折", "量能": "動作有沒有力道", "籌碼": "誰在買、誰在賣"}

# 滑鼠移上去看的說明：程式怎麼判斷＋一般怎麼解讀（僅供理解訊號，不是買賣建議）
SIGNAL_HELP = {
    "ma_bull": "5日＞10日＞20日＞60日均線。短中長期平均成本一路往上，典型的上升趨勢（順風）。會連續成立很多天，是背景狀態",
    "ma_bear": "5日＜10日＜20日＜60日均線。平均成本一路往下，典型的下跌趨勢（逆風）",
    "ma_squeeze": "5／10／20日均線差距小於 1%。近期買進成本都差不多，股價在盤整、還沒選方向，之後常出現較大波動，方向未定",
    "breakout_20d": "收盤高於前 20 天最高價。近一個月上方沒有套牢賣壓；要留意隔幾天又跌回去的「假突破」，有量比較可信",
    "breakout_60d": "收盤高於前 60 天最高價。同 20 日新高但時間更長，通常比 20 日突破更有份量",
    "breakdown_20d": "收盤低於前 20 天最低價。近一個月買的人全部套牢，可能引發停損賣壓",
    "gap_up": "今天最低價高於昨天最高價。開盤就急著買，買盤很急；缺口常被當作之後的支撐觀察",
    "gap_down": "今天最高價低於昨天最低價。開盤就急著賣，常跟利空消息有關；缺口常被當作之後的壓力觀察",
    "volume_long_red": "成交量超過前 20 日均量 2 倍、漲 4% 以上。大量資金推升；搭配突破更可信，但在已大漲的高檔出現要留意追價過熱",
    "volume_long_black": "成交量超過前 20 日均量 2 倍、跌 4% 以上。很多人急著出場；在高檔出現常被解讀為有人出貨",
    "strong_rs": "近 20 日報酬在全市場前 10%。最近比大部分股票強，不受大盤好壞影響",
    "foreign_buy_streak": "外資連續 5 天以上買超。外資持續布局，資金大、常影響中期走勢",
    "trust_adoption": "投信連買 3 天以上、5 日買超佔成交量 1% 以上。基金開始集中買這檔；季底前常有作帳行情",
    "margin_up_price_down": "5 天內融資餘額增加、股價卻下跌。散戶借錢逢低承接，籌碼變亂，一般視為警訊",
}


def group_of(key: str) -> str | None:
    return next((group for group, keys in SIGNAL_GROUPS.items() if key in keys), None)


def direction_of(key: str) -> str:
    return "偏空" if key in BEARISH_SIGNALS else "中性" if key in NEUTRAL_SIGNALS else "偏多"


def summarize(keys) -> dict:
    """一組同時成立的訊號 → 多空數量、涵蓋幾類、一句描述（只整理訊號，不做買賣判斷）"""
    keys = [k for k in keys if k in SIGNALS]
    bullish = [k for k in keys if direction_of(k) == "偏多"]
    bearish = [k for k in keys if direction_of(k) == "偏空"]

    def groups(items):
        return [g for g in SIGNAL_GROUPS if any(group_of(k) == g for k in items)]

    if bullish and bearish:
        status, tone = "多空訊號並存，看法分歧", "warn"
    elif len(bullish) >= 2:
        status, tone = f"偏多訊號同向（{'、'.join(groups(bullish))}）", "up"
    elif len(bearish) >= 2:
        status, tone = f"偏空訊號同向（{'、'.join(groups(bearish))}）", "down"
    elif bullish or bearish:
        status, tone = "單一訊號，參考性較低", ""
    elif keys:
        status, tone = "只有盤整訊號，尚未表態", ""
    else:
        status, tone = "沒有訊號", ""
    return {"bullish": bullish, "bearish": bearish, "status": status, "tone": tone,
            "short": f"多{len(bullish)}／空{len(bearish)}" if keys else ""}

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


def summary_text(keys) -> str:
    summary = summarize(keys)
    return f"{summary['short']}・{summary['status']}" if summary["short"] else ""


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
    result["signal_summary"] = result.apply(lambda r: summary_text(active_signals(r)), axis=1)
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
    lines = ["| 代號 | 名稱 | 收盤 | 漲跌% | 今日新訊號 | 持續中訊號 | 多空整理 |", "|---|---|---|---|---|---|---|"]
    for a in alerts:
        change = "-" if a["change_pct"] is None else f"{a['change_pct']:+.2f}%"
        new = "、".join(SIGNALS[k] for k in a["new"]) or "-"
        continuing = "、".join(SIGNALS[k] for k in a["continuing"]) or "-"
        summary = summary_text(a["new"] + a["continuing"]) or "-"
        lines.append(f"| {a['code']} | {a['name']} | {a['close']:g} | {change} | {new} | {continuing} | {summary} |")
    return "\n".join(lines)
