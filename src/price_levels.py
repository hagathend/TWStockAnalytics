"""支撐壓力與成交量密集區（Volume Profile），程式計算、給 K 線圖與 AI 提示詞共用。

支撐壓力：
1. 找轉折點：某天最高價是前後各 5 天的最高 → 轉折高點；最低價是前後各 5 天的最低 → 轉折低點
2. 價格相差 1.5% 以內的轉折點合併成一個價位（取平均），碰觸次數愈多愈重要
3. 低於目前收盤價的是支撐、高於的是壓力，各取距離最近的幾個

成交量密集區：把期間價格範圍切成 24 格，每天成交量依「典型價＝(高+低+收)/3」歸到對應價格格；
成交量最大的格＝POC（最多人成交的價位），涵蓋 70% 成交量的連續價格區間＝價值區（Value Area）。

輸入欄位用 date/high/low/close/volume；FinMind 的 max/min/Trading_Volume 由 from_finmind() 轉換。
"""

import pandas as pd

SWING_WINDOW = 5
MERGE_TOLERANCE = 0.015
PROFILE_BINS = 24
VALUE_AREA = 0.70


def from_finmind(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "high", "low", "close", "volume"])
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    for column in ("high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[["date", "high", "low", "close", "volume"]].dropna().sort_values("date").reset_index(drop=True)


def _swing_points(df: pd.DataFrame, window: int = SWING_WINDOW) -> list[tuple[float, str, str]]:
    """(價格, 日期, high|low)。最後 window 天還看不到「之後」的走勢，不算轉折。"""
    points = []
    highs, lows = df["high"].tolist(), df["low"].tolist()
    for i in range(window, len(df) - window):
        segment_high = highs[i - window:i + window + 1]
        segment_low = lows[i - window:i + window + 1]
        if highs[i] == max(segment_high) and segment_high.count(highs[i]) == 1:
            points.append((highs[i], df["date"].iloc[i], "high"))
        if lows[i] == min(segment_low) and segment_low.count(lows[i]) == 1:
            points.append((lows[i], df["date"].iloc[i], "low"))
    return points


def _cluster(points: list[tuple[float, str, str]], tolerance: float = MERGE_TOLERANCE) -> list[dict]:
    levels = []
    for price, day, _ in sorted(points):
        if levels and abs(price - levels[-1]["price"]) / levels[-1]["price"] <= tolerance:
            level = levels[-1]
            level["prices"].append(price)
            level["price"] = sum(level["prices"]) / len(level["prices"])
            level["last_date"] = max(level["last_date"], day)
        else:
            levels.append({"price": price, "prices": [price], "last_date": day})
    return [{"price": l["price"], "touches": len(l["prices"]), "last_date": l["last_date"]} for l in levels]


def support_resistance(df: pd.DataFrame, max_levels: int = 3) -> dict:
    """{"close", "supports": [...], "resistances": [...]}，各依距離目前收盤由近到遠"""
    if len(df) < SWING_WINDOW * 2 + 1:
        return {"close": None, "supports": [], "resistances": []}
    close = float(df["close"].iloc[-1])
    levels = _cluster(_swing_points(df))
    for level in levels:
        level["distance_pct"] = (level["price"] / close - 1) * 100
    supports = sorted([l for l in levels if l["price"] < close], key=lambda l: -l["price"])[:max_levels]
    resistances = sorted([l for l in levels if l["price"] > close], key=lambda l: l["price"])[:max_levels]
    return {"close": close, "supports": supports, "resistances": resistances}


def volume_profile(df: pd.DataFrame, bins: int = PROFILE_BINS) -> dict | None:
    """{"bins": DataFrame(price_low, price_high, price_mid, volume), "poc", "value_area_low", "value_area_high"}"""
    if df.empty or df["volume"].sum() <= 0:
        return None
    low, high = float(df["low"].min()), float(df["high"].max())
    if high <= low:
        return None
    step = (high - low) / bins
    typical = (df["high"] + df["low"] + df["close"]) / 3
    index = ((typical - low) / step).astype(int).clip(0, bins - 1)
    volumes = df["volume"].groupby(index).sum().reindex(range(bins), fill_value=0)
    table = pd.DataFrame({
        "price_low": [low + i * step for i in range(bins)],
        "price_high": [low + (i + 1) * step for i in range(bins)],
        "volume": volumes.values,
    })
    table["price_mid"] = (table["price_low"] + table["price_high"]) / 2
    poc_index = int(table["volume"].idxmax())

    # 從 POC 往兩側擴張，每次加入成交量較大的那一邊，直到涵蓋 70%
    total, covered = table["volume"].sum(), table["volume"].iloc[poc_index]
    lo_i = hi_i = poc_index
    while covered < total * VALUE_AREA and (lo_i > 0 or hi_i < bins - 1):
        below = table["volume"].iloc[lo_i - 1] if lo_i > 0 else -1
        above = table["volume"].iloc[hi_i + 1] if hi_i < bins - 1 else -1
        if above >= below:
            hi_i += 1
            covered += above
        else:
            lo_i -= 1
            covered += below
    return {"bins": table, "poc": float(table["price_mid"].iloc[poc_index]),
            "value_area_low": float(table["price_low"].iloc[lo_i]), "value_area_high": float(table["price_high"].iloc[hi_i])}


def summarize_for_prompt(df: pd.DataFrame, days: int = 120) -> str:
    recent = df.tail(days)
    levels = support_resistance(recent)
    if levels["close"] is None:
        return "（股價歷史不足，無法計算支撐壓力）"

    def describe(items):
        if not items:
            return "近期沒有明顯價位"
        return "、".join(f"{l['price']:,.2f}（距離 {l['distance_pct']:+.1f}%，碰觸 {l['touches']} 次）" for l in items)

    lines = [f"最新收盤 {levels['close']:,.2f}（近 {len(recent)} 個交易日的轉折點）",
             f"支撐：{describe(levels['supports'])}",
             f"壓力：{describe(levels['resistances'])}"]
    profile = volume_profile(df.tail(60))
    if profile:
        lines.append(f"近 60 日成交量最密集價位 {profile['poc']:,.2f}，70% 成交量集中在 "
                     f"{profile['value_area_low']:,.2f}～{profile['value_area_high']:,.2f}")
    return "\n".join(lines)
