"""公開申購（抽籤）：證交所「公開申購公告-抽籤日程表」，上市、上櫃、增資都在同一張表。

GET https://www.twse.com.tw/rwd/zh/announcement/publicForm?response=json&yy=西元年

- 日期是民國年，轉成西元；「未訂出」等非數字存 None
- 價差＝最新收盤 − 承銷價（初次上市櫃還沒有收盤價）；每一籤的價差＝價差 × 申購股數。
  只是用目前股價估算，撥券時的股價會不同，不是獲利保證
"""

from datetime import date as _date, timedelta

import pandas as pd
import requests

from src.collectors.twse_official import _HEADERS, _TIMEOUT, _to_float
from src.storage import db

_URL = "https://www.twse.com.tw/rwd/zh/announcement/publicForm"
COLUMNS = ["draw_date", "name", "code", "kind", "start_date", "end_date", "price", "shares_per_lot", "total_shares",
           "listing_date", "broker", "win_rate"]
_FIELDS = {"抽籤日期": "draw_date", "證券名稱": "name", "證券代號": "code", "發行市場": "kind", "申購開始日": "start_date",
           "申購結束日": "end_date", "承銷價(元)": "announced_price", "實際承銷價(元)": "actual_price",
           "承銷股數": "total_shares", "撥券日期(上市、上櫃日期)": "listing_date", "主辦券商": "broker",
           "申購股數": "shares_per_lot", "中籤率(%)": "win_rate", "取消公開抽籤": "cancelled"}


def _iso(roc: str) -> str | None:
    parts = str(roc or "").strip().split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return f"{int(parts[0]) + 1911}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def parse(payload: dict) -> list[dict]:
    if payload.get("stat") != "OK":
        return []
    fields = [str(f).strip() for f in payload.get("fields") or []]
    rows = []
    for cols in payload.get("data") or []:
        raw = {_FIELDS[f]: str(v).strip() for f, v in zip(fields, cols) if f in _FIELDS}
        if raw.get("cancelled"):
            continue
        price = _to_float(raw.get("actual_price"))
        rows.append({
            "draw_date": _iso(raw.get("draw_date")), "name": raw.get("name"), "code": raw.get("code"),
            "kind": raw.get("kind"), "start_date": _iso(raw.get("start_date")), "end_date": _iso(raw.get("end_date")),
            # 實際承銷價還沒訂出（競價拍賣中）時先用公告的承銷價
            "price": price if price is not None else _to_float(raw.get("announced_price")),
            "shares_per_lot": _to_float(raw.get("shares_per_lot")), "total_shares": _to_float(raw.get("total_shares")),
            "listing_date": _iso(raw.get("listing_date")), "broker": raw.get("broker"),
            "win_rate": _to_float(raw.get("win_rate")) or None,  # 還沒抽籤時是 0
        })
    return rows


def fetch(year: int) -> tuple[bool, list[dict] | str]:
    try:
        resp = requests.get(_URL, params={"response": "json", "yy": year}, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True, parse(resp.json())
    except (requests.RequestException, ValueError) as exc:
        return False, f"證交所公開申購資料讀取失敗：{exc}"


def schedule(rows: list[dict], today: _date, closes: dict[str, float], past_days: int = 14) -> pd.DataFrame:
    """還沒截止申購的排前面（依截止日），其次是最近 past_days 天內抽過籤的；附最新收盤與價差"""
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if frame.empty:
        return frame.assign(status=None, close=None, spread_pct=None, spread_per_lot=None)
    iso = today.isoformat()
    since = (today - timedelta(days=past_days)).isoformat()
    frame = frame[(frame["end_date"] >= iso) | (frame["draw_date"] >= since)].copy()
    frame["status"] = [("申購中" if start and start <= iso else "即將開始") if end and end >= iso else
                       ("待抽籤" if draw and draw >= iso else "已抽籤")
                       for start, end, draw in zip(frame["start_date"], frame["end_date"], frame["draw_date"])]
    frame["close"] = frame["code"].map(closes)
    price = pd.to_numeric(frame["price"], errors="coerce")
    frame["spread_pct"] = (frame["close"] - price) / price.where(price > 0) * 100
    frame["spread_per_lot"] = (frame["close"] - price) * frame["shares_per_lot"]
    order = {"申購中": 0, "即將開始": 1, "待抽籤": 2}
    active = frame[frame["status"] != "已抽籤"].assign(_order=lambda f: f["status"].map(order))
    active = active.sort_values(["_order", "end_date", "draw_date"]).drop(columns="_order")
    past = frame[frame["status"] == "已抽籤"].sort_values("draw_date", ascending=False)  # 最近抽籤的在前
    return pd.concat([active, past]).reset_index(drop=True)


def latest_closes(codes: list[str]) -> dict[str, float]:
    closes = {}
    for code in codes:
        rows = db.query_code_history("stock_price", code, limit=1)
        if rows and rows[0].get("close"):
            closes[code] = float(rows[0]["close"])
    return closes
