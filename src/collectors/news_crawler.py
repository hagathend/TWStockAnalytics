"""鉅亨網 (cnyes) 台股新聞收集器，使用其公開 JSON API（免爬 HTML）。

這個 API 的回應本身就包含文章全文（content 欄位，HTML 實體跳脫過的 HTML），
所以不用另外爬網站，直接解析存起來即可，供之後 AI 逐篇摘要用。"""

import html
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 20
_CATEGORY = "tw_stock"  # 台股分類
_CODE_IN_TITLE = re.compile(r"\((\d{4,6}[A-Z]?)\)")
_MAX_CONTENT_LENGTH = 4000
_PAGE_SIZE = 30  # API 一頁最多 30 則
_MAX_PAGES = 10  # 保險上限：一天 300 則已遠超過實際量


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


def _to_row(item: dict, today: str, collected_at: str) -> dict:
    news_id = item.get("newsId")
    published_at = None
    if item.get("publishAt"):
        published_at = datetime.fromtimestamp(item["publishAt"]).isoformat(timespec="seconds")
    title = item.get("title")
    return {
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


def fetch_cnyes_news(hours: int = 26, max_pages: int = _MAX_PAGES, page_delay: float = 0.5) -> list[dict]:
    """抓取最近 N 小時內的鉅亨網台股新聞（逐頁抓到最後一頁）。

    hours 預設 26 小時，確保晚上執行時能涵蓋「今天整個交易日」的新聞。
    API 一頁固定最多 30 則（limit 設更大也沒用），一天約 100～150 則。以前只抓第一頁，
    晚上收集時第一頁剛好都是收盤後的總經／生活新聞，白天的個股新聞全部漏掉。
    """
    now = datetime.now()
    params = {"startAt": int((now - timedelta(hours=hours)).timestamp()), "endAt": int(now.timestamp()),
              "limit": _PAGE_SIZE}
    url = f"https://news.cnyes.com/api/v3/news/category/{_CATEGORY}"
    today = now.strftime("%Y-%m-%d")
    collected_at = now.isoformat(timespec="seconds")

    rows, seen = [], set()
    page, last_page = 1, 1
    while page <= min(last_page, max_pages):
        resp = requests.get(url, headers=_HEADERS, params={**params, "page": page}, timeout=_TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("items", {})
        last_page = items.get("last_page") or 1
        for item in items.get("data", []):
            if item.get("newsId") in seen:  # 翻頁期間有新新聞進來時，前一頁的最後幾則會被擠到下一頁
                continue
            seen.add(item.get("newsId"))
            rows.append(_to_row(item, today, collected_at))
        page += 1
        if page_delay and page <= min(last_page, max_pages):
            time.sleep(page_delay)
    return rows
