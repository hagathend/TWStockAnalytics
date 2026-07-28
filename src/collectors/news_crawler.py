"""鉅亨網 (cnyes) 台股新聞收集器，使用其公開 JSON API（免爬 HTML）。

這個 API 的回應本身就包含文章全文（content 欄位，HTML 實體跳脫過的 HTML），
所以不用另外爬網站，直接解析存起來即可，供之後 AI 逐篇摘要用。"""

import html
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 20
_CATEGORY = "tw_stock"  # 台股分類
_CODE_IN_TITLE = re.compile(r"\((\d{4,6}[A-Z]?)\)")
_MAX_CONTENT_LENGTH = 4000


def _extract_code(title: str) -> str | None:
    """從標題如「矽格(6257)子公司...」擷取股票代號，作為粗略的關聯標記。
    精準分類留待第二階段交給 AI 判斷。"""
    match = _CODE_IN_TITLE.search(title or "")
    return match.group(1) if match else None


def _extract_content_text(raw_content: str) -> str:
    """content 欄位是 HTML 實體跳脫過的 HTML（例如 &lt;p&gt;...&lt;/p&gt;），
    要先反跳脫還原成真正的 HTML 標籤，再用 BeautifulSoup 去標籤取純文字。"""
    if not raw_content:
        return ""
    unescaped = html.unescape(raw_content)
    text = BeautifulSoup(unescaped, "html.parser").get_text(separator=" ", strip=True)
    return text[:_MAX_CONTENT_LENGTH]


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
                "content": _extract_content_text(item.get("content", "")),
                "related_code": _extract_code(title),
                "published_at": published_at,
                "collected_at": collected_at,
            }
        )
    return rows
