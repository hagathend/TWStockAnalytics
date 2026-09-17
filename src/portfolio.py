"""我的持股：由交易紀錄（trades）推算持倉、未實現與已實現損益，並整理成給 AI 判讀的文字。

計算方式（台灣券商對帳單常用的「平均成本法」）：
- 買進：持股成本 += 股數 × 成交價 + 手續費（手續費算進成本）
- 賣出：以賣出當下的平均成本計算已實現損益 = 股數 × 成交價 − 手續費 − 證交稅 − 平均成本 × 股數
- 賣到 0 股之後再買，視為新的一段持有（持有天數、買進明細重新起算）
交易必須依日期先後重播，同一天依輸入順序；賣超過持有股數視為資料錯誤，不硬算。

市價用本地資料庫最近一個交易日的收盤價，並標示價格日期；未實現損益未扣「將來賣出」的手續費與證交稅。
提示詞只陳述事實；進出場判斷交給 AI 以條件式觀察點呈現，決策留給使用者。
"""

import math
from datetime import date as _date

from src.storage import db

SHARES_PER_LOT = 1000
FEE_RATE = 0.001425
MIN_FEE_BOARD_LOT = 20   # 整股最低手續費（多數券商）
MIN_FEE_ODD_LOT = 1      # 零股最低手續費（多數券商）
STOCK_TAX_RATE = 0.003
ETF_TAX_RATE = 0.001


class TradeError(ValueError):
    """交易紀錄不合理（例如賣出股數超過當時持有）"""


def lots_text(shares: int) -> str:
    """股數 → 「3 張」或「2 張 500 股」或「500 股」"""
    lots, odd = divmod(int(shares), SHARES_PER_LOT)
    if lots and odd:
        return f"{lots} 張 {odd} 股"
    if lots:
        return f"{lots} 張"
    return f"{odd} 股"


def estimate_fee(shares: int, price: float, discount: float = 1.0) -> int:
    """券商手續費試算：成交金額 × 0.1425% × 折扣，無條件捨去，整股最低 20 元、零股最低 1 元"""
    raw = math.floor(shares * price * FEE_RATE * discount)
    minimum = MIN_FEE_BOARD_LOT if shares >= SHARES_PER_LOT else MIN_FEE_ODD_LOT
    return max(raw, minimum)


def estimate_tax(code: str, shares: int, price: float) -> int:
    """賣出證交稅試算：股票 0.3%、ETF（00 開頭）0.1%，無條件捨去（不處理當沖減半等特例）"""
    rate = ETF_TAX_RATE if code.startswith("00") else STOCK_TAX_RATE
    return math.floor(shares * price * rate)


def _days_between(start: str | None, end: str | _date) -> int | None:
    if not start:
        return None
    try:
        end_date = end if isinstance(end, _date) else _date.fromisoformat(end)
        return (end_date - _date.fromisoformat(start)).days
    except ValueError:
        return None


def replay(trades: list[dict]) -> dict[str, dict]:
    """依時間重播交易 → 每檔目前狀態與已實現紀錄。賣超過持有股數時丟出 TradeError。"""
    ordered = sorted(trades, key=lambda t: (t["date"], t["id"] if t.get("id") is not None else 0))
    states: dict[str, dict] = {}
    for trade in ordered:
        code = trade["code"]
        state = states.setdefault(code, {"code": code, "name": trade.get("name") or code, "shares": 0, "cost": 0.0,
                                         "opened_date": None, "lot_buys": [], "realized": []})
        if trade.get("name"):
            state["name"] = trade["name"]
        shares, price = int(trade["shares"]), float(trade["price"])
        fee, tax = float(trade.get("fee") or 0), float(trade.get("tax") or 0)
        if shares <= 0 or price <= 0:
            raise TradeError(f"{trade['date']} {code} 股數與價格必須大於 0")

        if trade["side"] == "buy":
            if state["shares"] == 0:
                state["opened_date"], state["lot_buys"] = trade["date"], []
            state["shares"] += shares
            state["cost"] += shares * price + fee
            state["lot_buys"].append(trade)
            continue

        if shares > state["shares"]:
            raise TradeError(f"{trade['date']} {code} 賣出 {lots_text(shares)}，但當時只持有 {lots_text(state['shares'])}")
        avg_cost = state["cost"] / state["shares"]
        cost_basis = avg_cost * shares
        proceeds = shares * price - fee - tax
        state["realized"].append({
            **trade,
            "name": state["name"],
            "avg_cost": avg_cost,
            "cost_basis": cost_basis,
            "proceeds": proceeds,
            "pnl": proceeds - cost_basis,
            "return_pct": (proceeds / cost_basis - 1) * 100 if cost_basis else None,
            "opened_date": state["opened_date"],
            "holding_days": _days_between(state["opened_date"], trade["date"]),
            "lot_buys": list(state["lot_buys"]),
        })
        state["shares"] -= shares
        state["cost"] -= cost_basis
        if state["shares"] == 0:
            state["cost"] = 0.0
    return states


def validate(trades: list[dict]) -> str | None:
    """回傳錯誤訊息；沒問題回傳 None（UI 儲存前檢查用）"""
    try:
        replay(trades)
    except TradeError as exc:
        return str(exc)
    return None


def summarize_position(state: dict, price: dict | None, today: _date | None = None) -> dict:
    """一檔的持倉狀態 + 最新收盤 → 畫面與提示詞用的持倉資訊"""
    today = today or _date.today()
    shares, cost = state["shares"], state["cost"]
    position = {
        "code": state["code"],
        "name": (price or {}).get("name") or state["name"],
        "records": len(state["lot_buys"]),
        "shares": shares,
        "cost": cost,
        "avg_cost": cost / shares if shares else None,
        "first_buy_date": state["opened_date"],
        "holding_days": _days_between(state["opened_date"], today),
        "lot_buys": state["lot_buys"],
        "close": None, "price_date": None, "day_change": None,
        "market_value": None, "pnl": None, "pnl_pct": None,
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


def _states(as_of: str | None = None) -> dict[str, dict]:
    trades = db.query_trades()
    if as_of:
        trades = [t for t in trades if t["date"] <= as_of]
    try:
        return replay(trades)
    except TradeError:
        return {}  # 資料錯誤時畫面會另外提示；這裡不讓整頁當掉


def load_positions(as_of: str | None = None) -> list[dict]:
    """目前持有中的部位（依市值由大到小；沒有市價的排最後）"""
    positions = [summarize_position(state, db.query_latest_close(code, as_of))
                 for code, state in _states(as_of).items() if state["shares"] > 0]
    return sorted(positions, key=lambda p: (p["market_value"] is None, -(p["market_value"] or 0)))


def realized_trades(year: int | None = None) -> list[dict]:
    """已實現的賣出紀錄（由新到舊）"""
    rows = [r for state in _states().values() for r in state["realized"]]
    if year:
        rows = [r for r in rows if r["date"].startswith(str(year))]
    return sorted(rows, key=lambda r: (r["date"], r["id"]), reverse=True)


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
    state = _states().get(code)
    if not state or state["shares"] <= 0:
        return None
    total_value = portfolio_totals(load_positions())["market_value"]
    p = summarize_position(state, db.query_latest_close(code))
    lines = [f"持有 {lots_text(p['shares'])}，平均成本 {p['avg_cost']:,.2f} 元（含買進手續費，共 {p['records']} 筆買進）"]
    if p["first_buy_date"]:
        lines.append(f"這段持有從 {p['first_buy_date']} 開始，已持有 {p['holding_days']} 天")
    if p["close"] is not None:
        lines.append(
            f"最新收盤 {p['close']:,.2f} 元（{p['price_date']}），未實現損益 {p['pnl']:+,.0f} 元"
            f"（{p['pnl_pct']:+.2f}%，未扣將來賣出的手續費與證交稅）"
        )
        if total_value:
            lines.append(f"佔目前持股總市值 {p['market_value'] / total_value * 100:.1f}%")
    else:
        lines.append("本地資料庫查無最新收盤價，無法計算損益")
    for buy in p["lot_buys"]:
        reason = f"，理由：{buy['reason']}" if buy.get("reason") else ""
        lines.append(f"買進 {buy['date']} {lots_text(buy['shares'])} @ {float(buy['price']):,.2f}{reason}")
    return "\n".join(lines)


_REVIEW_PROMPT = """你是台股交易覆盤助手。以下是使用者一筆已賣出交易的完整紀錄，請幫忙檢討這次的進出場。

【交易結果】
{result_block}

【買進紀錄與當時理由】
{buy_block}

【賣出紀錄與理由】
{sell_block}

【持有期間走勢】（本地資料庫收盤價）
{price_block}

請用繁體中文、條列精簡回答以下三項，不要開場白，總字數 800 字以內：
進場檢討：（對照當時的理由與之後走勢，進場的判斷哪裡合理、哪裡可以更好）
出場檢討：（出場時機與理由是否一致，是否太早或太晚，對照同期大盤表現）
下次可以注意：（可以帶到之後交易的具體檢查點，例如進場前要確認的條件、停損停利紀律）

這是事後覆盤，只檢討這筆交易的決策過程，不要對這檔股票給出之後的買賣建議。
"""


def build_review_prompt(sell_trade_id: int) -> str | None:
    record = next((r for r in realized_trades() if r["id"] == sell_trade_id), None)
    if not record:
        return None
    code, start, end = record["code"], record["opened_date"], record["date"]
    result_block = "\n".join([
        f"{code} {record['name']}：賣出 {lots_text(record['shares'])}，平均成本 {record['avg_cost']:,.2f}，"
        f"賣出價 {float(record['price']):,.2f}",
        f"已實現損益 {record['pnl']:+,.0f} 元（{record['return_pct']:+.2f}%，已扣手續費與證交稅），"
        f"持有 {record['holding_days']} 天（{start} ～ {end}）",
    ])
    buy_block = "\n".join(
        f"- {b['date']} 買進 {lots_text(b['shares'])} @ {float(b['price']):,.2f}：{b.get('reason') or '（未填理由）'}"
        for b in record["lot_buys"]
    )
    sell_block = f"- {end} 賣出 {lots_text(record['shares'])} @ {float(record['price']):,.2f}：{record.get('reason') or '（未填理由）'}"

    prices = [r for r in db.query_price_range(code, start, end) if r["close"] is not None]
    if len(prices) >= 2:
        closes = [float(r["close"]) for r in prices]
        high_row = max(prices, key=lambda r: r["close"])
        low_row = min(prices, key=lambda r: r["close"])
        market = db.query_market_average_return(prices[0]["date"], prices[-1]["date"])
        price_lines = [
            f"期間收盤 {closes[0]:,.2f} → {closes[-1]:,.2f}（{(closes[-1] / closes[0] - 1) * 100:+.2f}%）",
            f"期間最高收盤 {float(high_row['close']):,.2f}（{high_row['date']}）、最低收盤 {float(low_row['close']):,.2f}（{low_row['date']}）",
        ]
        if market is not None:
            price_lines.append(f"同期上市個股平均報酬 {market:+.2f}%")
        if len(prices) > 12:
            step = max(1, len(prices) // 10)
            sampled = prices[::step] + ([prices[-1]] if prices[-1] not in prices[::step] else [])
            price_lines.append("走勢取樣：" + "、".join(f"{r['date'][5:]} {float(r['close']):,.2f}" for r in sampled))
        else:
            price_lines.append("每日收盤：" + "、".join(f"{r['date'][5:]} {float(r['close']):,.2f}" for r in prices))
        price_block = "\n".join(price_lines)
    else:
        price_block = "（本地資料庫的價格資料不足，無法描述持有期間走勢）"

    return _REVIEW_PROMPT.format(result_block=result_block, buy_block=buy_block, sell_block=sell_block,
                                 price_block=price_block)
