"""集保結算所「集保戶股權分散表」：各股依持股張數分級的股東人數與持股比例（每週更新一次）。

來源：https://opendata.tdcc.com.tw/getOD.ashx?id=1-5（CSV，只有最新一週，歷史要靠每週累積）
持股分級：1＝1–999 股 … 12＝400,001–600,000 股、13、14、15＝1,000,001 股以上（千張大戶）、
16＝差異數調整（不用）、17＝合計（總股東人數）。
"""

import csv
import io

import requests

from src.collectors.twse_official import _HEADERS, _to_float, _to_int

URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
_TIMEOUT = 60


def parse_csv(text: str, keep_code=None) -> list[dict]:
    rows = []
    # 開頭若帶 BOM（U+FEFF），第一個欄位名稱會對不上而整份解析不出資料
    for item in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        code = (item.get("證券代號") or "").strip()
        raw_date = (item.get("資料日期") or "").strip()
        level = _to_int(item.get("持股分級"))
        if not code or len(raw_date) != 8 or level is None or level == 16:
            continue
        if keep_code and not keep_code(code):
            continue
        rows.append({
            "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}",
            "code": code,
            "level": level,
            "holders": _to_int(item.get("人數")),
            "shares": _to_int(item.get("股數")),
            "pct": _to_float(item.get("占集保庫存數比例%")),
        })
    return rows


def fetch_shareholding() -> list[dict]:
    """最新一週的股權分散表（只保留個股，ETF／權證不需要）"""
    from src.storage.db import is_stock_code

    resp = requests.get(URL, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_csv(resp.content.decode("utf-8-sig"), keep_code=is_stock_code)
