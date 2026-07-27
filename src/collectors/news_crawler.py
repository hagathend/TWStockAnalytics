"""鉅亨網 (cnyes) 台股新聞收集器，使用其公開 JSON API（免爬 HTML）。"""

import re
from datetime import datetime, timedelta

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 20
_CATEGORY = "tw_stock"  # 台股分類
_CODE_IN_TITLE = re.compile(r"\((\d{4,6}[A-Z]?)\)")


def _extract_code(title: str) -> str | None:
    """從標題如「矽格(6257)子公司...」擷取股票代號，作為粗略的關聯標記。
    精準分類留待第二階段交給 AI 判斷。"""
    match = _CODE_IN_TITLE.search(title or "")
    return match.group(1) if match else None


def fetch_cnyes_news(hours: int = 26, limit: int = 100) -> list[dict]:
    """抓取最近 N 小時內的鉅亨網台股新聞列表。

    hours 預設 26 小時，確保晚上 8 點執行時能涵蓋「今天整個交易日」的新聞。
    """
    now = datetime.now()
    start_at = int((now - timedelta(hours=hours)).timestamp())
    end_at = int(now.timestamp())

    url = f"https://news.cnyes.com/api/v3/news/category/{_CATEGORY}"
    params = {"startAt": start_at, "endAt": end_at, "limit": min(limit, 100)}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("items", {}).get("data", [])
    today = now.strftime("%Y-%m-%d")
    collected_at = now.isoformat(timespec="seconds")

    rows = []
    for item in items:
        news_id = item.get("newsId")
        published_at = None
        if item.get("publishAt"):
            published_at = datetime.fromtimestamp(item["publishAt"]).isoformat(
                timespec="seconds"
            )
        title = item.get("title")
        rows.append(
            {
                "date": today,
                "source": "cnyes",
                "title": title,
                "url": f"https://news.cnyes.com/news/id/{news_id}" if news_id else None,
                "summary": (item.get("summary") or "")[:500],
                "related_code": _extract_code(title),
                "published_at": published_at,
                "collected_at": collected_at,
            }
        )
    return rows
