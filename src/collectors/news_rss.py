"""Google News RSS：針對特定個股做新聞延伸搜尋（免 API key）。"""

from datetime import datetime
from time import mktime
from urllib.parse import quote

import feedparser

_RSS_URL = "https://news.google.com/rss/search"


def fetch_stock_news(code: str, name: str, limit: int = 10) -> list[dict]:
    """搜尋「代號 名稱」相關新聞，例如 2330 台積電"""
    query = quote(f"{code} {name}")
    url = f"{_RSS_URL}?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(url)

    today = datetime.now().strftime("%Y-%m-%d")
    collected_at = datetime.now().isoformat(timespec="seconds")

    rows = []
    for entry in feed.entries[:limit]:
        published_at = None
        if getattr(entry, "published_parsed", None):
            published_at = datetime.fromtimestamp(
                mktime(entry.published_parsed)
            ).isoformat(timespec="seconds")
        rows.append(
            {
                "date": today,
                "source": "google_news_rss",
                "title": entry.get("title"),
                "url": entry.get("link"),
                "summary": entry.get("summary", "")[:500],
                "related_code": code,
                "published_at": published_at,
                "collected_at": collected_at,
            }
        )
    return rows


def fetch_watchlist_news(watchlist: dict[str, str], limit_per_stock: int = 10) -> list[dict]:
    """對 watchlist 內每檔股票各自搜尋新聞並彙整"""
    rows = []
    for code, name in watchlist.items():
        rows.extend(fetch_stock_news(code, name, limit=limit_per_stock))
    return rows
