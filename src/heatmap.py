"""產業熱力圖：每檔股票一個方塊，依產業分組；方塊大小＝成交值、顏色＝漲跌幅（紅漲綠跌）。

產業別取自月營收彙總表的「產業別」（上市上櫃都有，不需要另外的資料來源）。
只畫個股（排除 ETF、權證）；查不到產業別的股票歸到「未分類」。
"""

import pandas as pd
import plotly.graph_objects as go

from src import ui
from src.storage import db

COLOR_CAP_PCT = 7.0  # 漲跌超過 ±7% 顏色就飽和（台股漲跌停 10%，大多數日子不會到）
UNCLASSIFIED = "未分類"

# 上市上櫃同一類別用詞不同，合併成同一個方塊
_INDUSTRY_ALIASES = {"金融業": "金融保險業"}

MARKET_OPTIONS = {"上市": ("TWSE",), "上櫃": ("TPEx",), "全部": ("TWSE", "TPEx")}


def industry_frame(date: str, markets=("TWSE",)) -> pd.DataFrame:
    """某天各股的產業、漲跌幅、成交值"""
    rows = [r for r in db.query_stock_price(date) if r["market"] in markets and db.is_stock_code(r["code"])]
    if not rows:
        return pd.DataFrame(columns=["code", "name", "market", "industry", "close", "change_pct", "turnover"])
    industries = db.query_industry_map()
    df = pd.DataFrame(rows)
    for column in ("close", "change", "turnover"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    previous = df["close"] - df["change"]
    df["change_pct"] = (df["change"] / previous.where(previous > 0)) * 100
    df["industry"] = df["code"].map(industries).fillna(UNCLASSIFIED).replace(_INDUSTRY_ALIASES)
    df = df[df["turnover"].fillna(0) > 0]  # 沒有成交的股票畫不出面積
    return df[["code", "name", "market", "industry", "close", "change_pct", "turnover"]].reset_index(drop=True)


def industry_summary(df: pd.DataFrame) -> pd.DataFrame:
    """產業彙總：家數、等權平均漲跌、成交值加權漲跌、上漲家數比例、成交值占比（依加權漲跌排序）"""
    if df.empty:
        return pd.DataFrame(columns=["industry", "count", "avg_change", "weighted_change", "up_ratio", "turnover_share"])
    total_turnover = df["turnover"].sum()
    rows = []
    for industry, group in df.groupby("industry"):
        valid = group.dropna(subset=["change_pct"])
        weight = valid["turnover"].sum()
        rows.append({
            "industry": industry,
            "count": len(group),
            "avg_change": valid["change_pct"].mean() if len(valid) else None,
            "weighted_change": (valid["change_pct"] * valid["turnover"]).sum() / weight if weight else None,
            "up_ratio": (valid["change_pct"] > 0).mean() * 100 if len(valid) else None,
            "turnover_share": group["turnover"].sum() / total_turnover * 100 if total_turnover else None,
        })
    return pd.DataFrame(rows).sort_values("weighted_change", ascending=False, na_position="last").reset_index(drop=True)


def _color_value(pct) -> float:
    if pct is None or pd.isna(pct):
        return 0.0
    return max(-COLOR_CAP_PCT, min(COLOR_CAP_PCT, float(pct)))


def build_treemap(df: pd.DataFrame, summary: pd.DataFrame) -> go.Figure:
    weighted = summary.set_index("industry")["weighted_change"].to_dict()
    ids, labels, parents, values, colors, texts, hovers = [], [], [], [], [], [], []
    for industry, group in df.groupby("industry"):
        change = weighted.get(industry)
        ids.append(f"ind:{industry}")
        labels.append(industry)
        parents.append("")
        values.append(float(group["turnover"].sum()))
        colors.append(_color_value(change))
        texts.append("" if change is None or pd.isna(change) else f"{change:+.2f}%")
        hovers.append(f"{industry}<br>成交值加權漲跌 {texts[-1] or '-'}<br>{len(group)} 檔")
        for row in group.itertuples():
            pct = "-" if pd.isna(row.change_pct) else f"{row.change_pct:+.2f}%"
            ids.append(f"stk:{row.code}")
            labels.append(f"{row.name}")
            parents.append(f"ind:{industry}")
            values.append(float(row.turnover))
            colors.append(_color_value(row.change_pct))
            texts.append(pct)
            hovers.append(f"{row.code} {row.name}<br>收盤 {row.close:,.2f}　{pct}<br>成交值 {row.turnover / 1e8:,.2f} 億")

    colorscale = [[0.0, ui.DOWN_COLOR], [0.5, "#2A3140"], [1.0, ui.UP_COLOR]]
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        text=texts, texttemplate="<b>%{label}</b><br>%{text}", hovertext=hovers, hoverinfo="text",
        # 固定白字：plotly 自動配色在紅色方塊上會選淡粉紅，幾乎看不清楚
        textfont={"color": "#F2F4F8"}, outsidetextfont={"color": "#C9D1DE"},
        marker={"colors": colors, "colorscale": colorscale, "cmin": -COLOR_CAP_PCT, "cmax": COLOR_CAP_PCT,
                "line": {"width": 1, "color": ui.CHART_BG}, "pad": {"t": 22, "l": 2, "r": 2, "b": 2}},
        pathbar={"visible": True, "textfont": {"size": 12}},
        tiling={"packing": "squarify"},
        maxdepth=2,
    ))
    ui.style_chart(fig, height=640)
    fig.update_layout(margin={"l": 4, "r": 4, "t": 28, "b": 4}, uniformtext={"minsize": 10, "mode": "hide"})
    return fig
