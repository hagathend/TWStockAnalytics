"""證交所「每日市場成交資訊」（FMTQIK）：每天的發行量加權股價指數、成交股數／金額／筆數。

一次請求給一整個月的每日資料，用 date=YYYYMM01 指定月份，回補歷史很省請求數。
"""

from datetime import date as _date

import requests

from src.collectors.twse_official import _HEADERS, _TIMEOUT, _to_float, _to_int

_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"


def _roc_slash_date(text: str) -> str | None:
    """'115/09/01' → '2026-09-01'"""
    parts = (text or "").strip().split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return f"{int(parts[0]) + 1911}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def parse_payload(payload: dict) -> list[dict]:
    if payload.get("stat") != "OK" or not payload.get("fields"):
        return []
    idx = {name: i for i, name in enumerate(payload["fields"])}
    rows = []
    for cols in payload.get("data", []):
        iso = _roc_slash_date(cols[idx["日期"]])
        taiex = _to_float(cols[idx["發行量加權股價指數"]])
        if not iso or taiex is None:
            continue
        rows.append({
            "date": iso,
            "taiex": taiex,
            "change": _to_float(cols[idx["漲跌點數"]]),
            "volume": _to_int(cols[idx["成交股數"]]),
            "turnover": _to_int(cols[idx["成交金額"]]),
            "transactions": _to_int(cols[idx["成交筆數"]]),
        })
    return rows


def fetch_month(year: int, month: int) -> list[dict]:
    resp = requests.get(_URL, headers=_HEADERS, params={"date": f"{year}{month:02d}01", "response": "json"},
                        timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_payload(resp.json())


def fetch_current_month() -> list[dict]:
    today = _date.today()
    return fetch_month(today.year, today.month)
