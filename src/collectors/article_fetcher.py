"""用 headless 瀏覽器 (Playwright) 解析 Google News RSS 連結。

Google News RSS 給的連結是 news.google.com 的中介頁面，要靠 JavaScript
才會轉址到真正的新聞網站，單純用 requests 抓不到轉址後的內容。
不同新聞網站頁面結構不一樣，用「先找 <article> 標籤、找不到就退回抓整個 body」
的方式盡量取得乾淨的內文，這是 best-effort，不保證每個網站都能抓乾淨。
"""

from playwright.sync_api import sync_playwright

_MAX_CONTENT_LENGTH = 4000
_GOTO_TIMEOUT_MS = 20000
_SETTLE_WAIT_MS = 1500


class ArticleFetcher:
    """重複使用同一個瀏覽器實例抓多篇文章，避免每篇都重新啟動瀏覽器（啟動成本較高）。

    用法:
        with ArticleFetcher() as fetcher:
            text = fetcher.fetch(url)
    """

    def __enter__(self) -> "ArticleFetcher":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        return self

    def __exit__(self, *exc_info):
        self._browser.close()
        self._playwright.stop()

    def fetch(self, url: str) -> str | None:
        """回傳文章內文（best-effort），失敗回傳 None（呼叫端應該優雅降級用標題/摘要代替）"""
        page = None
        try:
            page = self._browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
            page.wait_for_timeout(_SETTLE_WAIT_MS)

            article = page.query_selector("article")
            text = article.inner_text() if article else page.inner_text("body")
            text = text.strip()
            return text[:_MAX_CONTENT_LENGTH] if text else None
        except Exception:  # noqa: BLE001 - 各家新聞網站結構不同，任何失敗都優雅降級，不中斷整批處理
            return None
        finally:
            if page:
                page.close()
