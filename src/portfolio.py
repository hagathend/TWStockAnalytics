"""我的持股：彙總每檔持股的成本與損益，並整理成給 AI 判讀的文字。

- 同一檔分批買進時，成本用「加權平均」：總成本 ÷ 總股數。
- 市價用本地資料庫最近一個交易日的收盤價（上市上櫃都查），並標示價格日期，
  避免把舊收盤價當成即時價。
- 損益未扣手續費與證交稅，UI 與提示詞都要說明。
- 提示詞只陳述成本、損益、持有天數等事實；進出場判斷交給 AI 以「條件式觀察點」呈現，
  最後由使用者自行決定。
"""

from datetime import date as _date

from src.storage import db

SHARES_PER_LOT = 1000


def lots_text(shares: int) -> str:
    """股數 → 「3 張」或「2 張 500 股」或「500 股」"""
    lots, odd = divmod(int(shares), SHARES_PER_LOT)
    if lots and odd:
        return f"{lots} 張 {odd} 股"
    if lots:
        return f"{lots} 張"
    return f"{odd} 股"


def _holding_days(first_buy: str | None, today: _date) -> int | None:
    if not first_buy:
        return None
    try:
        return (today - _date.fromisoformat(first_buy)).days
    except ValueError:
        return None


def summarize_position(records: list[dict], price: dict | None, today: _date | None = None) -> dict:
    """同一檔股票的多筆買進紀錄 → 一個持倉。records 需為同一個 code。"""
    today = today or _date.today()
    shares = sum(int(r["shares"]) for r in records)
    cost = sum(int(r["shares"]) * float(r["cost_price"]) for r in records)
    buy_dates = sorted(r["buy_date"] for r in records if r.get("buy_date"))
    position = {
        "code": records[0]["code"],
        "name": (price or {}).get("name") or records[0].get("name") or records[0]["code"],
        "records": len(records),
        "shares": shares,
        "cost": cost,
        "avg_cost": cost / shares if shares else None,
        "first_buy_date": buy_dates[0] if buy_dates else None,
        "holding_days": _holding_days(buy_dates[0] if buy_dates else None, today),
        "close": None,
        "price_date": None,
        "day_change": None,
        "market_value": None,
        "pnl": None,
        "pnl_pct": None,
    }
    if price and price.get("close") is not None and shares:
        close = float(price["close"])
        position.update({
            "close": close,
            "price_date": price["date"],
            "day_change": price.get("change"),
            "market_value": close * shares,
            "pnl": close * shares - cost,
            "pnl_pct": (close * shares / cost - 1) * 100 if cost else None,
        })
    return position


def load_positions(as_of: str | None = None) -> list[dict]:
    """所有持倉（依市值由大到小；沒有市價的排最後）"""
    grouped: dict[str, list[dict]] = {}
    for record in db.query_holdings():
        grouped.setdefault(record["code"], []).append(record)
    positions = [summarize_position(records, db.query_latest_close(code, as_of)) for code, records in grouped.items()]
    return sorted(positions, key=lambda p: (p["market_value"] is None, -(p["market_value"] or 0)))


def portfolio_totals(positions: list[dict]) -> dict:
    priced = [p for p in positions if p["market_value"] is not None]
    cost = sum(p["cost"] for p in priced)
    value = sum(p["market_value"] for p in priced)
    return {
        "positions": len(positions),
        "cost": sum(p["cost"] for p in positions),
        "market_value": value,
        "pnl": value - cost,
        "pnl_pct": (value / cost - 1) * 100 if cost else None,
        "unpriced": len(positions) - len(priced),
    }


def summarize_for_prompt(code: str) -> str | None:
    """個股分析提示詞用的持股區塊；沒有持有這檔就回傳 None（提示詞不放持股段落）"""
    records = db.query_holdings(code)
    if not records:
        return None
    total_value = portfolio_totals(load_positions())["market_value"]
    p = summarize_position(records, db.query_latest_close(code))
    lines = [f"持有 {lots_text(p['shares'])}，平均成本 {p['avg_cost']:,.2f} 元（共 {p['records']} 筆買進）"]
    if p["first_buy_date"]:
        lines.append(f"最早買進日 {p['first_buy_date']}，已持有 {p['holding_days']} 天")
    if p["close"] is not None:
        lines.append(
            f"最新收盤 {p['close']:,.2f} 元（{p['price_date']}），未實現損益 {p['pnl']:+,.0f} 元"
            f"（{p['pnl_pct']:+.2f}%，未扣手續費與證交稅）"
        )
        if total_value:
            lines.append(f"佔目前持股總市值 {p['market_value'] / total_value * 100:.1f}%")
    else:
        lines.append("本地資料庫查無最新收盤價，無法計算損益")
    if len(records) > 1:
        detail = "；".join(
            f"{r.get('buy_date') or '日期未填'} {lots_text(r['shares'])} @ {float(r['cost_price']):,.2f}"
            for r in records
        )
        lines.append(f"買進明細：{detail}")
    return "\n".join(lines)
