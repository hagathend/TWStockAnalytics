"""用 Firecrawl API 抓取文章內文，作為 Playwright (article_fetcher.py) 的優先選項。

Firecrawl 是專門的網頁擷取服務，通常比我們自己寫的「找 <article> 標籤」heuristic
更能應付不同網站的頁面結構。免費額度每月 1,000 次，不需要信用卡
（https://www.firecrawl.dev/ 申請 API Key）。沒有設定 Key 或呼叫失敗時，
呼叫端應該優雅降級改用 Playwright。
"""

import requests

_API_URL = "https://api.firecrawl.dev/v2/scrape"
_TIMEOUT = 30
_MAX_CONTENT_LENGTH = 4000


def fetch(url: str, api_key: str) -> str | None:
    """回傳文章內文（markdown格式，best-effort），失敗回傳 None"""
    if not api_key:
        return None
    try:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        markdown = (payload.get("data") or {}).get("markdown", "")
        markdown = markdown.strip()
        return markdown[:_MAX_CONTENT_LENGTH] if markdown else None
    except Exception:  # noqa: BLE001 - 呼叫失敗要優雅降級回退到 Playwright，不中斷整批處理
        return None


def test_connection(api_key: str) -> tuple[bool, str]:
    """驗證 API Key 是否有效：用一個輕量網址測試實際 scrape 呼叫
    （Firecrawl 沒有免費的『驗證用』端點，測試本身會消耗 1 個額度）"""
    if not api_key:
        return False, "尚未輸入 API Key"
    try:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"url": "https://example.com", "formats": ["markdown"]},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 401:
            return False, "API Key 無效"
        resp.raise_for_status()
        return True, "連線成功（此測試會消耗 1 個額度）"
    except Exception as exc:  # noqa: BLE001 - 需要把任何底層例外轉成使用者看得懂的訊息
        return False, f"連線失敗: {exc}"
