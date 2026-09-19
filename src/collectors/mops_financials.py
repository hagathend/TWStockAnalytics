"""公開資訊觀測站舊站「綜合損益表／資產負債表／現金流量表」彙總查詢（全市場、指定年度季別）。

- 損益表：POST https://mopsov.twse.com.tw/mops/web/ajax_t163sb04
- 資產負債表：POST https://mopsov.twse.com.tw/mops/web/ajax_t163sb05（期末數，只有大分類，沒有存貨，所以算不出速動比）
- 現金流量表：POST https://mopsov.twse.com.tw/mops/web/ajax_t163sb20（年初累計，同損益表要相減才是單季）
- TYPEK：sii＝上市、otc＝上櫃；year 為民國年；season 01～04
- 一般業、銀行、證券、金控、保險、其他各一個表格，欄位名稱略有不同（例如「淨利（損）」與「淨利（淨損）」），
  所以用關鍵字比對欄位；損益表數字是「年初累計到該季」，單季數字要自己相減。金額單位千元，每股盈餘單位元。
"""

import requests
from bs4 import BeautifulSoup

from src.collectors.twse_official import _HEADERS, _to_float

_URL = "https://mopsov.twse.com.tw/mops/web/ajax_{report}"
_TYPEK = {"TWSE": "sii", "TPEx": "otc"}
_TIMEOUT = 90


def parse_tables(html: str) -> list[dict]:
    """把每個含「公司代號」的表格轉成 {欄位名稱: 文字} 的清單"""
    soup = BeautifulSoup(html, "lxml")
    records = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if "公司代號" not in headers:
            continue
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) == len(headers) and cells and cells[0]:
                records.append(dict(zip(headers, cells)))
    return records


def _pick(record: dict, predicate):
    for key, value in record.items():
        if predicate(key):
            return None if value in ("", "--") else _to_float(value)
    return None


def normalize_income(record: dict) -> dict:
    gross = _pick(record, lambda k: k == "營業毛利（毛損）淨額")
    if gross is None:
        gross = _pick(record, lambda k: k == "營業毛利（毛損）")
    return {
        "code": record["公司代號"].strip(),
        "name": record.get("公司名稱", "").strip(),
        "revenue": _pick(record, lambda k: k == "營業收入"),
        "gross_profit": gross,
        "operating_income": _pick(record, lambda k: k == "營業利益（損失）"),
        "net_income": _pick(record, lambda k: k.startswith("淨利") and "歸屬於母公司業主" in k),
        "eps": _pick(record, lambda k: k.startswith("基本每股盈餘")),
    }


def normalize_balance(record: dict) -> dict:
    equity = _pick(record, lambda k: "歸屬於母公司業主" in k and "權益" in k and "庫藏" not in k)
    if equity is None:
        equity = _pick(record, lambda k: k in ("權益總計", "權益總額"))
    return {
        "code": record["公司代號"].strip(),
        "equity": equity,
        "total_assets": _pick(record, lambda k: k in ("資產總計", "資產總額")),
        "total_liabilities": _pick(record, lambda k: k in ("負債總計", "負債總額")),
        "current_assets": _pick(record, lambda k: k == "流動資產"),  # 金融業沒有流動／非流動之分，會是 None
        "current_liabilities": _pick(record, lambda k: k == "流動負債"),
    }


def normalize_cashflow(record: dict) -> dict:
    return {
        "code": record["公司代號"].strip(),
        "operating_cf": _pick(record, lambda k: k.startswith("營業活動之淨現金流入")),
        "investing_cf": _pick(record, lambda k: k.startswith("投資活動之淨現金流入")),
        "financing_cf": _pick(record, lambda k: k.startswith("籌資活動之淨現金流入")),
    }


def _post(report: str, year: int, quarter: int, market: str) -> str:
    data = {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
            "TYPEK": _TYPEK[market], "year": str(year - 1911), "season": f"{quarter:02d}"}
    resp = requests.post(_URL.format(report=report), data=data, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def fetch_quarter(year: int, quarter: int, market: str) -> list[dict]:
    """某年某季全市場的損益與權益（年初累計值）。尚未公布時回傳空清單。"""
    income = {r["code"]: r for r in map(normalize_income, parse_tables(_post("t163sb04", year, quarter, market)))}
    if not income:
        return []
    balance = {r["code"]: r for r in map(normalize_balance, parse_tables(_post("t163sb05", year, quarter, market)))}
    cashflow = {r["code"]: r for r in map(normalize_cashflow, parse_tables(_post("t163sb20", year, quarter, market)))}
    rows = []
    for code, row in income.items():
        extra = {**_EMPTY_EXTRA, **balance.get(code, {}), **cashflow.get(code, {})}
        rows.append({**row, **extra, "code": code, "year": year, "quarter": quarter, "market": market})
    return rows


_EMPTY_EXTRA = {"equity": None, "total_assets": None, "total_liabilities": None, "current_assets": None,
                "current_liabilities": None, "operating_cf": None, "investing_cf": None, "financing_cf": None}
