"""個股 K 線圖：即時向 FinMind 補抓近期歷史繪製蠟燭圖 + 均線 + 成交量。

我們自己資料庫是每天收集才累積一筆，剛起步時歷史很短，
所以看個股詳情時改用 FinMind 現抓一段歷史來畫圖。

注意：均線要算得準，抓取的資料必須比「畫出來的天數」更長
（例如要畫近90天又要有 MA60，就得抓約150個日曆天再把前面的裁掉），
否則畫面左側的均線會因為前面沒有足夠資料而斷掉或算錯。
"""

from datetime import date as _date, timedelta

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src import price_levels, ui
from src.collectors import finmind
from src.indicators import RECOMMENDED_HISTORY_DAYS, add_indicators, to_dataframe

_UP_COLOR = ui.UP_COLOR  # 台股慣例：紅漲綠跌
_DOWN_COLOR = ui.DOWN_COLOR
_MA_LINES = [("MA5", "#F5B942"), ("MA20", "#4C8DF6"), ("MA60", "#A78BFA")]


def build_candlestick(code: str, name: str, days: int = 90) -> go.Figure | None:
    """畫出 K 線 + 均線 + 成交量副圖。days 是「顯示」的天數，
    實際抓取會多抓一段以便算出 MA60。"""
    # 顯示區間之外還要再往前多抓一段，MA60 才不會在畫面左側缺一大截
    # （要顯示 N 個交易日的 MA60，需要 N+59 個交易日的資料）
    end_date = _date.today().isoformat()
    fetch_start = (_date.today() - timedelta(days=days + RECOMMENDED_HISTORY_DAYS)).isoformat()

    rows = finmind.fetch_stock_price(code, fetch_start, end_date)
    if not rows:
        return None

    df = add_indicators(to_dataframe(rows))

    # 均線算完之後才裁切成要顯示的區間，這樣畫面左側的均線也是正確的
    display_start = (_date.today() - timedelta(days=days)).isoformat()
    display_df = df[df["date"] >= display_start]
    if display_df.empty:
        display_df = df

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.74, 0.26],
    )

    fig.add_trace(
        go.Candlestick(
            x=display_df["date"],
            open=display_df["open"],
            high=display_df["max"],
            low=display_df["min"],
            close=display_df["close"],
            increasing_line_color=_UP_COLOR,
            increasing_fillcolor=_UP_COLOR,
            decreasing_line_color=_DOWN_COLOR,
            decreasing_fillcolor=_DOWN_COLOR,
            name="K線",
        ),
        row=1,
        col=1,
    )

    for column, color in _MA_LINES:
        fig.add_trace(
            go.Scatter(
                x=display_df["date"],
                y=display_df[column],
                mode="lines",
                line={"width": 1.2, "color": color},
                name=column,
            ),
            row=1,
            col=1,
        )

    volume_colors = [
        _UP_COLOR if close >= open_ else _DOWN_COLOR
        for close, open_ in zip(display_df["close"], display_df["open"])
    ]
    fig.add_trace(
        go.Bar(
            x=display_df["date"],
            y=display_df["Trading_Volume"],
            marker_color=volume_colors,
            name="成交量",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    _add_price_levels(fig, rows, display_df)

    # 標題由頁面上的區塊標題負責，圖內不再放標題——圖內標題會跟上方圖例擠在同一行黏在一起
    ui.style_chart(fig, height=560)
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.03, "x": 0, "font": {"size": 12}},
    )
    # 休市日（週末、假日）不留空白，K 棒才會連續
    fig.update_xaxes(type="category", nticks=10, row=1, col=1)
    fig.update_xaxes(type="category", nticks=10, row=2, col=1)
    fig.update_yaxes(title_text="價格", title_font={"size": 11}, row=1, col=1)
    fig.update_yaxes(title_text="成交量(股)", title_font={"size": 11}, row=2, col=1)
    return fig


def _add_price_levels(fig: go.Figure, rows: list[dict], display_df) -> None:
    """在 K 線圖上標出最近的支撐壓力（虛線）、成交量最密集價位（點線），並在右側疊一層半透明的價量分布"""
    history = price_levels.from_finmind(rows)
    if history.empty:
        return
    low, high = float(display_df["min"].min()), float(display_df["max"].max())
    visible = (low * 0.97, high * 1.03)  # 太遠的價位不畫，免得把 K 線壓扁

    levels = price_levels.support_resistance(history.tail(120), max_levels=2)
    for items, color, label in ((levels["supports"], _DOWN_COLOR, "支撐"), (levels["resistances"], _UP_COLOR, "壓力")):
        for level in items:
            if visible[0] <= level["price"] <= visible[1]:
                fig.add_hline(y=level["price"], line={"color": color, "width": 1, "dash": "dash"}, opacity=0.8,
                              annotation_text=f"{label} {level['price']:,.2f}", annotation_position="top left",
                              annotation_font={"size": 11, "color": color}, row=1, col=1)

    profile = price_levels.volume_profile(history.tail(60))
    if not profile:
        return
    if visible[0] <= profile["poc"] <= visible[1]:
        fig.add_hline(y=profile["poc"], line={"color": "#F5B942", "width": 1, "dash": "dot"}, opacity=0.8,
                      annotation_text=f"量密集 {profile['poc']:,.2f}", annotation_position="bottom left",
                      annotation_font={"size": 11, "color": "#F5B942"}, row=1, col=1)
    bins = profile["bins"]
    fig.add_trace(go.Bar(
        x=bins["volume"], y=bins["price_mid"], orientation="h", xaxis="x3", yaxis="y",
        width=float(bins["price_high"].iloc[0] - bins["price_low"].iloc[0]) * 0.9,
        marker={"color": "rgba(135, 146, 166, 0.18)"}, name="近 60 日價量分布", hoverinfo="skip", showlegend=False,
    ))
    # 價量分布用獨立的 x 軸，範圍反過來讓長條從右邊往左長，最多佔圖寬約四分之一
    fig.update_layout(xaxis3={"overlaying": "x", "anchor": "y", "side": "top", "visible": False,
                              "range": [float(bins["volume"].max()) * 4, 0]})
