"""公開資訊觀測站舊站的「月營收彙總表」靜態頁面，用來回補歷史月營收（OpenAPI 只有最新一個月）。

網址：https://mopsov.twse.com.tw/nas/t21/{sii|otc}/t21sc03_{民國年}_{月}_{0|1}.html
- sii＝上市、otc＝上櫃；最後的 0＝國內公司、1＝外國公司（KY 股）
- Big5 編碼；每個產業一個表格，表頭有「產業別：XXX」；金額單位千元
欄位：公司代號、公司名稱、當月營收、上月營收、去年當月營收、上月比較增減(%)、去年同月增減(%)、
當月累計營收、去年累計營收、前期比較增減(%)、備註
"""

import re

import requests
from bs4 import BeautifulSoup

from src.collectors.twse_official import _HEADERS, _to_float, _to_int

_URL = "https://mopsov.twse.com.tw/nas/t21/{board}/t21sc03_{roc_year}_{month}_{kind}.html"
_BOARDS = {"TWSE": "sii", "TPEx": "otc"}
_CODE_PATTERN = re.compile(r"\d{4}[A-Z]?")
_TIMEOUT = 60


def parse_page(html: str, year_month: str, market: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows, seen = [], set()
    for header in soup.find_all("th", string=re.compile("產業別")):
        industry = header.get_text(strip=True).split("：", 1)[-1]
        table = header.find_parent("table")
        if table is None:
            continue
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 10 or not _CODE_PATTERN.fullmatch(cells[0]) or cells[0] in seen:
                continue
            seen.add(cells[0])
            rows.append({
                "year_month": year_month, "market": market, "code": cells[0], "name": cells[1],
                "industry": industry,
                "revenue": _to_int(cells[2]), "revenue_last_month": _to_int(cells[3]),
                "revenue_last_year": _to_int(cells[4]), "mom_pct": _to_float(cells[5]),
                "yoy_pct": _to_float(cells[6]), "cum_revenue": _to_int(cells[7]),
                "cum_revenue_last_year": _to_int(cells[8]), "cum_yoy_pct": _to_float(cells[9]),
            })
    return rows


def fetch_month(year: int, month: int, market: str) -> list[dict]:
    """某月某市場的全部公司月營收（國內＋外國公司）。該月尚未公布時回傳空清單。"""
    year_month = f"{year}-{month:02d}"
    rows = []
    for kind in (0, 1):
        url = _URL.format(board=_BOARDS[market], roc_year=year - 1911, month=month, kind=kind)
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        rows += parse_page(resp.content.decode("big5", errors="replace"), year_month, market)
    return rows
