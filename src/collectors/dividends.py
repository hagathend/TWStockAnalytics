"""除權除息預告：證交所 TWT48U（上市）、櫃買中心 OpenAPI tpex_exright_prepost（上櫃）。

只列「即將」除權息的股票（含 ETF），每天抓一次覆寫；已過的日期留在資料庫當紀錄。
現金股利有時是「待公告實際收益分配金額」這類文字（ETF 常見），存成 None。
"""

import re

import requests

from src.collectors.twse_official import _HEADERS, _TIMEOUT, _roc_date_to_iso, _to_float, _tpex_session

_TWSE_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U"
_TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"
_ROC_CHINESE_DATE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")


def _kind(text: str) -> str:
    """統一成「息」「權」「權息」"""
    text = (text or "").replace("除", "").strip()
    return "權息" if "權" in text and "息" in text else text


def _number_or_none(value):
    number = _to_float(value)
    return number if number else None


def parse_twse(payload: dict) -> list[dict]:
    if payload.get("stat") != "OK" or not payload.get("fields"):
        return []
    idx = {name: i for i, name in enumerate(payload["fields"])}
    rows = []
    for cols in payload.get("data", []):
        match = _ROC_CHINESE_DATE.search(str(cols[idx["除權除息日期"]]))
        if not match:
            continue
        year, month, day = (int(g) for g in match.groups())
        rows.append({
            "ex_date": f"{year + 1911}-{month:02d}-{day:02d}", "market": "TWSE",
            "code": str(cols[idx["股票代號"]]).strip(), "name": str(cols[idx["名稱"]]).strip(),
            "kind": _kind(cols[idx["除權息"]]),
            "cash_dividend": _number_or_none(cols[idx["現金股利"]]),
            "stock_ratio": _number_or_none(cols[idx["無償配股率"]]),
        })
    return rows


def parse_tpex(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        ex_date = _roc_date_to_iso(item.get("ExRrightsExDividendDate", ""))
        code = (item.get("SecuritiesCompanyCode") or "").strip()
        if not ex_date or not code:
            continue
        rows.append({
            "ex_date": ex_date, "market": "TPEx", "code": code, "name": (item.get("CompanyName") or "").strip(),
            "kind": _kind(item.get("ExRrightsExDividend")),
            "cash_dividend": _number_or_none(item.get("CashDividend")),
            "stock_ratio": _number_or_none(item.get("StockDividendRatio")),
        })
    return rows


def fetch_twse_dividends() -> list[dict]:
    resp = requests.get(_TWSE_URL, headers=_HEADERS, params={"response": "json"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_twse(resp.json())


def fetch_tpex_dividends() -> list[dict]:
    resp = _tpex_session().get(_TPEX_URL, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_tpex(resp.json())
