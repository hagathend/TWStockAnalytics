"""個股 K 線圖：即時向 FinMind 補抓近期歷史繪製蠟燭圖。

我們自己資料庫是每天收集才累積一筆，剛起步時歷史很短，
所以看個股詳情時改用 FinMind 現抓一段歷史（預設 90 天）來畫圖。
"""

from datetime import date as _date, timedelta

import pandas as pd
import plotly.graph_objects as go

from src.collectors import finmind


def build_candlestick(code: str, name: str, days: int = 90) -> go.Figure | None:
    end_date = _date.today().isoformat()
    start_date = (_date.today() - timedelta(days=days)).isoformat()

    rows = finmind.fetch_stock_price(code, start_date, end_date)
    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date")

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["max"],
                low=df["min"],
                close=df["close"],
                increasing_line_color="red",
                decreasing_line_color="green",
                name=code,
            )
        ]
    )
    fig.update_layout(
        title=f"{code} {name} 近 {days} 天走勢（資料來源: FinMind）",
        xaxis_title="日期",
        yaxis_title="價格",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=450,
    )
    return fig
