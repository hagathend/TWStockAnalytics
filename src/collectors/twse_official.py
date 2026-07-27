"""TWSE (上市) / TPEx (上櫃) 官方 OpenAPI 收集器。

- TWSE OpenAPI: https://openapi.twse.com.tw/
- TWSE 舊版查詢介面 (rwd)：三大法人買賣超日報 (T86) 未收錄在 OpenAPI 中，改用此介面
- TPEx OpenAPI: https://www.tpex.org.tw/openapi/
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


def fetch_twse_price() -> list[dict]:
    """TWSE 上市每日收盤價量（最近一個交易日，官方 OpenAPI 沒有 date 參數）。

    儲存日期一律用「收集當下日期」而非 API 回傳裡的交易日期，
    因為 TWSE/TPEx 各自的「最新一筆」有時不同步（例如某一邊還沒更新），
    若各自沿用內嵌日期會導致兩個市場的資料被存成不同日期、UI 依日期查詢時只看得到其中一邊。
    """
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    today = _date.today().isoformat()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": today,
                "market": "TWSE",
                "code": item.get("Code"),
                "name": item.get("Name"),
                "open": _to_float(item.get("OpeningPrice")),
                "high": _to_float(item.get("HighestPrice")),
                "low": _to_float(item.get("LowestPrice")),
                "close": _to_float(item.get("ClosingPrice")),
                "change": _to_float(item.get("Change")),
                "volume": _to_int(item.get("TradeVolume")),
                "turnover": _to_int(item.get("TradeValue")),
            }
        )
    return rows


def fetch_twse_margin() -> list[dict]:
    """TWSE 上市融資融券（最近一個交易日）"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    today = _date.today().isoformat()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": today,
                "market": "TWSE",
                "code": item.get("股票代號"),
                "name": item.get("股票名稱"),
                "margin_balance": _to_int(item.get("融資今日餘額")),
                "margin_buy": _to_int(item.get("融資買進")),
                "margin_sell": _to_int(item.get("融資賣出")),
                "short_balance": _to_int(item.get("融券今日餘額")),
                "short_sell": _to_int(item.get("融券賣出")),
                "short_cover": _to_int(item.get("融券現券償還")),
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
    """TPEx 上櫃每日收盤價量（最近一個交易日）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    today = _date.today().isoformat()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": today,
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
    """TPEx 上櫃融資融券（最近一個交易日）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    today = _date.today().isoformat()
    rows = []
    for item in resp.json():
        rows.append(
            {
                "date": today,
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
    """TPEx 上櫃三大法人買賣超（最近一個交易日）"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    resp = _tpex_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    today = _date.today().isoformat()
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
                "date": today,
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
