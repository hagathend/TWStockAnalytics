"""基本面資料收集：本益比／殖利率／股價淨值比（每日）、月營收（每月）。

- TWSE 本益比: https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d（可指定日期，跟價量同一套 rwd 介面）
- TPEx 本益比: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis（只有最新一天）
- 月營收（上市）: https://openapi.twse.com.tw/v1/opendata/t187ap05_L
- 月營收（上櫃）: https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O
  兩者都是「全市場最新公布月份」彙總表，已附月增率／年增率，只有最新一個月、無法指定月份，
  所以每天收一次、以「資料年月」為主鍵覆寫，歷史靠長期累積。營收單位為「千元」。

欄位一律用欄位名稱對應，不用固定位置：TWSE rwd 介面歷年改過欄位順序。
虧損公司的本益比會是 "-"，轉成 None（不是 0，0 會被篩選器誤判為超便宜）。
"""

from datetime import date as _date

import requests

from src.collectors.twse_official import (
    _HEADERS,
    _TIMEOUT,
    _roc_date_to_iso,
    _to_float,
    _to_int,
    _tpex_session,
)


def _positive_or_none(value):
    number = _to_float(value)
    return number if number is not None and number > 0 else None


def _roc_year_month(value: str) -> str | None:
    """'11508' → '2026-08'"""
    value = (value or "").strip()
    if len(value) < 5 or not value.isdigit():
        return None
    return f"{int(value[:-2]) + 1911}-{value[-2:]}"


def fetch_twse_valuation(date: str | None = None) -> list[dict]:
    """TWSE 上市個股日本益比、殖利率及股價淨值比，date 格式 YYYYMMDD，預設今天"""
    date = date or _date.today().strftime("%Y%m%d")
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
    params = {"date": date, "selectType": "ALL", "response": "json"}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "OK" or not payload.get("fields"):
        return []

    idx = {name: i for i, name in enumerate(payload["fields"])}
    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = []
    for cols in payload.get("data", []):
        rows.append({
            "date": iso_date,
            "market": "TWSE",
            "code": str(cols[idx["證券代號"]]).strip(),
            "name": str(cols[idx["證券名稱"]]).strip(),
            "pe_ratio": _positive_or_none(cols[idx["本益比"]]),
            "dividend_yield": _to_float(cols[idx["殖利率(%)"]]),
            "pb_ratio": _positive_or_none(cols[idx["股價淨值比"]]),
        })
    return rows


def fetch_tpex_valuation() -> list[dict]:
    """TPEx 上櫃本益比／殖利率／淨值比（最近一個交易日，信任 API 回傳日期）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = []
    for item in resp.json():
        rows.append({
            "date": _roc_date_to_iso(item.get("Date", "")),
            "market": "TPEx",
            "code": item.get("SecuritiesCompanyCode"),
            "name": item.get("CompanyName"),
            "pe_ratio": _positive_or_none(item.get("PriceEarningRatio")),
            "dividend_yield": _to_float(item.get("YieldRatio")),
            "pb_ratio": _positive_or_none(item.get("PriceBookRatio")),
        })
    return rows


def _parse_revenue_item(item: dict, market: str) -> dict:
    return {
        "year_month": _roc_year_month(item.get("資料年月")),
        "market": market,
        "code": (item.get("公司代號") or "").strip(),
        "name": (item.get("公司名稱") or "").strip(),
        "industry": item.get("產業別"),
        "revenue": _to_int(item.get("營業收入-當月營收")),
        "revenue_last_month": _to_int(item.get("營業收入-上月營收")),
        "revenue_last_year": _to_int(item.get("營業收入-去年當月營收")),
        "mom_pct": _to_float(item.get("營業收入-上月比較增減(%)")),
        "yoy_pct": _to_float(item.get("營業收入-去年同月增減(%)")),
        "cum_revenue": _to_int(item.get("累計營業收入-當月累計營收")),
        "cum_revenue_last_year": _to_int(item.get("累計營業收入-去年累計營收")),
        "cum_yoy_pct": _to_float(item.get("累計營業收入-前期比較增減(%)")),
    }


def _valid_revenue_rows(items: list[dict], market: str) -> list[dict]:
    rows = [_parse_revenue_item(item, market) for item in items]
    return [r for r in rows if r["year_month"] and r["code"]]


def fetch_twse_month_revenue() -> list[dict]:
    """上市公司最新公布月份的營收彙總（千元）"""
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return _valid_revenue_rows(resp.json(), "TWSE")


def fetch_tpex_month_revenue() -> list[dict]:
    """上櫃公司最新公布月份的營收彙總（千元）"""
    url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return _valid_revenue_rows(resp.json(), "TPEx")
