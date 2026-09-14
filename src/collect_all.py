"""每日資料收集流程整合：供 Streamlit UI 手動觸發，也供排程腳本呼叫。"""

from datetime import date as _date, timedelta

from src import backfill
from src.collectors import finmind, news_crawler, news_rss, twse_official
from src.config import WATCHLIST
from src.storage import db


def _run_step(step_name: str, func, save_func=None):
    """執行單一收集步驟並記錄結果。

    狀態分三種，不要把「查無資料」混進 success——否則週末/假日或來源尚未公布時，
    log 看起來一切正常，實際上什麼都沒收到，很容易誤判（曾經就這樣看漏過）。
    """
    try:
        rows = func()
        if save_func:
            save_func(rows)
        if not rows:
            db.log_step(step_name, "no_data", "查無資料（可能非交易日，或資料來源尚未公布）")
        else:
            db.log_step(step_name, "success", f"{len(rows)} 筆")
        return rows
    except Exception as exc:  # noqa: BLE001 - 收集流程需要各步驟獨立容錯，不能因單一來源失敗中斷整體
        db.log_step(step_name, "failed", str(exc))
        return []


def collect_stock_price() -> dict:
    twse_rows = _run_step("TWSE 上市價量", twse_official.fetch_twse_price, db.save_stock_price)
    tpex_rows = _run_step("TPEx 上櫃價量", twse_official.fetch_tpex_price, db.save_stock_price)
    return {"twse": len(twse_rows), "tpex": len(tpex_rows)}


def collect_institutional() -> dict:
    twse_rows = _run_step(
        "TWSE 三大法人買賣超", twse_official.fetch_twse_institutional, db.save_institutional
    )
    tpex_rows = _run_step(
        "TPEx 三大法人買賣超", twse_official.fetch_tpex_institutional, db.save_institutional
    )
    return {"twse": len(twse_rows), "tpex": len(tpex_rows)}


def collect_margin() -> dict:
    twse_rows = _run_step("TWSE 融資融券", twse_official.fetch_twse_margin, db.save_margin)
    tpex_rows = _run_step("TPEx 融資融券", twse_official.fetch_tpex_margin, db.save_margin)
    return {"twse": len(twse_rows), "tpex": len(tpex_rows)}


def collect_finmind_watchlist(days_back: int = 7) -> int:
    """對 watchlist 個股用 FinMind 抓取近期價量，作為官方資料的交叉比對"""
    end_date = _date.today().isoformat()
    start_date = (_date.today() - timedelta(days=days_back)).isoformat()

    total = 0
    for code in WATCHLIST:
        try:
            rows = finmind.fetch_stock_price(code, start_date, end_date)
            total += len(rows)
            if not rows:
                db.log_step(f"FinMind 價量 {code}", "no_data", "查無資料")
            else:
                db.log_step(f"FinMind 價量 {code}", "success", f"{len(rows)} 筆")
        except Exception as exc:  # noqa: BLE001
            db.log_step(f"FinMind 價量 {code}", "failed", str(exc))
    return total


def collect_news() -> dict:
    cnyes_rows = _run_step(
        "鉅亨網新聞", news_crawler.fetch_cnyes_news, db.save_news
    )
    rss_rows = _run_step(
        "Google News RSS (watchlist)",
        lambda: news_rss.fetch_watchlist_news(WATCHLIST),
        db.save_news,
    )
    return {"cnyes": len(cnyes_rows), "rss": len(rss_rows)}


def collect_recent_gaps() -> dict:
    """自動補最近兩週漏掉的上市交易日（例如排程沒觸發、當天來源故障的日子）。

    已完整的日期與已知非交易日會跳過，正常情況下幾乎不發請求；
    失敗不影響其他收集步驟，下次執行會自動重試。"""
    try:
        stats = backfill.fill_recent_gaps()
    except Exception as exc:  # noqa: BLE001 - 補缺失敗不能中斷每日收集
        db.log_step("自動補齊近期缺漏交易日", "failed", str(exc))
        return {"filled": 0, "failed": 1}
    # 沒有缺漏是健康狀態，記 success；不要記成 no_data，否則看起來像出問題
    status = "failed" if stats["failed"] else "success"
    detail = (f"補齊 {stats['filled']} 天、失敗 {len(stats['failed'])} 天、請求 {stats['requests']} 次"
              if stats["filled"] or stats["failed"] else "近期無缺漏")
    db.log_step("自動補齊近期缺漏交易日", status, detail)
    return {"filled": stats["filled"], "failed": len(stats["failed"])}


def run_daily_collect() -> dict:
    """完整每日收集流程：股價、三大法人、融資融券、新聞，最後自動補近期缺漏的交易日"""
    db.init_db()
    result = {
        "price": collect_stock_price(),
        "institutional": collect_institutional(),
        "margin": collect_margin(),
        "finmind": collect_finmind_watchlist(),
        "news": collect_news(),
        "gap_fill": collect_recent_gaps(),
    }
    return result
