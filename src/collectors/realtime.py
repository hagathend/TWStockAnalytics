"""盤中即時報價：證交所基本市況報導網站（上市、上櫃都有），約 5 秒更新一次。

GET https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|otc_6488.tw&json=1&delay=0

- 不知道股票是上市或上櫃，所以每檔同時查 tse_ 與 otc_，查不到的那一個會回空的代號（c 為空字串），略過即可
- z＝最近成交價；這 5 秒沒有成交時是「-」，改用最佳買價，再沒有就用參考昨收
- y＝昨收、v＝累計成交量（張）、d／t＝資料日期與時間；收盤後查詢會回當天最後一筆
- 請求太頻繁會被暫時封鎖，一次查詢合併多檔，畫面上也限制最短更新間隔
"""

import requests

from src.collectors.twse_official import _HEADERS

_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
_TIMEOUT = 10
_CHUNK = 40  # 每次查詢的股票數（每檔兩個頻道）


def _num(value) -> float | None:
    try:
        number = float(str(value).split("_")[0])
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse(payload: dict) -> dict[str, dict]:
    quotes = {}
    for item in payload.get("msgArray") or []:
        code = str(item.get("c") or "").strip()
        if not code:
            continue
        prev_close = _num(item.get("y"))
        price = _num(item.get("z")) or _num(item.get("b")) or _num(item.get("pz"))
        change = price - prev_close if price is not None and prev_close else None
        date = str(item.get("d") or "")
        quotes[code] = {
            "code": code, "name": item.get("n"), "market": "TWSE" if item.get("ex") == "tse" else "TPEx",
            "price": price, "prev_close": prev_close, "change": change,
            "change_pct": change / prev_close * 100 if change is not None else None,
            "open": _num(item.get("o")), "high": _num(item.get("h")), "low": _num(item.get("l")),
            "volume_lots": _num(item.get("v")),
            "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else None, "time": item.get("t"),
            "limit_up": _num(item.get("u")), "limit_down": _num(item.get("w")),
        }
    return quotes


def fetch_quotes(codes: list[str]) -> tuple[bool, dict[str, dict] | str]:
    codes = list(dict.fromkeys(c for c in codes if c))
    quotes = {}
    try:
        for start in range(0, len(codes), _CHUNK):
            chunk = codes[start:start + _CHUNK]
            channels = "|".join(f"{ex}_{code}.tw" for code in chunk for ex in ("tse", "otc"))
            resp = requests.get(_URL, params={"ex_ch": channels, "json": "1", "delay": "0"},
                                headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            quotes.update(parse(resp.json()))
    except (requests.RequestException, ValueError) as exc:
        return False, f"即時報價讀取失敗（可能查詢太頻繁被暫時擋下，稍後再試）：{exc}"
    return True, quotes
