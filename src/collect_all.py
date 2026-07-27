"""每日資料收集流程整合：供 Streamlit UI 手動觸發，也供排程腳本呼叫。"""

from datetime import date as _date, timedelta

from src.collectors import finmind, news_crawler, news_rss, twse_official
from src.config import WATCHLIST
from src.storage import db


def _run_step(step_name: str, func, save_func=None):
    try:
        rows = func()
        if save_func:
            save_func(rows)
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


def run_daily_collect() -> dict:
    """完整每日收集流程：股價、三大法人、融資融券、新聞"""
    db.init_db()
    result = {
        "price": collect_stock_price(),
        "institutional": collect_institutional(),
        "margin": collect_margin(),
        "finmind": collect_finmind_watchlist(),
        "news": collect_news(),
    }
    return result
