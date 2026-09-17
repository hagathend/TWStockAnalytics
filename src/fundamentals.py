"""基本面整理：把本益比／殖利率／淨值比與月營收合併成選股器可用的表，並產生提示詞文字。

跟籌碼、技術指標一樣只陳述數值，不下「便宜／昂貴」的結論——本益比高低要看產業與成長性，
交給 AI 或使用者判讀。
"""

import pandas as pd

from src.storage import db

FUNDAMENTAL_COLUMNS = ["pe_ratio", "dividend_yield", "pb_ratio", "year_month", "revenue",
                       "mom_pct", "yoy_pct", "cum_yoy_pct"]


def latest_fundamentals(as_of: str | None = None) -> pd.DataFrame:
    """每檔股票一列：最新本益比資料 + 最新月營收，以 code 為鍵"""
    valuation = pd.DataFrame(db.query_latest_valuation(as_of))
    revenue = pd.DataFrame(db.query_latest_month_revenue())
    frames = []
    if not valuation.empty:
        frames.append(valuation[["code", "pe_ratio", "dividend_yield", "pb_ratio"]].drop_duplicates("code"))
    if not revenue.empty:
        frames.append(revenue[["code", "year_month", "revenue", "mom_pct", "yoy_pct", "cum_yoy_pct"]]
                      .drop_duplicates("code"))
    if not frames:
        return pd.DataFrame(columns=["code", *FUNDAMENTAL_COLUMNS])
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="code", how="outer")
    for column in FUNDAMENTAL_COLUMNS:
        if column not in merged.columns:
            merged[column] = None
    for column in ("pe_ratio", "dividend_yield", "pb_ratio", "revenue", "mom_pct", "yoy_pct", "cum_yoy_pct"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged


def attach_fundamentals(df: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.merge(fundamentals, on="code", how="left")


def apply_filters(df: pd.DataFrame, pe_max=None, yield_min=None, pb_max=None, yoy_min=None) -> pd.DataFrame:
    """數值篩選。有設條件時，缺資料的股票（例如虧損無本益比、尚未公布營收）視為不符合。"""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    if pe_max is not None:
        mask &= df["pe_ratio"].notna() & (df["pe_ratio"] <= pe_max)
    if yield_min is not None:
        mask &= df["dividend_yield"].notna() & (df["dividend_yield"] >= yield_min)
    if pb_max is not None:
        mask &= df["pb_ratio"].notna() & (df["pb_ratio"] <= pb_max)
    if yoy_min is not None:
        mask &= df["yoy_pct"].notna() & (df["yoy_pct"] >= yoy_min)
    return df[mask].reset_index(drop=True)


def _num(value, fmt: str, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "無資料"
    return f"{value:{fmt}}{suffix}"


def summarize_for_prompt(code: str) -> str:
    data = db.query_code_fundamentals(code)
    valuation, revenue = data["valuation"], data["revenue"]
    lines = []
    if valuation:
        pe_note = "（無資料通常代表近四季虧損）" if valuation["pe_ratio"] is None else ""
        lines.append(
            f"本益比 {_num(valuation['pe_ratio'], '.2f')}{pe_note}、"
            f"殖利率 {_num(valuation['dividend_yield'], '.2f', '%')}、"
            f"股價淨值比 {_num(valuation['pb_ratio'], '.2f')}（{valuation['date']}）"
        )
    else:
        lines.append("本益比／殖利率／淨值比: 無資料")
    if revenue:
        for r in revenue[:6]:
            lines.append(
                f"{r['year_month']} 營收 {_num(r['revenue'] / 1000 if r['revenue'] else None, ',.0f', ' 百萬元')}，"
                f"月增 {_num(r['mom_pct'], '+.1f', '%')}、年增 {_num(r['yoy_pct'], '+.1f', '%')}、"
                f"累計年增 {_num(r['cum_yoy_pct'], '+.1f', '%')}"
            )
        from src.revenue import summarize_for_prompt as summarize_revenue  # 避免循環匯入

        revenue_note = summarize_revenue(code)
        if revenue_note:
            lines.append(f"營收趨勢：{revenue_note}")
    else:
        lines.append("月營收: 無資料")
    from src.financials import summarize_for_prompt as summarize_quarterly
    from src.pe_river import summarize_for_prompt as summarize_river

    river_note = summarize_river(code)
    if river_note:
        lines.append(river_note)

    quarterly = summarize_quarterly(code)
    lines.append("季度財報（毛利率、營益率為單季；金融業無毛利率）：\n" + quarterly if quarterly else "季度財報: 無資料")
    return "\n".join(lines)
