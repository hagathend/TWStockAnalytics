"""每日資料收集流程整合：供 Streamlit UI 手動觸發，也供排程腳本呼叫。"""

from datetime import date as _date, timedelta

from src import backfill
from src.collectors import finmind, fundamentals, news_crawler, news_rss, tdcc, twse_official
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


def collect_fundamentals() -> dict:
    """本益比／殖利率／淨值比（每日）與月營收（來源只有最新月份，每天覆寫一次即可）"""
    twse_val = _run_step("TWSE 本益比/殖利率/淨值比", fundamentals.fetch_twse_valuation, db.save_valuation)
    tpex_val = _run_step("TPEx 本益比/殖利率/淨值比", fundamentals.fetch_tpex_valuation, db.save_valuation)
    twse_rev = _run_step("TWSE 月營收", fundamentals.fetch_twse_month_revenue, db.save_month_revenue)
    tpex_rev = _run_step("TPEx 月營收", fundamentals.fetch_tpex_month_revenue, db.save_month_revenue)
    return {"valuation": len(twse_val) + len(tpex_val), "month_revenue": len(twse_rev) + len(tpex_rev)}


def collect_shareholding() -> int:
    """集保股權分散表：每週更新一次，每天抓最新一週覆寫即可（同一週重複抓不會多存）"""
    return len(_run_step("集保股權分散表", tdcc.fetch_shareholding, db.save_shareholding))


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
        "fundamentals": collect_fundamentals(),
        "shareholding": collect_shareholding(),
        "gap_fill": collect_recent_gaps(),
    }
    result["alerts"] = check_alerts_step()
    return result


def check_alerts_step() -> dict:
    """收集完檢查條件提醒並跳 Windows 通知；失敗只記錄，不影響收集結果"""
    from src import alerts  # 延遲匯入：alerts 會載入訊號計算，收集器本身不需要

    try:
        outcome = alerts.check_alerts()
    except Exception as exc:  # noqa: BLE001
        db.log_step("條件提醒檢查", "failed", str(exc))
        return {"new_events": 0}
    db.log_step("條件提醒檢查", "success", outcome["message"])
    return {"new_events": len(outcome["new_events"])}
