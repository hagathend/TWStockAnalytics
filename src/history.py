"""歷史查詢：把期間內的新聞焦點與 AI 預測整理成好查的表（頁面在 app.py 的 history_page）。"""

import pandas as pd

from src import prediction_views
from src.storage import db


def pick_frequency(picks: list[dict]) -> pd.DataFrame:
    """期間內每檔股票上新聞焦點的次數、最佳排名、第一次與最近一次出現日（次數多→排名好→最近出現的排前面）"""
    columns = ["code", "name", "count", "best_rank", "first_date", "last_date", "last_reason"]
    if not picks:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(picks).sort_values(["date", "rank"], ascending=[False, True])
    grouped = df.groupby("code", sort=False)
    result = pd.DataFrame({
        "name": grouped["name"].first(),
        "count": grouped.size(),
        "best_rank": grouped["rank"].min(),
        "first_date": grouped["date"].min(),
        "last_date": grouped["date"].max(),
        "last_reason": grouped["reason"].first(),
    }).reset_index()
    return result.sort_values(["count", "best_rank", "last_date"], ascending=[False, True, False])[columns].reset_index(drop=True)


def _matches(result: dict, keyword: str) -> bool:
    keyword = keyword.strip()
    return not keyword or keyword in result["code"] or keyword in (result.get("name") or "")


def search_views(start: str, end: str, keyword: str | None = None, direction: str | None = None,
                 status: str | None = None, views: list[dict] | None = None) -> list[dict]:
    """期間內（依觀點開始日）的 AI 觀點與成績。status：active／done／too_short／no_data；direction：偏多／偏空／中性"""
    results = []
    for result in prediction_views.build_views() if views is None else views:
        if not start <= result["start_date"] <= end or not _matches(result, keyword or ""):
            continue
        if direction and result["direction"] != direction:
            continue
        if status and result["status"] != status:
            continue
        results.append(result)
    return results


def analysis_text(date: str, code: str) -> str | None:
    """某天某檔的個股分析全文"""
    rows = db.query_stock_analysis(date, code)
    return rows[0]["analysis"] if rows else None
