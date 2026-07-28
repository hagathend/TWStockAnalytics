"""把每日報告的 Markdown 文字轉成 PDF。

重複使用已經為了解析 Google News RSS 而安裝的 Playwright/Chromium
（見 src/collectors/article_fetcher.py），不需要額外安裝 wkhtmltopdf 之類的外部工具：
Markdown 轉 HTML 後，用 Chromium 的「列印成 PDF」功能輸出。
"""

import markdown as md_lib
from playwright.sync_api import sync_playwright

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    font-family: "Microsoft JhengHei", "PMingLiU", "Noto Sans TC", sans-serif;
    font-size: 13px;
    line-height: 1.7;
    color: #222;
    padding: 10px 20px;
}}
h1 {{ font-size: 20px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ font-size: 16px; margin-top: 22px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }}
h3 {{ font-size: 14px; margin-top: 16px; color: #444; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ccc; padding: 5px 8px; text-align: left; font-size: 11px; }}
th {{ background: #f0f0f0; }}
em {{ color: #777; font-size: 11px; }}
</style>
</head>
<body>
{content}
</body>
</html>
"""


def markdown_to_pdf(report_markdown: str) -> bytes:
    """把報告的 Markdown 文字轉成 PDF bytes，可直接餵給 st.download_button"""
    html_body = md_lib.markdown(report_markdown, extensions=["tables"])
    full_html = _HTML_TEMPLATE.format(content=html_body)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(full_html, wait_until="load")
        pdf_bytes = page.pdf(
            format="A4",
            margin={"top": "18mm", "bottom": "18mm", "left": "15mm", "right": "15mm"},
        )
        browser.close()
    return pdf_bytes
