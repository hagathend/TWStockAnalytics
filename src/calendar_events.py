"""事件行事曆：把分散在各處的「接下來會發生的事」整理成一份清單。

事件種類：
- 除權息：證交所／櫃買中心預告；持股會附上預估現金股利（股數 × 每股現金股利，未扣補充保費與匯費）
- 月營收公布期限：依規定每月 10 日前公布上月營收
- AI 觀點到期日：同方向的連續預測合併成一段觀點（見 prediction_views），觀點開始後第 10 個交易日結算
  （以平日推估，遇國定假日會晚幾天）；已經因為方向改變而結束的觀點不列
"""

from datetime import date as _date, timedelta

import pandas as pd

from src import portfolio, prediction_views
from src.config_watchlist import load_watchlist
from src.storage import db

KIND_DIVIDEND = "除權息"
KIND_REVENUE = "月營收公布期限"
KIND_PREDICTION = "AI 觀點到期"


def _prediction_views(until: _date) -> list[dict]:
    """用「平日」當交易日曆把預測合併成觀點（未來的交易日還沒有股價資料），回傳還沒因方向改變而結束的觀點與到期日"""
    rows = db.query_predictions()
    if not rows:
        return []
    first = _date.fromisoformat(min(r["date"] for r in rows)) - timedelta(days=7)
    calendar, current = [], first
    while current <= until + timedelta(days=30):
        if current.weekday() < 5:
            calendar.append(current.isoformat())
        current += timedelta(days=1)
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        by_code.setdefault(row["code"], []).append(row)
    result = []
    for code_rows in by_code.values():
        for view in prediction_views.group_views(code_rows, calendar):
            if view["end_reason"] == prediction_views.REASON_CHANGED or view["end_idx"] is None:
                continue
            result.append({"code": view["code"], "name": view["name"], "direction": view["direction"],
                           "start": calendar[view["start_idx"]], "due": calendar[view["end_idx"]],
                           "analyses": len(view["analyses"])})
    return result


def _add_weekdays(start: _date, n: int) -> _date:
    current = start
    while n > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            n -= 1
    return current


def upcoming_events(start: _date | None = None, days: int = 30, include_holdings: bool = True) -> pd.DataFrame:
    """start（含）起 days 天內的事件。include_holdings=False 時不帶持股股數與預估股利（報告分享用）"""
    start = start or _date.today()
    end = start + timedelta(days=days)
    watchlist = load_watchlist()
    positions = {p["code"]: p for p in portfolio.load_positions()} if include_holdings else {}
    events = []

    for d in db.query_dividend_events(start.isoformat(), end.isoformat()):
        position = positions.get(d["code"])
        detail = []
        if d["cash_dividend"]:
            detail.append(f"現金股利 {d['cash_dividend']:g} 元")
        if d["stock_ratio"]:
            detail.append(f"配股率 {d['stock_ratio']:g}")
        if position and d["cash_dividend"]:
            detail.append(f"持有 {portfolio.lots_text(position['shares'])}，預估領 {position['shares'] * d['cash_dividend']:,.0f} 元")
        events.append({"date": d["ex_date"], "kind": KIND_DIVIDEND, "code": d["code"], "name": d["name"],
                       "title": f"除{d['kind']}", "detail": "、".join(detail),
                       "in_holdings": d["code"] in positions, "in_watchlist": d["code"] in watchlist})

    month_start = _date(start.year, start.month, 1)
    for i in range(3):
        year = month_start.year + (month_start.month - 1 + i) // 12
        month = (month_start.month - 1 + i) % 12 + 1
        deadline = _date(year, month, 10)
        if start <= deadline <= end:
            previous = 12 if month == 1 else month - 1
            events.append({"date": deadline.isoformat(), "kind": KIND_REVENUE, "code": "", "name": "",
                           "title": f"{previous} 月營收公布期限", "detail": "上市櫃公司最晚在這天前公布上月營收",
                           "in_holdings": False, "in_watchlist": False})

    for view in _prediction_views(end):
        due = _date.fromisoformat(view["due"])
        if start <= due <= end:
            events.append({"date": view["due"], "kind": KIND_PREDICTION, "code": view["code"], "name": view["name"],
                           "title": f"AI 觀點（{view['direction']}）滿 {prediction_views.VIEW_MAX_DAYS} 日",
                           "detail": f"{view['start']} 起的觀點（{view['analyses']} 次分析），約這天結算",
                           "in_holdings": view["code"] in positions, "in_watchlist": view["code"] in watchlist})

    columns = ["date", "kind", "code", "name", "title", "detail", "in_holdings", "in_watchlist"]
    if not events:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(events)[columns].sort_values(["date", "kind", "code"]).reset_index(drop=True)


def report_markdown(start: _date, days: int = 7, include_holdings: bool = False) -> str:
    """每日報告用：只列持股（可選）與觀察名單相關的除權息，加上營收公布期限"""
    events = upcoming_events(start, days, include_holdings)
    if events.empty:
        return "_（未來 7 天沒有相關事件）_"
    mine = events[(events["kind"] != KIND_DIVIDEND) | events["in_watchlist"] | events["in_holdings"]]
    mine = mine[mine["kind"] != KIND_PREDICTION]
    if mine.empty:
        return "_（未來 7 天持股與觀察名單沒有除權息，也沒有營收公布期限）_"
    lines = ["| 日期 | 事件 | 股票 | 說明 |", "|---|---|---|---|"]
    for e in mine.itertuples():
        stock = f"{e.code} {e.name}".strip() or "-"
        lines.append(f"| {e.date} | {e.title} | {stock} | {e.detail or '-'} |")
    return "\n".join(lines)
