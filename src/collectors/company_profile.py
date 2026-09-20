"""公司基本資料：公開資訊觀測站舊站「公司基本資料」（t05st03），一次查一家，上市櫃與興櫃都有。

POST https://mopsov.twse.com.tw/mops/web/ajax_t05st03  co_id=代號
OpenAPI 的 t187ap03_L／mopsfin_t187ap03_O 沒有「主要經營業務」，所以改查這一頁。
頁面是一列好幾組「th 標題、td 內容」，逐組配對；民國日期轉西元。
"""

import re

import requests
from bs4 import BeautifulSoup

from src.collectors.twse_official import _HEADERS

_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st03"
_TIMEOUT = 60

# 顯示用欄位：頁面標題（去掉空白後）→ 我們的欄位名
FIELDS = {
    "產業類別": "industry", "公司名稱": "full_name", "董事長": "chairman", "總經理": "president",
    "發言人": "spokesman", "主要經營業務": "business", "公司成立日期": "founded", "上市日期": "listed_twse",
    "上櫃日期": "listed_tpex", "興櫃日期": "listed_emerging", "實收資本額": "capital",
    "已發行普通股數或TDR原股發行股數": "shares", "普通股盈餘分派或虧損撥補頻率": "dividend_frequency",
    "簽證會計師事務所": "auditor", "公司網址": "website", "地址": "address", "英文簡稱": "english_name",
}


_CJK = r"　-〿一-鿿＀-￯"  # 中日韓標點、漢字、全形字元
_CJK_GAP = re.compile(rf"(?<=[{_CJK}])\s+|\s+(?=[{_CJK}])")


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("&nbsp", "")).strip()
    return text


def _roc_to_iso(text: str) -> str:
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if not match:
        return text
    y, m, d = (int(g) for g in match.groups())
    return f"{y + 1911}-{m:02d}-{d:02d}"


def parse(html: str) -> dict | None:
    """回傳 {欄位: 文字}；查無此公司回 None"""
    soup = BeautifulSoup(html, "lxml")
    pairs = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        for head, value in zip(cells, cells[1:]):
            if head.name == "th" and value.name == "td":
                label = re.sub(r"\s+", "", head.get_text())
                pairs.setdefault(label, value.get_text(" ", strip=True))
    if "股票代號" not in pairs:
        return None
    profile = {}
    for label, key in FIELDS.items():
        value = _clean(pairs.get(label, ""))
        if key in ("founded", "listed_twse", "listed_tpex", "listed_emerging"):
            value = _roc_to_iso(value)
        if key == "shares":
            value = value.split("(")[0].strip()  # 後面接「(含私募 0股)」
        if key == "business":
            value = _CJK_GAP.sub("", value)  # 原網頁在中文裡硬換行，轉成空白後要拿掉（英文字之間的空白保留）
        profile[key] = value
    return profile


def fetch(code: str) -> tuple[bool, dict | str]:
    data = {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "queryName": "co_id",
            "inpuType": "co_id", "TYPEK": "all", "co_id": code}
    try:
        resp = requests.post(_URL, data=data, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except requests.RequestException as exc:
        return False, f"公開資訊觀測站連線失敗：{exc}"
    profile = parse(resp.text)
    if profile is None:
        return False, "查無這家公司的基本資料（ETF、權證沒有公司資料）"
    return True, profile
