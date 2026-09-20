"""市場溫度計：上市個股每天的漲跌家數、收盤創 20／60 日新高新低家數、成交值熱度。

用來判斷「整體市場是普漲還是只有少數權值股在撐」：
- 指數漲但創新低家數增加 → 內部轉弱（背離）
- 創新高家數持續多於創新低 → 多頭廣度健康
「創 N 日新高」＝今天收盤高於「前 N 個交易日（不含今天）」的最高收盤；歷史不足 N 天的股票不列入。
"""

import pandas as pd

from src.storage import db

WINDOWS = (20, 60)
DEFAULT_LOOKBACK_DAYS = 200  # 要算 60 日新高，再往前多留緩衝


def load_price_history(since: str) -> pd.DataFrame:
    rows = [r for r in db.query_price_history("TWSE", since) if db.is_stock_code(r["code"])]
    if not rows:
        return pd.DataFrame(columns=["date", "code", "close", "change", "turnover"])
    df = pd.DataFrame(rows)[["date", "code", "close", "change", "turnover"]]
    for column in ("close", "change", "turnover"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def compute_breadth(history: pd.DataFrame) -> pd.DataFrame:
    """每個交易日一列的市場廣度統計（由舊到新）"""
    columns = ["date", "up", "down", "flat", "ad_ratio", "adl", "turnover", "turnover_ma20_ratio",
               *[f"new_high_{n}" for n in WINDOWS], *[f"new_low_{n}" for n in WINDOWS]]
    if history.empty:
        return pd.DataFrame(columns=columns)
    df = history.copy()
    # 向量化：先依股票把收盤往後移一天，再分組滾動（比逐檔 lambda 快一個數量級）
    df["prev_close"] = df.groupby("code", sort=False)["close"].shift(1)
    rolling_group = df.groupby("code", sort=False)["prev_close"]
    for n in WINDOWS:
        prior_high = rolling_group.rolling(n, min_periods=n).max().reset_index(level=0, drop=True)
        prior_low = rolling_group.rolling(n, min_periods=n).min().reset_index(level=0, drop=True)
        df[f"new_high_{n}"] = df["close"] > prior_high
        df[f"new_low_{n}"] = df["close"] < prior_low

    daily = df.groupby("date").agg(
        up=("change", lambda s: int((s > 0).sum())),
        down=("change", lambda s: int((s < 0).sum())),
        flat=("change", lambda s: int((s == 0).sum())),
        turnover=("turnover", "sum"),
        **{f"new_high_{n}": (f"new_high_{n}", "sum") for n in WINDOWS},
        **{f"new_low_{n}": (f"new_low_{n}", "sum") for n in WINDOWS},
    ).reset_index().sort_values("date")
    daily["ad_ratio"] = daily["up"] / daily["down"].where(daily["down"] > 0)
    # 騰落線（ADL）：每天「上漲家數 − 下跌家數」的累計；起點是資料期間第一天，只看趨勢不看絕對數字
    daily["adl"] = (daily["up"] - daily["down"]).cumsum()
    # 當天成交值 ÷ 前 20 個交易日平均（不含當天），>1 代表比近期熱絡
    daily["turnover_ma20_ratio"] = daily["turnover"] / daily["turnover"].shift(1).rolling(20, min_periods=20).mean()
    # 歷史剛開始的前 N 天，大部分股票還算不出 N 日新高，數字會嚴重偏低，直接標成缺值
    first_valid = {n: daily["date"].iloc[n] if len(daily) > n else None for n in WINDOWS}
    for n in WINDOWS:
        mask = daily["date"] < first_valid[n] if first_valid[n] else pd.Series(True, index=daily.index)
        daily.loc[mask, [f"new_high_{n}", f"new_low_{n}"]] = None
    return daily[columns].reset_index(drop=True)


def breadth_until(date: str | None = None, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> pd.DataFrame:
    from datetime import date as _date, timedelta

    end = _date.fromisoformat(date) if date else _date.today()
    history = load_price_history((end - timedelta(days=lookback_days)).isoformat())
    if not history.empty:
        history = history[history["date"] <= end.isoformat()]
    return compute_breadth(history)


def _num(value, fmt="{:,.0f}") -> str:
    return "無資料" if value is None or pd.isna(value) else fmt.format(value)


def summarize_for_prompt(breadth: pd.DataFrame) -> str:
    if breadth.empty:
        return "（無市場溫度計資料）"
    last = breadth.iloc[-1]
    lines = [
        f"資料日 {last['date']}：上漲 {int(last['up'])}／下跌 {int(last['down'])} 家，漲跌家數比 {_num(last['ad_ratio'], '{:.2f}')}",
        f"收盤創 20 日新高 {_num(last['new_high_20'])} 家、創 20 日新低 {_num(last['new_low_20'])} 家；"
        f"創 60 日新高 {_num(last['new_high_60'])} 家、創 60 日新低 {_num(last['new_low_60'])} 家",
        f"上市個股成交值為前 20 日平均的 {_num(last['turnover_ma20_ratio'], '{:.2f}')} 倍",
    ]
    recent = breadth.tail(5)
    if len(recent) >= 2:
        trend = "、".join(
            f"{r['date'][5:]} 新高{_num(r['new_high_20'])}/新低{_num(r['new_low_20'])}" for _, r in recent.iterrows())
        lines.append(f"近 5 日 20 日新高／新低家數：{trend}")
    return "\n".join(lines)
