"""補收集上市（TWSE）歷史資料：股價、三大法人、融資融券。

選股篩選器、籌碼延伸指標、回測都需要一段連續歷史（例如 MA60、法人連買天數、20日後報酬），
但本地資料庫只有「有收集的那幾天」。TWSE 的 rwd 介面可以指定任意過去日期查詢，所以補得回來。
（TPEx 的 OpenAPI 只給「最新一筆」，沒辦法補過去的日期，這裡不處理。）

設計重點：
- **可中斷續跑**：三張表都已經有資料的日期直接跳過，跑到一半中斷再執行會從缺的地方接著補
- **非交易日只問一次**：過去日期查無股價 → 記進 trading_calendar，之後直接跳過
- **今天（含以後）不標記非交易日**：盤後資料可能還沒公布，查無資料不代表休市
- **網路錯誤不等於休市**：抓取拋例外時只記 log，不寫進 calendar，下次會重試
- **對 TWSE 客氣**：每個請求之間固定間隔，TWSE 對短時間大量請求會暫時封鎖 IP
"""

import time
from datetime import date as _date, timedelta

from src.collectors import twse_official
from src.storage import db

DEFAULT_SLEEP_SECONDS = 3.0
_MARKET = "TWSE"


def iter_weekdays(start: _date, end: _date):
    """由新到舊產生 start~end（含）之間的平日；週末台股不開盤，不必發請求"""
    current = end
    while current >= start:
        if current.weekday() < 5:
            yield current
        current -= timedelta(days=1)


def backfill_twse(start: _date, end: _date, sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
                  progress=None, today: _date | None = None) -> dict:
    """補收集 start~end 之間缺的上市資料。

    progress(message: str) 可選，每處理一天回報一次。
    回傳統計：{"filled": 補到的交易日數, "skipped": 已完整跳過, "non_trading": 非交易日,
              "failed": 失敗的日期清單, "requests": 實際發出的請求數}
    """
    db.init_db()
    today = today or _date.today()

    have_price = db.query_dates_with_data("stock_price", _MARKET)
    have_inst = db.query_dates_with_data("institutional", _MARKET)
    have_margin = db.query_dates_with_data("margin", _MARKET)
    non_trading = db.query_non_trading_dates(_MARKET)

    stats = {"filled": 0, "skipped": 0, "non_trading": 0, "failed": [], "requests": 0}
    first_request = True

    def _polite_call(fetch, yyyymmdd):
        nonlocal first_request
        if not first_request and sleep_seconds:
            time.sleep(sleep_seconds)
        first_request = False
        stats["requests"] += 1
        return fetch(yyyymmdd)

    for day in iter_weekdays(start, end):
        iso = day.isoformat()
        yyyymmdd = day.strftime("%Y%m%d")

        if iso in non_trading:
            stats["non_trading"] += 1
            continue
        if iso in have_price and iso in have_inst and iso in have_margin:
            stats["skipped"] += 1
            continue

        try:
            price_rows = [] if iso in have_price else _polite_call(twse_official.fetch_twse_price, yyyymmdd)

            if iso not in have_price and not price_rows:
                if day < today:
                    db.mark_trading_day(iso, False, _MARKET)
                    stats["non_trading"] += 1
                    if progress:
                        progress(f"{iso} 非交易日")
                elif progress:
                    progress(f"{iso} 尚未公布，略過")
                continue

            db.save_stock_price(price_rows)
            db.mark_trading_day(iso, True, _MARKET)

            counts = {"價量": len(price_rows) if price_rows else "已有"}
            if iso not in have_inst:
                inst_rows = _polite_call(twse_official.fetch_twse_institutional, yyyymmdd)
                db.save_institutional(inst_rows)
                counts["法人"] = len(inst_rows)
            if iso not in have_margin:
                margin_rows = _polite_call(twse_official.fetch_twse_margin, yyyymmdd)
                db.save_margin(margin_rows)
                counts["融資券"] = len(margin_rows)

            detail = "、".join(f"{k} {v}" for k, v in counts.items())
            db.log_step(f"補收集 TWSE {iso}", "success", detail)
            stats["filled"] += 1
            if progress:
                progress(f"{iso} 補齊（{detail}）")
        except Exception as exc:  # noqa: BLE001 - 單日失敗不中斷整批，也不寫進 calendar（下次重試）
            db.log_step(f"補收集 TWSE {iso}", "failed", str(exc))
            stats["failed"].append(iso)
            if progress:
                progress(f"{iso} 失敗：{exc}")

    return stats


def fill_recent_gaps(lookback_days: int = 14, sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
                     today: _date | None = None) -> dict:
    """每日收集後自動補最近幾天漏掉的交易日（例如排程沒觸發的日子）。

    範圍只到昨天：今天的資料由每日收集本身負責，而且盤後可能還沒公布。
    非交易日已記在 calendar、完整的日期會跳過，所以正常情況下幾乎不會發出任何請求。
    """
    today = today or _date.today()
    return backfill_twse(
        today - timedelta(days=lookback_days),
        today - timedelta(days=1),
        sleep_seconds=sleep_seconds,
        today=today,
    )
