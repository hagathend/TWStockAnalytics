"""AI 預測改用「觀點」來追蹤：同一檔股票連續同方向的預測合併成一段觀點，一段只算一次成績。

為什麼：持股每天都做個股分析，每天各記一筆 10 日預測的話，同一段走勢會被重複計分好幾次，
AI 今天偏多、明天中性的來回翻轉也會把統計攪亂，看不出到底準不準。

規則（交易日以上市股價資料的日期為準）：
- 觀點從第一筆預測的分析日開始；之後同方向的預測只是「延續」，併進同一段
- 方向改變 → 舊觀點在新預測那天結束（結束原因：方向改變），新方向開新的一段
- 同方向但從開始已滿 VIEW_MAX_DAYS 個交易日 → 舊觀點在第 VIEW_MAX_DAYS 天結束（滿 10 日），之後的預測開新的一段
- 成績：開始日收盤 → 結束日收盤的報酬，同樣用 predictions.is_hit 判定；附同期上市個股平均報酬當基準
- 持續不到 MIN_SCORED_DAYS 個交易日就翻轉的觀點「太短不計分」，但會算進翻轉次數
- 中性的命中條件（±3% 內）本來就寬鬆，統計時和偏多／偏空分開，不混在一起算命中率
"""

from bisect import bisect_right

from src import predictions
from src.storage import db

VIEW_MAX_DAYS = predictions.VERDICT_HORIZON
MIN_SCORED_DAYS = 3

STATUS_LABELS = {"active": "進行中", "done": "已結束", "too_short": "太短不計", "no_data": "資料不足"}
REASON_CHANGED = "方向改變"
REASON_EXPIRED = f"滿 {VIEW_MAX_DAYS} 日"


def _trading_index(trading_dates: list[str], date: str) -> int | None:
    """date 當天或之前最近的交易日在清單中的位置（分析日可能是假日）"""
    position = bisect_right(trading_dates, date) - 1
    return position if position >= 0 else None


def group_views(rows: list[dict], trading_dates: list[str]) -> list[dict]:
    """同一檔股票的預測（任意順序）→ 觀點段落（由舊到新），尚未計算報酬。
    每段：code, name, direction, start_idx, end_idx（None＝進行中）, end_reason, analyses（併進來的預測）"""
    views: list[dict] = []
    current = None
    for row in sorted(rows, key=lambda r: r["date"]):
        index = _trading_index(trading_dates, row["date"])
        if index is None:
            continue
        if current and row["direction"] == current["direction"] and index - current["start_idx"] < VIEW_MAX_DAYS:
            current["analyses"].append(row)
            continue
        if current:
            expired = index - current["start_idx"] >= VIEW_MAX_DAYS
            current["end_idx"] = current["start_idx"] + VIEW_MAX_DAYS if expired else index
            current["end_reason"] = REASON_EXPIRED if expired else REASON_CHANGED
            views.append(current)
        current = {"code": row["code"], "name": row["name"], "direction": row["direction"], "start_idx": index,
                   "end_idx": None, "end_reason": None, "analyses": [row]}
    if current:
        if current["start_idx"] + VIEW_MAX_DAYS < len(trading_dates):
            current["end_idx"], current["end_reason"] = current["start_idx"] + VIEW_MAX_DAYS, REASON_EXPIRED
        views.append(current)
    return views


def _evaluate(view: dict, trading_dates: list[str], market_cache: dict) -> dict:
    start_date = trading_dates[view["start_idx"]]
    active = view["end_idx"] is None
    end_idx = len(trading_dates) - 1 if active else view["end_idx"]
    end_date = trading_dates[end_idx]
    latest = view["analyses"][-1]
    result = {
        "code": view["code"], "name": view["name"], "direction": view["direction"],
        "start_date": start_date, "end_date": None if active else end_date, "as_of": end_date,
        "days": end_idx - view["start_idx"], "analyses": len(view["analyses"]),
        "analysis_dates": [a["date"] for a in view["analyses"]],
        "end_reason": "進行中" if active else view["end_reason"],
        "support": latest.get("support"), "resistance": latest.get("resistance"), "confidence": latest.get("confidence"),
        "start_close": None, "end_close": None, "return_pct": None, "market_return": None, "excess": None, "hit": None,
    }
    start = db.query_latest_close(view["code"], start_date)
    end = db.query_latest_close(view["code"], end_date)
    if not start or not end or not start["close"]:
        result["status"] = "no_data"
        return result
    result["start_close"], result["end_close"] = float(start["close"]), float(end["close"])
    result["return_pct"] = (result["end_close"] / result["start_close"] - 1) * 100
    if result["days"]:
        key = (start_date, end_date)
        if key not in market_cache:
            market_cache[key] = db.query_market_average_return(start_date, end_date)
        result["market_return"] = market_cache[key]
        if result["market_return"] is not None:
            result["excess"] = result["return_pct"] - result["market_return"]
    if active:
        result["status"] = "active"
    elif result["days"] < MIN_SCORED_DAYS:
        result["status"] = "too_short"
    else:
        result["status"] = "done"
        result["hit"] = predictions.is_hit(view["direction"], result["return_pct"])
    return result


def build_views(code: str | None = None) -> list[dict]:
    """全部（或單一股票）的觀點與成績，新到舊（依開始日），同一天依代號"""
    trading_dates = db.query_trading_dates("TWSE")
    if not trading_dates:
        return []
    by_code: dict[str, list[dict]] = {}
    for row in db.query_predictions(code):
        by_code.setdefault(row["code"], []).append(row)
    market_cache: dict = {}
    views = [_evaluate(view, trading_dates, market_cache)
             for rows in by_code.values() for view in group_views(rows, trading_dates)]
    return sorted(views, key=lambda v: (v["start_date"], v["code"]), reverse=True)


def current_views(views: list[dict]) -> list[dict]:
    """每檔股票最新的一段觀點（不管是否已結束），依開始日新到舊"""
    latest: dict[str, dict] = {}
    for view in views:
        if view["code"] not in latest or view["start_date"] > latest[view["code"]]["start_date"]:
            latest[view["code"]] = view
    return sorted(latest.values(), key=lambda v: (v["start_date"], v["code"]), reverse=True)


def flip_stats(views: list[dict]) -> list[dict]:
    """每檔股票：分析次數、觀點段數、方向翻轉次數（因方向改變而結束的段數）、已計分段數與命中段數"""
    stats: dict[str, dict] = {}
    for view in views:
        s = stats.setdefault(view["code"], {"code": view["code"], "name": view["name"], "analyses": 0, "views": 0,
                                            "flips": 0, "scored": 0, "hits": 0})
        s["analyses"] += view["analyses"]
        s["views"] += 1
        s["flips"] += view["end_reason"] == REASON_CHANGED
        if view["status"] == "done":
            s["scored"] += 1
            s["hits"] += bool(view["hit"])
    for s in stats.values():
        s["flip_rate"] = s["flips"] / (s["analyses"] - 1) * 100 if s["analyses"] > 1 else None
    return sorted(stats.values(), key=lambda s: (-s["flips"], -s["analyses"], s["code"]))


def _group_stats(group: list[dict]) -> dict | None:
    if not group:
        return None
    excess = [v["excess"] for v in group if v["excess"] is not None]
    return {"count": len(group), "hit_rate": sum(v["hit"] for v in group) / len(group) * 100,
            "avg_return": sum(v["return_pct"] for v in group) / len(group),
            "avg_excess": sum(excess) / len(excess) if excess else None}


def summarize(views: list[dict]) -> dict:
    """偏多／偏空合起來算「方向性觀點」命中率；中性分開算；另外各方向的平均報酬與超額報酬"""
    done = [v for v in views if v["status"] == "done"]
    directional = [v for v in done if v["direction"] != "中性"]
    return {
        "total": len(views),
        "active": sum(v["status"] == "active" for v in views),
        "done": len(done),
        "too_short": sum(v["status"] == "too_short" for v in views),
        "flips": sum(v["end_reason"] == REASON_CHANGED for v in views),
        "directional": _group_stats(directional),
        "by_direction": {d: stats for d in predictions.DIRECTIONS
                         if (stats := _group_stats([v for v in done if v["direction"] == d]))},
    }
