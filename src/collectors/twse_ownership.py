"""證交所每日：外資及陸資持股（MI_QFIIS）、信用額度總量管制餘額表的借券賣出（TWT93U）。

兩者都可以用 date=YYYYMMDD 指定日期，所以能回補歷史。股數單位都是「股」。
TWT93U 前半段是融資融券（已由 MI_MARGN 收集），後半段才是借券賣出；兩段的欄位名稱重複（例如兩個「前日餘額」），
所以借券欄位用「位置」取：第 9～14 欄。
"""

from datetime import date as _date

import requests

from src.collectors.twse_official import _HEADERS, _TIMEOUT, _to_float, _to_int

_QFIIS_URL = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
_SBL_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def parse_foreign_holding(payload: dict, yyyymmdd: str, keep_code=None) -> list[dict]:
    if payload.get("stat") != "OK" or not payload.get("fields"):
        return []
    idx = {name: i for i, name in enumerate(payload["fields"])}
    rows = []
    for cols in payload.get("data", []):
        code = str(cols[idx["證券代號"]]).strip()
        if keep_code and not keep_code(code):
            continue
        rows.append({
            "date": _iso(yyyymmdd), "code": code, "name": str(cols[idx["證券名稱"]]).strip(),
            "issued_shares": _to_int(cols[idx["發行股數"]]),
            "foreign_shares": _to_int(cols[idx["全體外資及陸資持有股數"]]),
            "foreign_pct": _to_float(cols[idx["全體外資及陸資持股比率"]]),
            "foreign_limit_pct": _to_float(cols[idx["外資及陸資共用法令投資上限比率"]]),
        })
    return rows


def parse_sbl(payload: dict, yyyymmdd: str, keep_code=None) -> list[dict]:
    if payload.get("stat") != "OK" or not payload.get("fields"):
        return []
    fields = payload["fields"]
    if len(fields) < 14 or fields[0] != "代號":
        raise ValueError(f"TWT93U 欄位格式改變：{fields}")
    rows = []
    for cols in payload.get("data", []):
        code = str(cols[0]).strip()
        if keep_code and not keep_code(code):
            continue
        rows.append({
            "date": _iso(yyyymmdd), "code": code, "name": str(cols[1]).strip(),
            "prev_balance": _to_int(cols[8]), "sold": _to_int(cols[9]), "returned": _to_int(cols[10]),
            "adjusted": _to_int(cols[11]), "balance": _to_int(cols[12]), "next_limit": _to_int(cols[13]),
        })
    return rows


def _get(url: str, params: dict) -> dict:
    resp = requests.get(url, headers=_HEADERS, params={**params, "response": "json"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _stock_only(code: str) -> bool:
    from src.storage.db import is_stock_code

    return is_stock_code(code)


def fetch_foreign_holding(yyyymmdd: str | None = None) -> list[dict]:
    yyyymmdd = yyyymmdd or _date.today().strftime("%Y%m%d")
    return parse_foreign_holding(_get(_QFIIS_URL, {"date": yyyymmdd, "selectType": "ALLBUT0999"}), yyyymmdd,
                                 keep_code=_stock_only)


def fetch_sbl(yyyymmdd: str | None = None) -> list[dict]:
    yyyymmdd = yyyymmdd or _date.today().strftime("%Y%m%d")
    return parse_sbl(_get(_SBL_URL, {"date": yyyymmdd}), yyyymmdd, keep_code=_stock_only)
