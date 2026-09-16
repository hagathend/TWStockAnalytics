"""AI 預測追蹤：把個股分析裡的「預測摘要」存下來，事後用實際股價檢驗 AI 準不準。

流程：
1. 個股分析提示詞要求最後輸出一行固定格式的「預測摘要」（方向、支撐、壓力、信心）
2. 儲存分析時解析那一行存進 predictions 表（沒有這行就不追蹤，不硬猜）
3. 需要時才即時計算結果：分析日收盤為基準，第 5／10 個交易日的報酬、同期大盤、支撐壓力有沒有被碰到

判定「方向命中」的門檻刻意留一點空間，避免 +0.1% 這種雜訊也算偏多命中：
偏多：10 日報酬 > +1%；偏空：< -1%；中性：絕對值 ≤ 3%。
交易日以上市股價資料的日期為準；第 10 個交易日沒有收盤價才算「資料不足」。
中間有缺資料的日子（常見於上櫃股）仍判定方向，但不判斷支撐壓力是否被碰到。
"""

import re

from src.storage import db

HORIZONS = (5, 10)
VERDICT_HORIZON = 10
BULL_MIN_PCT = 1.0
BEAR_MAX_PCT = -1.0
NEUTRAL_BAND_PCT = 3.0

DIRECTIONS = ("偏多", "中性", "偏空")
_SEP = r"\s*[=＝:：]\s*"
_NUMBER = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def parse_prediction(analysis_text: str) -> dict | None:
    """從分析文字抓出「預測摘要」那一行。方向是必要欄位，其他抓不到就是 None。"""
    for line in (analysis_text or "").splitlines():
        if "預測摘要" not in line and "方向" not in line:
            continue
        direction = re.search(rf"方向{_SEP}(偏多|中性|偏空)", line)
        if not direction:
            continue
        support = re.search(rf"支撐{_SEP}{_NUMBER}", line)
        resistance = re.search(rf"壓力{_SEP}{_NUMBER}", line)
        confidence = re.search(rf"信心{_SEP}(高|中|低)", line)
        return {
            "direction": direction.group(1),
            "support": float(support.group(1).replace(",", "")) if support else None,
            "resistance": float(resistance.group(1).replace(",", "")) if resistance else None,
            "confidence": confidence.group(1) if confidence else None,
        }
    return None


def record_from_analysis(date: str, code: str, name: str, analysis_text: str) -> dict | None:
    """儲存個股分析時呼叫：有預測摘要就存（同一天同一檔重新分析會覆蓋），沒有就刪掉舊的，避免留下過期預測"""
    prediction = parse_prediction(analysis_text)
    if prediction:
        db.save_prediction(date, code, name, prediction)
    else:
        db.delete_prediction(date, code)
    return prediction


def is_hit(direction: str, return_pct: float) -> bool:
    if direction == "偏多":
        return return_pct > BULL_MIN_PCT
    if direction == "偏空":
        return return_pct < BEAR_MAX_PCT
    return abs(return_pct) <= NEUTRAL_BAND_PCT


def evaluate(prediction: dict, trading_dates: list[str]) -> dict:
    """單筆預測的結果。trading_dates：由舊到新的交易日清單"""
    result = {**prediction, "status": "pending", "base_close": None, "hit": None,
              "support_broken": None, "resistance_reached": None, "days_elapsed": 0}
    for n in HORIZONS:
        result[f"return_{n}"] = None
        result[f"market_return_{n}"] = None

    base = db.query_latest_close(prediction["code"], prediction["date"])
    if not base:
        result["status"] = "no_data"
        return result
    base_date, base_close = base["date"], float(base["close"])
    result["base_close"] = base_close

    later = [d for d in trading_dates if d > base_date]
    result["days_elapsed"] = min(len(later), VERDICT_HORIZON)
    prices = {r["date"]: r for r in db.query_price_range(prediction["code"], base_date, later[VERDICT_HORIZON - 1]
                                                          if len(later) >= VERDICT_HORIZON else None)}
    for n in HORIZONS:
        if len(later) < n:
            continue
        exit_row = prices.get(later[n - 1])
        if not exit_row or exit_row["close"] is None:
            continue
        result[f"return_{n}"] = (float(exit_row["close"]) / base_close - 1) * 100
        result[f"market_return_{n}"] = db.query_market_average_return(base_date, later[n - 1])

    if len(later) < VERDICT_HORIZON:
        return result  # 還沒滿 10 個交易日

    if result[f"return_{VERDICT_HORIZON}"] is None:
        result["status"] = "no_data"
        return result
    result["status"] = "done"
    result["hit"] = is_hit(prediction["direction"], result[f"return_{VERDICT_HORIZON}"])

    # 支撐壓力要看期間每一天的高低點；中間有缺資料的日子（常見於上櫃股）就不判斷，避免漏看而誤判「沒跌破」
    window = [prices[d] for d in later[:VERDICT_HORIZON] if d in prices]
    if len(window) < VERDICT_HORIZON:
        return result
    lows = [float(r["low"]) for r in window if r["low"] is not None]
    highs = [float(r["high"]) for r in window if r["high"] is not None]
    if prediction.get("support") is not None and len(lows) == VERDICT_HORIZON:
        result["support_broken"] = min(lows) < prediction["support"]
    if prediction.get("resistance") is not None and len(highs) == VERDICT_HORIZON:
        result["resistance_reached"] = max(highs) > prediction["resistance"]
    return result


def evaluate_all(code: str | None = None) -> list[dict]:
    trading_dates = db.query_trading_dates("TWSE")
    return [evaluate(p, trading_dates) for p in db.query_predictions(code)]


def summarize(results: list[dict]) -> dict:
    """命中率統計（只算已到期、資料完整的預測）"""
    done = [r for r in results if r["status"] == "done"]
    summary = {"total": len(results), "done": len(done),
               "pending": sum(1 for r in results if r["status"] == "pending"),
               "hit_rate": None, "by_direction": {}}
    if done:
        summary["hit_rate"] = sum(r["hit"] for r in done) / len(done) * 100
    for direction in DIRECTIONS:
        group = [r for r in done if r["direction"] == direction]
        if not group:
            continue
        returns = [r[f"return_{VERDICT_HORIZON}"] for r in group]
        excess = [r[f"return_{VERDICT_HORIZON}"] - r[f"market_return_{VERDICT_HORIZON}"]
                  for r in group if r[f"market_return_{VERDICT_HORIZON}"] is not None]
        summary["by_direction"][direction] = {
            "count": len(group),
            "hit_rate": sum(r["hit"] for r in group) / len(group) * 100,
            "avg_return": sum(returns) / len(returns),
            "avg_excess": sum(excess) / len(excess) if excess else None,
        }
    return summary
