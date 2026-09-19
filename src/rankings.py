"""排行榜：某一天的漲跌幅、成交量、成交值、週轉率、法人買賣超、殖利率排行（只算個股，排除 ETF、權證）。

- 漲跌幅＝漲跌 ÷ 前一日收盤（前一日收盤＝收盤 − 漲跌）
- 週轉率＝成交股數 ÷ 發行股數，發行股數來自外資持股資料（只有上市股有），上櫃股沒有週轉率
- 法人買賣超以「張」顯示（原始資料是股）
- 殖利率取這一天或之前最新一筆估值資料
- 當沖比＝當沖成交股數 ÷ 成交股數；當沖比排行只列成交量 1000 張以上，避免冷門股幾張成交就 100%
"""

import pandas as pd

from src.storage import db

METRICS = {
    "漲幅": ("change_pct", False),
    "跌幅": ("change_pct", True),
    "成交量": ("volume_lots", False),
    "成交值": ("turnover_billion", False),
    "週轉率": ("turnover_rate", False),
    "外資買超": ("foreign_lots", False),
    "外資賣超": ("foreign_lots", True),
    "投信買超": ("trust_lots", False),
    "投信賣超": ("trust_lots", True),
    "殖利率": ("dividend_yield", False),
    "當沖比": ("day_trade_pct", False),
}
MARKETS = {"全部": ("TWSE", "TPEx"), "上市": ("TWSE",), "上櫃": ("TPEx",)}
MAX_YIELD = 40.0
MIN_DAY_TRADE_LOTS = 1000
COLUMNS = ["code", "name", "market", "close", "change_pct", "volume_lots", "turnover_billion", "turnover_rate",
           "foreign_lots", "trust_lots", "dividend_yield", "day_trade_pct"]


def daily_table(date: str) -> pd.DataFrame:
    """這一天所有個股的排行用欄位"""
    prices = [r for r in db.query_stock_price(date) if db.is_stock_code(r["code"])]
    if not prices:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(prices)
    for column in ("close", "change", "volume", "turnover"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df[df["close"] > 0]
    previous = df["close"] - df["change"]
    df["change_pct"] = (df["change"] / previous.where(previous > 0)) * 100
    df["volume_lots"] = df["volume"] / 1000
    df["turnover_billion"] = df["turnover"] / 1e8

    issued = pd.DataFrame(db.query_issued_shares(date), columns=["code", "issued_shares"])
    df = df.merge(issued, on="code", how="left")
    df["turnover_rate"] = df["volume"] / df["issued_shares"].where(df["issued_shares"] > 0) * 100

    inst = pd.DataFrame([r for r in db.query_institutional(date) if db.is_stock_code(r["code"])])
    if inst.empty:
        df["foreign_lots"] = df["trust_lots"] = None
    else:
        inst = inst.drop_duplicates("code")[["code", "foreign_net", "trust_net"]]
        df = df.merge(inst, on="code", how="left")
        df["foreign_lots"] = pd.to_numeric(df["foreign_net"], errors="coerce") / 1000
        df["trust_lots"] = pd.to_numeric(df["trust_net"], errors="coerce") / 1000

    valuation = pd.DataFrame(db.query_latest_valuation(date))
    if valuation.empty:
        df["dividend_yield"] = None
    else:
        df = df.merge(valuation[["code", "dividend_yield"]].drop_duplicates("code"), on="code", how="left")
    day_trade = pd.DataFrame(db.query_day_trading_ratio(date), columns=["code", "day_trade_pct"])
    df = df.merge(day_trade[["code", "day_trade_pct"]].drop_duplicates("code"), on="code", how="left")
    return df[COLUMNS].reset_index(drop=True)


def rank(table: pd.DataFrame, metric: str, market: str = "全部", limit: int = 50) -> pd.DataFrame:
    column, ascending = METRICS[metric]
    df = table[table["market"].isin(MARKETS[market])]
    values = pd.to_numeric(df[column], errors="coerce")
    df = df[values.notna()]
    if metric == "殖利率":
        # 來源偶爾有明顯錯誤的值（例如 100% 以上），排除 40% 以上避免排行被異常值佔滿
        df = df[(pd.to_numeric(df[column], errors="coerce") > 0) & (pd.to_numeric(df[column], errors="coerce") < MAX_YIELD)]
    elif metric in ("外資買超", "投信買超", "漲幅"):
        df = df[pd.to_numeric(df[column], errors="coerce") > 0]
    elif metric == "當沖比":
        df = df[pd.to_numeric(df["volume_lots"], errors="coerce") >= MIN_DAY_TRADE_LOTS]
    elif metric in ("外資賣超", "投信賣超", "跌幅"):
        df = df[pd.to_numeric(df[column], errors="coerce") < 0]
    return df.sort_values(column, ascending=ascending).head(limit).reset_index(drop=True)
