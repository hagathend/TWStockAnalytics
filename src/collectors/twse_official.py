"""TWSE (上市) / TPEx (上櫃) 官方 OpenAPI 收集器。

- TWSE 舊版查詢介面 (rwd)：`openapi.twse.com.tw` 的 STOCK_DAY_ALL / MI_MARGN
  實測會比 rwd 介面慢一拍公布當天資料（同一時間點 rwd 已經是當天收盤價，
  openapi 還停留在前一個交易日），且 MI_MARGN 完全沒有日期欄位可以判斷資料屬於哪一天。
  因此改用 rwd 介面（可指定 date 參數、回應內也會確認實際日期）：
    - 每日收盤行情: https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
    - 三大法人買賣超日報 (T86): https://www.twse.com.tw/rwd/zh/fund/T86
    - 融資融券 (MI_MARGN): https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN
- TPEx OpenAPI: https://www.tpex.org.tw/openapi/（實測目前資料公布時間點正常，
  但仍然信任 API 回傳裡的實際交易日期，不自行覆蓋，避免同一種問題發生在 TPEx 這邊）
"""

import ssl
from datetime import date as _date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 20


class _TpexSSLAdapter(HTTPAdapter):
    """TPEx 伺服器憑證鏈缺少 Subject Key Identifier 擴充欄位，OpenSSL 3.2+ 的
    X509_V_FLAG_X509_STRICT 嚴格模式會擋下它。這裡僅關閉該項嚴格檢查，
    憑證鏈驗證與主機名稱檢查（CERT_REQUIRED / check_hostname）仍然照常執行。"""

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def _tpex_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://www.tpex.org.tw", _TpexSSLAdapter())
    return session


def _roc_date_to_iso(roc: str) -> str | None:
    """將 '1150727' (民國年) 轉為 '2026-07-27'"""
    if not roc or len(roc) < 7:
        return None
    year = int(roc[:3]) + 1911
    month = roc[3:5]
    day = roc[5:7]
    return f"{year}-{month}-{day}"


def _to_float(v):
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _find_table(tables: list[dict], required_field: str) -> dict | None:
    for t in tables:
        if t.get("fields") and required_field in t["fields"]:
            return t
    return None


def _parse_change(color_tag: str, diff_str: str) -> float | None:
    """漲跌欄位是用 HTML 顏色標記方向（紅漲/綠跌），數值本身是絕對值，要自己補正負號"""
    diff = _to_float(diff_str)
    if diff is None:
        return None
    if "color:green" in (color_tag or ""):
        return -diff
    if "color:red" in (color_tag or ""):
        return diff
    return 0.0


def fetch_twse_price(date: str | None = None) -> list[dict]:
    """TWSE 上市每日收盤行情，date 格式 YYYYMMDD，預設為今天。
    用 type=ALLBUT0999 排除權證/牛熊證，只留一般股票與 ETF 等（約1300多檔）。"""
    date = date or _date.today().strftime("%Y%m%d")
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    params = {"date": date, "type": "ALLBUT0999", "response": "json"}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "OK":
        return []

    table = _find_table(payload.get("tables", []), "證券代號")
    if not table:
        return []

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = []
    for cols in table["data"]:
        rows.append(
            {
                "date": iso_date,
                "market": "TWSE",
                "code": cols[0].strip(),
                "name": cols[1].strip(),
                "open": _to_float(cols[5]),
                "high": _to_float(cols[6]),
                "low": _to_float(cols[7]),
                "close": _to_float(cols[8]),
                "change": _parse_change(cols[9], cols[10]),
                "volume": _to_int(cols[2]),
                "turnover": _to_int(cols[4]),
            }
        )
    return rows


def fetch_twse_margin(date: str | None = None) -> list[dict]:
    """TWSE 上市融資融券，date 格式 YYYYMMDD，預設為今天"""
    date = date or _date.today().strftime("%Y%m%d")
    url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    params = {"date": date, "selectType": "ALL", "response": "json"}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "OK":
        return []

    table = _find_table(payload.get("tables", []), "代號")
    if not table:
        return []

    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = []
    for cols in table["data"]:
        rows.append(
            {
                "date": iso_date,
                "market": "TWSE",
                "code": cols[0].strip(),
                "name": cols[1].strip(),
                "margin_buy": _to_int(cols[2]),
                "margin_sell": _to_int(cols[3]),
                "margin_balance": _to_int(cols[6]),
                "short_sell": _to_int(cols[9]),
                "short_cover": _to_int(cols[10]),
                "short_balance": _to_int(cols[12]),
            }
        )
    return rows


def fetch_twse_institutional(date: str | None = None) -> list[dict]:
    """TWSE 上市三大法人買賣超日報 (T86)，date 格式 YYYYMMDD，預設為今天"""
    date = date or _date.today().strftime("%Y%m%d")
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"date": date, "selectType": "ALL", "response": "json"}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "OK":
        return []

    fields = payload["fields"]
    idx = {name: i for i, name in enumerate(fields)}
    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = []
    for cols in payload["data"]:
        foreign_net = _to_int(cols[idx["外陸資買賣超股數(不含外資自營商)"]]) or 0
        foreign_dealer_net = _to_int(cols[idx["外資自營商買賣超股數"]]) or 0
        rows.append(
            {
                "date": iso_date,
                "market": "TWSE",
                "code": cols[idx["證券代號"]].strip(),
                "name": cols[idx["證券名稱"]].strip(),
                "foreign_net": foreign_net + foreign_dealer_net,
                "trust_net": _to_int(cols[idx["投信買賣超股數"]]),
                "dealer_net": _to_int(cols[idx["自營商買賣超股數"]]),
                "total_net": _to_int(cols[idx["三大法人買賣超股數"]]),
            }
        )
    return rows


def fetch_tpex_price() -> list[dict]:
    """TPEx 上櫃每日收盤價量（最近一個交易日，信任 API 回傳的實際交易日期）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": _roc_date_to_iso(item.get("Date", "")),
                "market": "TPEx",
                "code": item.get("SecuritiesCompanyCode"),
                "name": item.get("CompanyName"),
                "open": _to_float(item.get("Open")),
                "high": _to_float(item.get("High")),
                "low": _to_float(item.get("Low")),
                "close": _to_float(item.get("Close")),
                "change": _to_float(item.get("Change")),
                "volume": _to_int(item.get("TradingShares")),
                "turnover": _to_int(item.get("TransactionAmount")),
            }
        )
    return rows


def fetch_tpex_margin() -> list[dict]:
    """TPEx 上櫃融資融券（最近一個交易日，信任 API 回傳的實際交易日期）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": _roc_date_to_iso(item.get("Date", "")),
                "market": "TPEx",
                "code": item.get("SecuritiesCompanyCode"),
                "name": item.get("CompanyName"),
                "margin_balance": _to_int(item.get("MarginPurchaseBalance")),
                "margin_buy": _to_int(item.get("MarginPurchase")),
                "margin_sell": _to_int(item.get("MarginSales")),
                "short_balance": _to_int(item.get("ShortSaleBalance")),
                "short_sell": _to_int(item.get("ShortSale")),
                "short_cover": _to_int(item.get("ShortConvering")),
            }
        )
    return rows


def _find_value(item: dict, *substrings: str):
    """TPEx 3insti 開放資料欄位名稱常有多餘空白/不一致，改用子字串比對取值"""
    for key, value in item.items():
        normalized = key.replace(" ", "")
        if all(s.replace(" ", "") in normalized for s in substrings):
            return value
    return None


def fetch_tpex_institutional() -> list[dict]:
    """TPEx 上櫃三大法人買賣超（最近一個交易日，信任 API 回傳的實際交易日期）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = []
    for item in resp.json():
        foreign_net = _to_int(
            _find_value(item, "ForeignInvestorsIncludeMainlandAreaInvestors", "Difference")
        ) or 0
        trust_net = _to_int(
            _find_value(item, "SecuritiesInvestmentTrustCompanies", "Difference")
        )
        dealer_net = _to_int(_find_value(item, "Dealers", "Difference"))
        total_net = _to_int(item.get("TotalDifference"))
        rows.append(
            {
                "date": _roc_date_to_iso(item.get("Date", "")),
                "market": "TPEx",
                "code": item.get("SecuritiesCompanyCode"),
                "name": item.get("CompanyName"),
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": total_net,
            }
        )
    return rows
