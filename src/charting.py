"""個股 K 線圖：向 FinMind 抓歷史日線，畫日 K／週 K／月 K、均線、成交量，可以再加 KD、MACD、RSI 副圖。

我們自己資料庫是每天收集才累積一筆，剛起步時歷史很短，所以看個股詳情時改用 FinMind 現抓一段歷史來畫圖。

- 週 K、月 K 由日線合併：開盤取第一天、最高最低取區間極值、收盤取最後一天、成交量加總，
  日期標示為該週／該月最後一個交易日
- 均線依週期換：日 K 5／20／60 日、週 K 5／10／20 週、月 K 6／12／24 月
- 均線與指標要算得準，抓取的資料必須比「畫出來的期間」更長，多抓的部分算完再裁掉，
  否則畫面左側的均線會因為前面沒有足夠資料而斷掉或算錯
"""

from datetime import date as _date, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src import price_levels, ui
from src.collectors import finmind
from src.indicators import add_indicators

_UP_COLOR = ui.UP_COLOR  # 台股慣例：紅漲綠跌
_DOWN_COLOR = ui.DOWN_COLOR
_MA_COLORS = ("#F5B942", "#4C8DF6", "#A78BFA")

# 週期設定：ranges 是可選的顯示期間（日曆天）、bar_days 是一根 K 棒約幾個日曆天（估算要多抓多少歷史用）
PERIODS = {
    "日K": {"freq": None, "unit": "日", "ma": (5, 20, 60), "bar_days": 1.5, "levels_bars": 120, "profile_bars": 60,
            "ranges": {"3 個月": 90, "6 個月": 180, "1 年": 365}, "default": "3 個月"},
    "週K": {"freq": "W-FRI", "unit": "週", "ma": (5, 10, 20), "bar_days": 7, "levels_bars": 104, "profile_bars": 52,
            "ranges": {"1 年": 365, "2 年": 730, "3 年": 1095}, "default": "1 年"},
    "月K": {"freq": "M", "unit": "月", "ma": (6, 12, 24), "bar_days": 31, "levels_bars": 120, "profile_bars": 60,
            "ranges": {"3 年": 1095, "5 年": 1825, "10 年": 3650}, "default": "5 年"},
}
INDICATORS = ("KD", "MACD", "RSI")
_WARMUP_BARS = 35  # MACD 需要約 26+9 根才穩定


def fetch_days(period: str, range_label: str) -> int:
    """畫這個週期與期間，需要向 FinMind 抓幾個日曆天（含算均線與指標的暖身期）"""
    spec = PERIODS[period]
    warmup_bars = max(spec["ma"]) + _WARMUP_BARS
    return spec["ranges"][range_label] + int(warmup_bars * spec["bar_days"]) + 10


def fetch_rows(code: str, days: int, today: _date | None = None) -> list[dict]:
    today = today or _date.today()
    return finmind.fetch_stock_price(code, (today - timedelta(days=days)).isoformat(), today.isoformat())


def to_bars(rows: list[dict], period: str) -> pd.DataFrame:
    """FinMind 日線 → 指定週期的 K 棒（欄位沿用 FinMind：date, open, max, min, close, Trading_Volume）"""
    if not rows:
        return pd.DataFrame(columns=["date", "open", "max", "min", "close", "Trading_Volume"])
    df = pd.DataFrame(rows)[["date", "open", "max", "min", "close", "Trading_Volume"]].sort_values("date")
    for column in ("open", "max", "min", "close", "Trading_Volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    freq = PERIODS[period]["freq"]
    if not freq:
        return df.reset_index(drop=True)
    key = pd.to_datetime(df["date"]).dt.to_period(freq)
    bars = df.groupby(key, sort=True).agg(date=("date", "last"), open=("open", "first"), max=("max", "max"),
                                          min=("min", "min"), close=("close", "last"),
                                          Trading_Volume=("Trading_Volume", "sum"))
    return bars.reset_index(drop=True)


def prepare(rows: list[dict], period: str, range_label: str, today: _date | None = None) -> pd.DataFrame:
    """算好均線與指標、裁成要顯示的期間"""
    spec = PERIODS[period]
    df = add_indicators(to_bars(rows, period))
    if df.empty:
        return df
    for n in spec["ma"]:
        df[f"MA_{n}"] = df["close"].rolling(n).mean()
    today = today or _date.today()
    start = (today - timedelta(days=spec["ranges"][range_label])).isoformat()
    shown = df[df["date"] >= start]
    return (shown if not shown.empty else df).reset_index(drop=True)


def build_candlestick(code: str, name: str, period: str = "日K", range_label: str | None = None,
                      indicators=(), rows: list[dict] | None = None) -> go.Figure | None:
    """K 線 + 均線 + 成交量，另外依 indicators 加 KD／MACD／RSI 副圖。rows 沒給就向 FinMind 抓"""
    spec = PERIODS[period]
    range_label = range_label or spec["default"]
    if rows is None:
        rows = fetch_rows(code, fetch_days(period, range_label))
    if not rows:
        return None
    display_df = prepare(rows, period, range_label)
    if display_df.empty:
        return None
    indicators = [i for i in INDICATORS if i in indicators]

    panel_rows = 2 + len(indicators)
    heights = [0.58, 0.14] + [0.14] * len(indicators) if indicators else [0.74, 0.26]
    fig = make_subplots(rows=panel_rows, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=heights)

    fig.add_trace(go.Candlestick(
        x=display_df["date"], open=display_df["open"], high=display_df["max"], low=display_df["min"],
        close=display_df["close"], increasing_line_color=_UP_COLOR, increasing_fillcolor=_UP_COLOR,
        decreasing_line_color=_DOWN_COLOR, decreasing_fillcolor=_DOWN_COLOR, name=period,
    ), row=1, col=1)
    for n, color in zip(spec["ma"], _MA_COLORS):
        fig.add_trace(go.Scatter(x=display_df["date"], y=display_df[f"MA_{n}"], mode="lines",
                                 line={"width": 1.2, "color": color}, name=f"MA{n}{spec['unit']}"), row=1, col=1)

    volume_colors = [_UP_COLOR if c >= o else _DOWN_COLOR for c, o in zip(display_df["close"], display_df["open"])]
    fig.add_trace(go.Bar(x=display_df["date"], y=display_df["Trading_Volume"], marker_color=volume_colors,
                         name="成交量", showlegend=False), row=2, col=1)
    fig.update_yaxes(title_text="成交量", title_font={"size": 11}, row=2, col=1)

    for offset, indicator in enumerate(indicators, start=3):
        _add_indicator(fig, display_df, indicator, offset)

    _add_price_levels(fig, to_bars(rows, period), display_df, spec)

    # 標題由頁面上的區塊標題負責，圖內不再放標題——圖內標題會跟上方圖例擠在同一行黏在一起
    ui.style_chart(fig, height=560 + 150 * len(indicators))
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"size": 12}},
    )
    # 休市日（週末、假日）不留空白，K 棒才會連續
    for row in range(1, panel_rows + 1):
        fig.update_xaxes(type="category", nticks=10, row=row, col=1)
    fig.update_yaxes(title_text="價格", title_font={"size": 11}, row=1, col=1)
    return fig


def _add_indicator(fig: go.Figure, df: pd.DataFrame, indicator: str, row: int) -> None:
    x = df["date"]
    if indicator == "KD":
        fig.add_trace(go.Scatter(x=x, y=df["K"], mode="lines", name="K", line={"width": 1.3, "color": "#F5B942"}), row=row, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["D"], mode="lines", name="D", line={"width": 1.3, "color": "#4C8DF6"}), row=row, col=1)
        for level in (20, 80):
            fig.add_hline(y=level, line={"color": "rgba(135, 146, 166, 0.5)", "width": 1, "dash": "dot"}, row=row, col=1)
        fig.update_yaxes(title_text="KD", title_font={"size": 11}, range=[0, 100], row=row, col=1)
    elif indicator == "MACD":
        colors = [_UP_COLOR if v >= 0 else _DOWN_COLOR for v in df["OSC"].fillna(0)]
        fig.add_trace(go.Bar(x=x, y=df["OSC"], marker_color=colors, name="OSC", showlegend=False), row=row, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["DIF"], mode="lines", name="DIF", line={"width": 1.3, "color": "#F5B942"}), row=row, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["DEA"], mode="lines", name="MACD", line={"width": 1.3, "color": "#4C8DF6"}), row=row, col=1)
        fig.update_yaxes(title_text="MACD", title_font={"size": 11}, row=row, col=1)
    elif indicator == "RSI":
        fig.add_trace(go.Scatter(x=x, y=df["RSI14"], mode="lines", name="RSI14", line={"width": 1.3, "color": "#A78BFA"}), row=row, col=1)
        for level in (30, 70):
            fig.add_hline(y=level, line={"color": "rgba(135, 146, 166, 0.5)", "width": 1, "dash": "dot"}, row=row, col=1)
        fig.update_yaxes(title_text="RSI", title_font={"size": 11}, range=[0, 100], row=row, col=1)


def _add_price_levels(fig: go.Figure, bars: pd.DataFrame, display_df: pd.DataFrame, spec: dict) -> None:
    """在 K 線圖上標出最近的支撐壓力（虛線）、成交量最密集價位（點線），並在右側疊一層半透明的價量分布。
    週 K、月 K 用那個週期的 K 棒算，看得到更長期的關卡"""
    history = bars.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    history = history[(history["high"] > 0) & (history["low"] > 0) & (history["close"] > 0)]
    if history.empty:
        return
    low, high = float(display_df["min"].min()), float(display_df["max"].max())
    visible = (low * 0.97, high * 1.03)  # 太遠的價位不畫，免得把 K 線壓扁

    levels = price_levels.support_resistance(history.tail(spec["levels_bars"]), max_levels=2)
    for items, color, label in ((levels["supports"], _DOWN_COLOR, "支撐"), (levels["resistances"], _UP_COLOR, "壓力")):
        for level in items:
            if visible[0] <= level["price"] <= visible[1]:
                fig.add_hline(y=level["price"], line={"color": color, "width": 1, "dash": "dash"}, opacity=0.8,
                              annotation_text=f"{label} {level['price']:,.2f}", annotation_position="top left",
                              annotation_font={"size": 11, "color": color}, row=1, col=1)

    profile = price_levels.volume_profile(history.tail(spec["profile_bars"]))
    if not profile:
        return
    if visible[0] <= profile["poc"] <= visible[1]:
        fig.add_hline(y=profile["poc"], line={"color": "#F5B942", "width": 1, "dash": "dot"}, opacity=0.8,
                      annotation_text=f"量密集 {profile['poc']:,.2f}", annotation_position="bottom left",
                      annotation_font={"size": 11, "color": "#F5B942"}, row=1, col=1)
    table = profile["bins"]
    fig.add_trace(go.Bar(
        x=table["volume"], y=table["price_mid"], orientation="h", xaxis="x99", yaxis="y",
        width=float(table["price_high"].iloc[0] - table["price_low"].iloc[0]) * 0.9,
        marker={"color": "rgba(135, 146, 166, 0.18)"}, name="價量分布", hoverinfo="skip", showlegend=False,
    ))
    # 價量分布用獨立的 x 軸，範圍反過來讓長條從右邊往左長，最多佔圖寬約四分之一
    fig.update_layout(xaxis99={"overlaying": "x", "anchor": "y", "side": "top", "visible": False,
                               "range": [float(table["volume"].max()) * 4, 0]})
