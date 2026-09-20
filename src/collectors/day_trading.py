"""現股當沖（每檔當沖成交股數與買賣金額），可指定日期，回應日期與查詢日期不同就當作查無資料。

- 上市：GET https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=YYYYMMDD&selectType=All
  （rwd 新路徑查不到這張表，舊路徑仍可用）
- 上櫃：POST https://www.tpex.org.tw/www/zh-tw/intraday/stat  date=YYYY/MM/DD&type=Daily&response=json
  （OpenAPI 只有全市場統計與可當沖標的清單，沒有每檔成交量）
"""

import requests

from src.collectors.twse_official import _HEADERS, _TIMEOUT, _tpex_session, _to_int

_TWSE_URL = "https://www.twse.com.tw/exchangeReport/TWTB4U"
_TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/intraday/stat"
_FIELDS = ("證券代號", "當日沖銷交易成交股數", "當日沖銷交易買進成交金額", "當日沖銷交易賣出成交金額")


def parse(payload: dict, date: str, market: str) -> list[dict]:
    """date：YYYYMMDD。回應日期對不上（尚未公布時會回前一個交易日或空表）就回空清單"""
    if str(payload.get("date") or "") != date:
        return []
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        if not all(f in fields for f in _FIELDS):
            continue
        idx = {f: fields.index(f) for f in _FIELDS}
        name_idx = fields.index("證券名稱") if "證券名稱" in fields else None
        rows = []
        for cols in table.get("data") or []:
            volume = _to_int(cols[idx["當日沖銷交易成交股數"]])
            if volume is None:
                continue
            rows.append({"date": iso, "market": market, "code": str(cols[idx["證券代號"]]).strip(),
                         "name": str(cols[name_idx]).strip() if name_idx is not None else None, "volume": volume,
                         "buy_value": _to_int(cols[idx["當日沖銷交易買進成交金額"]]),
                         "sell_value": _to_int(cols[idx["當日沖銷交易賣出成交金額"]])})
        return rows
    return []


def fetch_twse(date: str) -> list[dict]:
    resp = requests.get(_TWSE_URL, params={"response": "json", "date": date, "selectType": "All"},
                        headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse(resp.json(), date, "TWSE")


def fetch_tpex(date: str) -> list[dict]:
    data = {"date": f"{date[:4]}/{date[4:6]}/{date[6:8]}", "type": "Daily", "response": "json"}
    resp = _tpex_session().post(_TPEX_URL, data=data, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse(resp.json(), date, "TPEx")
