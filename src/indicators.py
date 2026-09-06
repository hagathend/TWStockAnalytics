"""技術指標計算：從 OHLCV 資料算出均線、RSI、MACD、KD、布林通道、量能。

純數學計算（pandas），不經過 AI，結果是確定的、可重現的。
算好的指標用在兩個地方：
1. `src/charting.py` 的 K 線圖疊圖（均線、成交量）
2. `src/stock_analysis.py` 的個股分析提示詞（把數值整理成文字餵給 AI，
   讓它有算好的指標可以判讀，而不是自己瞪著原始價格數字猜）

指標參數採台股常用慣例：MA5/20/60、RSI(14)、MACD(12,26,9)、KD(9,3,3)、布林(20,2)。
"""

import pandas as pd

# 要算出 MA60 至少需要 60 個交易日，抓 150 個日曆天大約有 100 個交易日，足夠
RECOMMENDED_HISTORY_DAYS = 150


def to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """把 FinMind 的價量資料轉成依日期排序的 DataFrame。
    FinMind 欄位: date, open, max(最高), min(最低), close, Trading_Volume"""
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在 DataFrame 上補齊各項技術指標欄位（資料筆數不足的前幾筆會是 NaN，屬正常）"""
    if df.empty:
        return df

    df = df.copy()
    close = df["close"]

    # 移動平均線
    df["MA5"] = close.rolling(5).mean()
    df["MA20"] = close.rolling(20).mean()
    df["MA60"] = close.rolling(60).mean()

    # 布林通道（20日、2倍標準差，用母體標準差 ddof=0，與多數看盤軟體一致）
    std20 = close.rolling(20).std(ddof=0)
    df["BB_UPPER"] = df["MA20"] + 2 * std20
    df["BB_LOWER"] = df["MA20"] - 2 * std20

    # RSI(14)，用 Wilder 平滑（等同 alpha=1/14 的指數移動平均）
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    # avg_loss 為 0 時相除得到 inf，RSI 自然會是 100（連續上漲），不用特別處理
    rs = avg_gain / avg_loss
    df["RSI14"] = 100 - 100 / (1 + rs)

    # MACD(12,26,9)：台股習慣稱 DIF(快線)、MACD/DEA(慢線)、OSC(柱狀體)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["OSC"] = df["DIF"] - df["DEA"]

    # KD(9,3,3)：台股慣例，K、D 初始值皆為 50，逐筆遞推
    low9 = df["min"].rolling(9).min()
    high9 = df["max"].rolling(9).max()
    span = (high9 - low9).replace(0, pd.NA)  # 高低相同時 RSV 無意義，留給下面沿用前值
    rsv = (close - low9) / span * 100

    k_values: list[float | None] = []
    d_values: list[float | None] = []
    k = d = 50.0
    for value in rsv:
        if pd.notna(value):
            k = k * 2 / 3 + float(value) / 3
            d = d * 2 / 3 + k / 3
            k_values.append(k)
            d_values.append(d)
        else:
            k_values.append(None)
            d_values.append(None)
    df["K"] = k_values
    df["D"] = d_values

    # 量能
    df["VOL_MA5"] = df["Trading_Volume"].rolling(5).mean()
    df["VOL_MA20"] = df["Trading_Volume"].rolling(20).mean()

    return df


def _fmt(value, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "資料不足"
    return f"{value:,.{digits}f}"


def _position_vs_ma(close: float, ma_value) -> str:
    if ma_value is None or pd.isna(ma_value):
        return "資料不足"
    diff_pct = (close - ma_value) / ma_value * 100
    side = "站上" if close >= ma_value else "跌破"
    return f"{side}（{diff_pct:+.1f}%）"


def summarize_for_prompt(df: pd.DataFrame) -> str:
    """把最新一筆的技術指標整理成給 AI 判讀的文字區塊。
    只陳述算出來的數值與客觀狀態，不做多空結論（結論留給 AI 判斷）。"""
    if df.empty or len(df) < 2:
        return "（歷史資料不足，無法計算技術指標）"

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last["close"])

    lines = [
        f"最新收盤價: {_fmt(close)}（{last['date']}）",
        f"MA5: {_fmt(last['MA5'])}｜MA20: {_fmt(last['MA20'])}｜MA60: {_fmt(last['MA60'])}",
        f"股價相對均線: MA5 {_position_vs_ma(close, last['MA5'])}、"
        f"MA20 {_position_vs_ma(close, last['MA20'])}、MA60 {_position_vs_ma(close, last['MA60'])}",
        f"RSI(14): {_fmt(last['RSI14'], 1)}",
        f"KD(9,3,3): K={_fmt(last['K'], 1)}、D={_fmt(last['D'], 1)}"
        f"（前一日 K={_fmt(prev['K'], 1)}、D={_fmt(prev['D'], 1)}）",
        f"MACD(12,26,9): DIF={_fmt(last['DIF'])}、MACD={_fmt(last['DEA'])}、"
        f"柱狀體OSC={_fmt(last['OSC'])}（前一日 OSC={_fmt(prev['OSC'])}）",
        f"布林通道(20,2): 上軌 {_fmt(last['BB_UPPER'])}｜中軌 {_fmt(last['MA20'])}｜下軌 {_fmt(last['BB_LOWER'])}",
    ]

    volume = last.get("Trading_Volume")
    vol_ma5 = last.get("VOL_MA5")
    if pd.notna(volume) and pd.notna(vol_ma5) and vol_ma5:
        ratio = float(volume) / float(vol_ma5)
        lines.append(
            f"成交量: {int(volume):,} 股，為5日均量的 {ratio:.2f} 倍"
            f"（5日均量 {int(vol_ma5):,}、20日均量 {_fmt(last['VOL_MA20'], 0)}）"
        )

    window20 = df.tail(20)
    window60 = df.tail(60)
    lines.append(
        f"近20日區間: 最高 {_fmt(window20['max'].max())}、最低 {_fmt(window20['min'].min())}"
    )
    lines.append(
        f"近60日區間: 最高 {_fmt(window60['max'].max())}、最低 {_fmt(window60['min'].min())}"
        f"（實際天數 {len(window60)} 筆）"
    )

    return "\n".join(lines)
