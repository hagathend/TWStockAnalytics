"""盤中即時報價的整理：持股即時市值與損益、觀察名單報價表、是否為交易時間。

即時損益＝即時價 × 股數 − 持有成本（成本含買進手續費，未扣賣出稅費，與持倉明細同一算法）；
今日損益＝漲跌 × 股數（以昨收為基準，當天才買的部位會失真，僅供參考）。
"""

from datetime import datetime, time

import pandas as pd

TRADING_START, TRADING_END = time(9, 0), time(13, 30)

QUOTE_COLUMNS = ["code", "name", "price", "change", "change_pct", "open", "high", "low", "volume_lots", "time"]


def is_trading_time(now: datetime | None = None) -> bool:
    """週一到週五 9:00～13:30（不含國定假日判斷；假日查到的會是最後一個交易日的資料）"""
    now = now or datetime.now()
    return now.weekday() < 5 and TRADING_START <= now.time() <= TRADING_END


def quote_table(stocks: list[tuple[str, str]], quotes: dict[str, dict]) -> pd.DataFrame:
    """依 stocks 的順序排；查不到報價的也留一列（價格空白）"""
    rows = []
    for code, name in stocks:
        quote = quotes.get(code, {})
        rows.append({column: quote.get(column) for column in QUOTE_COLUMNS} | {"code": code, "name": name})
    return pd.DataFrame(rows, columns=QUOTE_COLUMNS)


def position_table(positions: list[dict], quotes: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for p in positions:
        quote = quotes.get(p["code"], {})
        price, shares, cost = quote.get("price"), p["shares"], p["cost"]
        value = price * shares if price is not None else None
        rows.append({
            "code": p["code"], "name": p["name"], "shares": shares, "avg_cost": p.get("avg_cost"),
            "price": price, "change": quote.get("change"), "change_pct": quote.get("change_pct"),
            "market_value": value, "pnl": value - cost if value is not None else None,
            "pnl_pct": (value / cost - 1) * 100 if value is not None and cost else None,
            "day_pnl": quote["change"] * shares if quote.get("change") is not None else None,
            "time": quote.get("time"),
        })
    return pd.DataFrame(rows, columns=["code", "name", "shares", "avg_cost", "price", "change", "change_pct",
                                       "market_value", "pnl", "pnl_pct", "day_pnl", "time"])


def latest_stamp(quotes: dict[str, dict]) -> str | None:
    stamps = [f"{q['date']} {q['time']}" for q in quotes.values() if q.get("date") and q.get("time")]
    return max(stamps) if stamps else None
