"""用當日新聞產生「新聞焦點 Top 20」觀察名單。

三種分析方式：
1. **Ollama（推薦，免費、自動）**：本機跑開源模型，用 structured output 強制 JSON 格式，
   收集資料後可自動觸發，不需要任何 API Key。
2. **複製貼上**：產生提示詞給使用者複製到免費的網頁版 Claude / ChatGPT / Gemini，
   再把回覆貼回來解析。適合沒有裝 Ollama 的情況。
3. **付費 API 直接呼叫**：src/ai_providers.py 的 generate_text，需要使用者自己的付費 Key。
"""

import json
import re

from src.ai_providers import generate_ollama_json, generate_ollama_text
from src.collectors.article_fetcher import ArticleFetcher
from src.storage import db

_MAX_NEWS_ITEMS = 60
_SUMMARY_TRUNCATE = 150

_MAX_CNYES_FOR_DEEP = 15  # 鉅亨網一般市場新聞
_MAX_RSS_FOR_DEEP = 10  # Google News RSS 個股延伸新聞（watchlist個股專屬，數量少但精準要保留）

_ARTICLE_SUMMARY_PROMPT = """請閱讀以下台股新聞內文，用不超過100字的繁體中文摘要重點，
特別留意有沒有提到具體公司名稱/股票代號、影響方向（利多/利空）、關鍵數字（營收、財報、目標價等）。
若內文不完整或只有片段也沒關係，就摘要看得到的部分，直接輸出摘要文字，不要加其他說明。

標題：{title}

內文：
{content}
"""

_DEEP_PROMPT_TEMPLATE = """你是台股新聞分析助手。以下是 {date} 收集到的台股新聞逐篇摘要
（共 {count} 則，每則都已經先針對新聞內文做過摘要）。

請完成以下工作：
1. 用 3-5 句話總結今天新聞的重點主題與市場氣氛
2. 從中挑出最多 20 檔你認為最值得投資人今天關注的個股，依重要程度排序，盡量附上正確的股票代號（若新聞未提供代號，可依你的知識補上；無法判斷代號就不要列入），每檔給不超過 40 字的關注原因

請「只」回傳以下 JSON 格式的內容，不要加上任何說明文字、不要用 markdown code fence 包起來：
{{"summary": "...", "picks": [{{"code": "2330", "name": "台積電", "reason": "..."}}]}}

新聞摘要清單：
{summaries_block}
"""

_PICKS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["code", "name", "reason"],
            },
        },
    },
    "required": ["summary", "picks"],
}

_PROMPT_TEMPLATE = """你是台股新聞分析助手。以下是 {date} 收集到的台股新聞標題與摘要（共 {count} 則）。

請完成以下工作：
1. 用 3-5 句話總結今天新聞的重點主題與市場氣氛
2. 從中挑出最多 20 檔你認為最值得投資人今天關注的個股，依重要程度排序，盡量附上正確的股票代號（若新聞未提供代號，可依你的知識補上；無法判斷代號就不要列入），每檔給不超過 40 字的關注原因

請「只」回傳以下 JSON 格式的內容，不要加上任何說明文字、不要用 markdown code fence 包起來：
{{"summary": "...", "picks": [{{"code": "2330", "name": "台積電", "reason": "..."}}]}}

新聞清單：
{news_block}
"""


def _build_news_block(news_rows: list[dict]) -> str:
    lines = []
    for i, row in enumerate(news_rows[:_MAX_NEWS_ITEMS], start=1):
        summary = (row.get("summary") or "")[:_SUMMARY_TRUNCATE]
        lines.append(f"{i}. {row['title']} — {summary}")
    return "\n".join(lines)


def build_prompt(date: str) -> tuple[bool, str]:
    """回傳 (是否成功, 提示詞文字或錯誤訊息)"""
    news_rows = db.query_news(date)
    if not news_rows:
        return False, "此日期尚無新聞資料，請先收集資料"
    prompt = _PROMPT_TEMPLATE.format(
        date=date, count=len(news_rows), news_block=_build_news_block(news_rows)
    )
    return True, prompt


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    return json.loads(text)


def _verify_pick(code: str, name: str) -> tuple[str, str]:
    """AI 有時會記錯代號和名稱的對應（例如把2454聯發科講成2357），
    但新聞文字通常是用公司名稱而非代號，相對可信，所以用本地資料庫的官方代號/名稱
    對照表校正：代號和名稱對不上時，以名稱回頭查代號為準。"""
    authoritative_name = db.lookup_stock_name(code)
    if authoritative_name and authoritative_name == name:
        return code, name

    corrected_code = db.lookup_stock_code_by_name(name)
    if corrected_code:
        return corrected_code, db.lookup_stock_name(corrected_code) or name

    if authoritative_name:
        return code, authoritative_name

    return code, name


def _normalize_picks(raw_picks: list[dict]) -> list[dict]:
    picks = []
    for i, p in enumerate(raw_picks[:20], start=1):
        code = str(p.get("code", "")).strip()
        code = re.sub(r"\.(TW|TWO|TPEX)$", "", code, flags=re.IGNORECASE)
        name = p.get("name", "")
        code, name = _verify_pick(code, name)
        picks.append(
            {
                "rank": i,
                "code": code,
                "name": name,
                "reason": p.get("reason", ""),
            }
        )
    return picks


def _save_result(date: str, provider_label: str, summary: str, raw_picks: list[dict]) -> dict:
    picks = _normalize_picks(raw_picks)
    db.save_ai_picks(date, picks)
    db.save_ai_analysis_summary(date, provider_label, summary)
    return {"ok": True, "message": "分析結果已儲存", "summary": summary, "picks": picks}


def parse_and_save(date: str, provider_label: str, raw_response: str) -> dict:
    """解析使用者貼回來的 AI 回覆，成功的話存入 DB。
    回傳 {"ok": bool, "message": str, "summary": str, "picks": [...]}"""
    if not raw_response.strip():
        return {"ok": False, "message": "尚未貼上任何內容", "summary": "", "picks": []}

    try:
        parsed = _extract_json(raw_response)
        summary = parsed.get("summary", "")
        raw_picks = parsed.get("picks", [])
    except Exception as exc:  # noqa: BLE001 - 貼上來的內容格式不受控，需要把任何解析例外轉成使用者看得懂的訊息
        return {
            "ok": False,
            "message": f"無法解析回覆內容，請確認有把完整 JSON 貼上（錯誤: {exc}）",
            "summary": "",
            "picks": [],
        }

    return _save_result(date, provider_label, summary, raw_picks)


def analyze_with_ollama(date: str, host: str, model: str) -> dict:
    """呼叫本機 Ollama 自動分析（免費，不需要任何 API Key）。
    回傳 {"ok": bool, "message": str, "summary": str, "picks": [...]}"""
    ok, prompt_or_msg = build_prompt(date)
    if not ok:
        return {"ok": False, "message": prompt_or_msg, "summary": "", "picks": []}

    gen_ok, text = generate_ollama_json(host, model, prompt_or_msg, _PICKS_SCHEMA)
    if not gen_ok:
        return {"ok": False, "message": text, "summary": "", "picks": []}

    try:
        parsed = json.loads(text)
        summary = parsed.get("summary", "")
        raw_picks = parsed.get("picks", [])
    except Exception as exc:  # noqa: BLE001 - Ollama回覆理論上已受schema約束，仍需保護解析失敗的情況
        return {
            "ok": False,
            "message": f"Ollama 回覆的 JSON 無法解析（錯誤: {exc}）\n\n原始回覆:\n{text[:500]}",
            "summary": "",
            "picks": [],
        }

    return _save_result(date, f"ollama:{model}", summary, raw_picks)


def _summarize_article(host: str, model: str, title: str, content: str) -> str:
    """逐篇摘要，失敗時優雅降級直接用標題代替，不中斷整批處理"""
    if not content:
        return title
    prompt = _ARTICLE_SUMMARY_PROMPT.format(title=title, content=content)
    ok, text = generate_ollama_text(host, model, prompt)
    return text if ok else title


def analyze_with_ollama_deep(
    date: str, host: str, model: str, progress_callback=None
) -> dict:
    """深度分析：先幫每則新聞抓內文（鉅亨網已經有、Google News RSS 用 headless 瀏覽器
    解析JS轉址後抓取），逐篇送AI摘要，最後把所有摘要彙整起來再送一次AI挑出前20檔。

    這個做法比 analyze_with_ollama() 準確（qwen2.5:7b 自己沒辦法爬網頁，
    只能靠我們先把內文準備好給它），但因為要逐篇呼叫AI，會慢很多（視新聞則數可能要幾分鐘）。

    progress_callback(current, total, message) 可選，用於UI顯示進度。
    """
    news_rows = db.query_news(date)
    if not news_rows:
        return {"ok": False, "message": "此日期尚無新聞資料，請先收集資料", "summary": "", "picks": []}

    # 分開取鉅亨網一般新聞 + RSS 個股延伸新聞，避免其中一種來源（通常是較多筆的鉅亨網）
    # 把另一種排擠掉——RSS 雖然筆數少，但是針對觀察名單個股的精準新聞，很重要
    cnyes_rows = [r for r in news_rows if r["source"] == "cnyes"][:_MAX_CNYES_FOR_DEEP]
    rss_rows = [r for r in news_rows if r["source"] != "cnyes"][:_MAX_RSS_FOR_DEEP]
    articles = cnyes_rows + rss_rows
    total = len(articles)

    # 先批次抓取缺少內文的新聞（主要是 Google News RSS 來源），共用同一個瀏覽器實例
    needs_fetch = [a for a in articles if not a.get("content") and a.get("url")]
    fetched_content: dict[int, str | None] = {}
    if needs_fetch:
        try:
            with ArticleFetcher() as fetcher:
                for i, article in enumerate(needs_fetch, start=1):
                    fetched_content[article["id"]] = fetcher.fetch(article["url"])
                    if progress_callback:
                        progress_callback(
                            i, len(needs_fetch), f"抓取內文中: {article['title'][:20]}"
                        )
        except Exception:  # noqa: BLE001 - Playwright若因環境問題整批失敗，優雅降級全部改用標題/短摘要
            pass

    summaries = []
    for i, article in enumerate(articles, start=1):
        content = (
            article.get("content")
            or fetched_content.get(article["id"])
            or article.get("summary")
            or ""
        )
        excerpt = _summarize_article(host, model, article["title"], content)
        summaries.append(f"{i}. {article['title']} — {excerpt}")
        if progress_callback:
            progress_callback(i, total, f"摘要中: {article['title'][:20]}")

    prompt = _DEEP_PROMPT_TEMPLATE.format(
        date=date, count=total, summaries_block="\n".join(summaries)
    )

    gen_ok, text = generate_ollama_json(host, model, prompt, _PICKS_SCHEMA)
    if not gen_ok:
        return {"ok": False, "message": text, "summary": "", "picks": []}

    try:
        parsed = json.loads(text)
        summary = parsed.get("summary", "")
        raw_picks = parsed.get("picks", [])
    except Exception as exc:  # noqa: BLE001 - Ollama回覆理論上已受schema約束，仍需保護解析失敗的情況
        return {
            "ok": False,
            "message": f"Ollama 回覆的 JSON 無法解析（錯誤: {exc}）\n\n原始回覆:\n{text[:500]}",
            "summary": "",
            "picks": [],
        }

    return _save_result(date, f"ollama-deep:{model}", summary, raw_picks)
