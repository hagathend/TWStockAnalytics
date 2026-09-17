"""期交所「三大法人－區分各期貨契約」每日交易與未平倉（CSV 下載，可指定日期區間）。

POST https://www.taifex.com.tw/cht/3/futContractsDateDown
  queryStartDate / queryEndDate：YYYY/MM/DD；commodityId：TXF＝臺股期貨
回應為 MS950（Big5）編碼的 CSV，每天三列（自營商、投信、外資及陸資）。口數單位「口」，金額單位千元。
"""

import csv
import io
from datetime import date as _date

import requests

from src.collectors.twse_official import _HEADERS, _to_int

_URL = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
_TIMEOUT = 60
IDENTITIES = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign"}


def parse_csv(text: str, commodity: str = "TXF") -> list[dict]:
    rows = []
    for item in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        identity = IDENTITIES.get((item.get("身份別") or "").strip())
        raw_date = (item.get("日期") or "").strip()
        if not identity or len(raw_date) != 10:
            continue
        rows.append({
            "date": raw_date.replace("/", "-"), "commodity": commodity, "identity": identity,
            "long_trade": _to_int(item.get("多方交易口數")), "short_trade": _to_int(item.get("空方交易口數")),
            "net_trade": _to_int(item.get("多空交易口數淨額")),
            "long_oi": _to_int(item.get("多方未平倉口數")), "short_oi": _to_int(item.get("空方未平倉口數")),
            "net_oi": _to_int(item.get("多空未平倉口數淨額")),
            "net_oi_value": _to_int(item.get("多空未平倉契約金額淨額(千元)")),
        })
    return rows


def fetch_range(start: _date, end: _date, commodity: str = "TXF") -> list[dict]:
    data = {"queryStartDate": start.strftime("%Y/%m/%d"), "queryEndDate": end.strftime("%Y/%m/%d"),
            "commodityId": commodity}
    resp = requests.post(_URL, data=data, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_csv(resp.content.decode("big5", errors="replace"), commodity)
