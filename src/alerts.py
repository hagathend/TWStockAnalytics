"""條件提醒：使用者設定規則，每日收集完自動檢查，觸發時記錄並跳出 Windows 通知。

規則種類（kind）：
- price_above / price_below：收盤價 ≥／≤ 門檻（指定個股）
- change_above / change_below：當日漲跌幅 ≥ +門檻% ／ ≤ -門檻%（指定個股）
- holding_loss / holding_gain：持股報酬率 ≤ -門檻% ／ ≥ +門檻%（指定個股，或 code 留空＝所有持股）
- watchlist_signal：觀察名單「今天新出現」指定訊號（signal_key 留空＝任何新訊號）

同一條規則、同一檔、同一個資料日期只會觸發一次（alert_events 唯一鍵），重複檢查不會重複通知。
只看「最新交易日」的價格：個股最新價格日期落後（停牌、上櫃資料缺漏）時不觸發當日漲跌類規則。
"""

from src import notify, portfolio, signals
from src.config_watchlist import load_watchlist
from src.storage import db

KINDS = {
    "price_above": "股價高於",
    "price_below": "股價低於",
    "change_above": "單日上漲超過",
    "change_below": "單日下跌超過",
    "holding_loss": "持股虧損超過",
    "holding_gain": "持股獲利超過",
    "watchlist_signal": "觀察名單出現新訊號",
}
PRICE_KINDS = {"price_above", "price_below", "change_above", "change_below"}
HOLDING_KINDS = {"holding_loss", "holding_gain"}


def describe_rule(rule: dict) -> str:
    kind, threshold = rule["kind"], rule.get("threshold")
    target = f"{rule['code']} {rule.get('name') or ''}".strip() if rule.get("code") else None
    if kind in ("price_above", "price_below"):
        return f"{target}：{KINDS[kind]} {threshold:,.2f}"
    if kind in ("change_above", "change_below"):
        return f"{target}：{KINDS[kind]} {threshold:g}%"
    if kind in HOLDING_KINDS:
        return f"{target or '所有持股'}：{KINDS[kind]} {threshold:g}%"
    signal = signals.SIGNALS.get(rule.get("signal_key") or "", "任何訊號")
    return f"觀察名單：出現「{signal}」"


def _change_pct(price: dict) -> float | None:
    close, change = price.get("close"), price.get("change")
    if close is None or change is None or close - change <= 0:
        return None
    return change / (close - change) * 100


def _price_events(rule: dict, latest_date: str) -> list[dict]:
    price = db.query_latest_close(rule["code"])
    if not price or price.get("close") is None:
        return []
    close, threshold, kind = float(price["close"]), float(rule["threshold"]), rule["kind"]
    label = f"{rule['code']} {price.get('name') or rule.get('name') or ''}".strip()
    if kind == "price_above" and close >= threshold:
        message = f"{label} 收盤 {close:,.2f}，已高於 {threshold:,.2f}"
    elif kind == "price_below" and close <= threshold:
        message = f"{label} 收盤 {close:,.2f}，已低於 {threshold:,.2f}"
    elif kind in ("change_above", "change_below"):
        if price["date"] != latest_date:  # 沒有最新一天的價格，不能拿舊的漲跌幅來觸發
            return []
        pct = _change_pct(price)
        if pct is None:
            return []
        if kind == "change_above" and pct >= threshold:
            message = f"{label} 今日上漲 {pct:+.2f}%（收盤 {close:,.2f}）"
        elif kind == "change_below" and pct <= -threshold:
            message = f"{label} 今日下跌 {pct:+.2f}%（收盤 {close:,.2f}）"
        else:
            return []
    else:
        return []
    return [{"date": price["date"], "code": rule["code"], "name": price.get("name"), "message": message}]


def _holding_events(rule: dict, positions: list[dict]) -> list[dict]:
    events = []
    threshold = float(rule["threshold"])
    for p in positions:
        if rule.get("code") and p["code"] != rule["code"]:
            continue
        if p["pnl_pct"] is None:
            continue
        if rule["kind"] == "holding_loss" and p["pnl_pct"] <= -threshold:
            message = f"{p['code']} {p['name']} 持股報酬率 {p['pnl_pct']:+.2f}%，虧損已超過 {threshold:g}%"
        elif rule["kind"] == "holding_gain" and p["pnl_pct"] >= threshold:
            message = f"{p['code']} {p['name']} 持股報酬率 {p['pnl_pct']:+.2f}%，獲利已超過 {threshold:g}%"
        else:
            continue
        events.append({"date": p["price_date"], "code": p["code"], "name": p["name"], "message": message})
    return events


def _signal_events(rule: dict, watch_alerts: list[dict]) -> list[dict]:
    wanted = rule.get("signal_key")
    events = []
    for alert in watch_alerts:
        new = [k for k in alert["new"] if not wanted or k == wanted]
        if not new:
            continue
        names = "、".join(signals.SIGNALS[k] for k in new)
        events.append({"date": alert["date"], "code": alert["code"], "name": alert["name"],
                       "message": f"{alert['code']} {alert['name']} 出現新訊號：{names}"})
    return events


def check_alerts(notify_user: bool = True) -> dict:
    """檢查所有啟用中的規則。回傳 {"new_events": [...], "notified": bool, "message": str}"""
    rules = [r for r in db.query_alert_rules() if r["enabled"]]
    if not rules:
        return {"new_events": [], "notified": False, "message": "沒有啟用中的提醒規則"}

    trading_dates = db.query_trading_dates("TWSE")
    latest_date = trading_dates[-1] if trading_dates else None
    positions = portfolio.load_positions() if any(r["kind"] in HOLDING_KINDS for r in rules) else []
    watch_alerts = []
    if any(r["kind"] == "watchlist_signal" for r in rules):
        watch_alerts = signals.watchlist_alerts(signals.load_signal_history(), load_watchlist().keys())

    new_events = []
    for rule in rules:
        if rule["kind"] in PRICE_KINDS:
            candidates = _price_events(rule, latest_date)
        elif rule["kind"] in HOLDING_KINDS:
            candidates = _holding_events(rule, positions)
        else:
            candidates = _signal_events(rule, watch_alerts)
        for event in candidates:
            if event["date"] and db.save_alert_event(rule["id"], event):
                new_events.append({**event, "rule_id": rule["id"]})

    notified = False
    message = "沒有新觸發的提醒"
    if new_events:
        message = f"觸發 {len(new_events)} 則提醒"
        if notify_user:
            notified, detail = notify.show_toast(f"台股分析：{len(new_events)} 則提醒", [e["message"] for e in new_events])
            if not notified:
                message += f"（{detail}）"
    return {"new_events": new_events, "notified": notified, "message": message}
