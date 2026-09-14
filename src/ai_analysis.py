"""用當日新聞產生「新聞焦點 Top 20」觀察名單。

分析方式：
1. **Ollama 深度分析（推薦，免費、自動）**：本機跑開源模型，逐篇抓內文摘要後彙整挑股，
   收集資料後可自動觸發，不需要任何 API Key。
2. **雲端 API 深度分析（Gemini/Claude/GPT）**：跟 Ollama 同一套「抓內文→逐篇摘要→彙整挑股」
   流程，只是摘要/挑股呼叫換成雲端 API。Gemini 有真正免費的額度（不用綁信用卡），
   Claude/GPT 是另外計費的付費 API。都需要先在「AI 設定」頁填 Key。
3. **複製貼上**：產生提示詞給使用者複製到免費的網頁版 Claude / ChatGPT / Gemini，
   再把回覆貼回來解析。適合完全不想接任何 API 的情況。
"""

import json
import re
import time

from src.ai_providers import generate_ollama_json, generate_ollama_text, generate_text
from src.collectors import firecrawl_fetcher
from src.collectors.article_fetcher import ArticleFetcher
from src.config_ai import load_scraping_settings
from src.storage import db

_MAX_NEWS_ITEMS = 60
_SUMMARY_TRUNCATE = 150

_MAX_CNYES_FOR_DEEP = 40  # 鉅亨網一般市場新聞：涵蓋整個大盤，篇數多才能覆蓋到夠多不同的公司
_MAX_RSS_FOR_DEEP = 15  # Google News RSS 個股延伸新聞（只涵蓋watchlist那幾檔，篇數增加不太會擴大公司覆蓋範圍，保留少量即可）

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

# 新聞篇數多的時候，一次把所有摘要塞進同一個提示詞會讓模型表現變差
# （實測55篇摘要塞在一起，qwen2.5:7b 只挑出2檔、還漂移成簡體字輸出）。
# 改成分批：每批只找候選個股（不用湊到20檔，找到多少算多少），批次之間去重後，
# 再用一次「候選清單→最終20檔」的呼叫做排序，這樣每次進模型的內容都不會太長。
_BATCH_SIZE = 15

_BATCH_PICKS_SCHEMA = {
    "type": "object",
    "properties": {
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
    "required": ["picks"],
}

_BATCH_PICKS_PROMPT = """以下是幾則台股新聞摘要。

請「列出」這些摘要中每一個有明確提到具體公司名稱或股票代號、且帶有實質內容
（例如：財報數字、法說會、合作案、股價異動、目標價等）的個股。不要因為覺得
「不夠重要」就自己先篩掉——只要摘要有明確提到某家公司的具體消息就列出來，
重要性判斷留給後續步驟處理。同一則新聞如果提到多家公司，都要列出來。

盡量附上正確的股票代號，每檔給不超過 40 字的摘要原因。只有在這批摘要完全沒有
提到任何具體公司時，才回傳空陣列。

請「只」回傳以下 JSON 格式的內容，不要加上任何說明文字：
{{"picks": [{{"code": "2330", "name": "台積電", "reason": "..."}}]}}

新聞摘要：
{batch_block}
"""

_FINAL_RANK_PROMPT = """你是台股新聞分析助手。以下是根據 {date} 新聞整理出的候選個股清單
（共 {count} 檔，每一檔都已經有實際新聞依據，這是篩選過的候選名單，不是原始新聞）。

請完成以下工作：
1. 用 3-5 句話總結今天新聞的重點主題與市場氣氛
2. 把清單中「每一檔」個股都納入最終結果（最多列出 20 檔），依重要程度排序。
   只有在確定兩檔是同一家公司重複時才合併，不要因為主觀覺得某檔「不夠重要」
   就自己刪減——這份候選清單已經是篩選過的結果，原則上都要保留

請「只」回傳以下 JSON 格式的內容，不要加上任何說明文字、不要用 markdown code fence 包起來：
{{"summary": "...", "picks": [{{"code": "2330", "name": "台積電", "reason": "..."}}]}}

候選個股清單：
{candidates_block}
"""

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
        code = re.sub(r"[.\-](TW|TWO|TPEX)$", "", code, flags=re.IGNORECASE)
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


def _dedup_candidates(raw_candidates: list[dict]) -> list[dict]:
    """依代號去重複，同一代號只留第一次出現的（不同批次講同一檔股票，原因通常大同小異）"""
    seen = set()
    deduped = []
    for c in raw_candidates:
        code = str(c.get("code", "")).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        deduped.append(c)
    return deduped


def _select_top_picks(date: str, summaries: list[str], call_llm) -> tuple[str | None, str, list[dict]]:
    """從逐篇摘要中挑出最終的前20檔個股。

    call_llm(prompt, schema) -> (是否成功, 文字內容或錯誤訊息)。schema 是 dict，
    Ollama 用來強制輸出格式；雲端 API（沒有 structured output）可以忽略這個參數。

    篇數不多時直接一次彙整；篇數多的話（實測超過20篇左右）改成分批只找候選個股、
    去重後再用一次「候選清單→最終20檔」彙整，避免一次塞太多內容讓模型表現變差
    （曾經實測55篇摘要一次彙整，模型只挑出2檔還漂移成簡體字輸出）。

    回傳 (錯誤訊息或None, 總結文字, 原始picks清單)"""
    if len(summaries) <= _BATCH_SIZE:
        prompt = _DEEP_PROMPT_TEMPLATE.format(
            date=date, count=len(summaries), summaries_block="\n".join(summaries)
        )
        ok, text = call_llm(prompt, _PICKS_SCHEMA)
        if not ok:
            return text, "", []
        try:
            parsed = _extract_json(text)
        except Exception as exc:  # noqa: BLE001 - 需要把任何解析例外轉成使用者看得懂的訊息
            return f"回覆的 JSON 無法解析（錯誤: {exc}）\n\n原始回覆:\n{text[:500]}", "", []
        return None, parsed.get("summary", ""), parsed.get("picks", [])

    batches = [summaries[i : i + _BATCH_SIZE] for i in range(0, len(summaries), _BATCH_SIZE)]
    raw_candidates = []
    for batch in batches:
        batch_prompt = _BATCH_PICKS_PROMPT.format(batch_block="\n".join(batch))
        ok, text = call_llm(batch_prompt, _BATCH_PICKS_SCHEMA)
        if not ok:
            continue  # 單一批次失敗就跳過，不中斷整體分析
        try:
            parsed = _extract_json(text)
        except Exception:  # noqa: BLE001 - 單一批次解析失敗，優雅跳過
            continue
        # 這裡就先校正代號/名稱（而不是等到最終結果才校正），
        # 這樣候選清單本身是乾淨的，最後彙整排序時模型看到的資訊才一致
        for p in parsed.get("picks", []):
            code = re.sub(r"[.\-](TW|TWO|TPEX)$", "", str(p.get("code", "")).strip(), flags=re.IGNORECASE)
            name = p.get("name", "")
            code, name = _verify_pick(code, name)
            raw_candidates.append({"code": code, "name": name, "reason": p.get("reason", "")})

    candidates = _dedup_candidates(raw_candidates)
    if not candidates:
        return "分批分析後沒有找到任何候選個股", "", []

    candidates_block = "\n".join(
        f"{c.get('code', '')} {c.get('name', '')} — {c.get('reason', '')}" for c in candidates
    )
    prompt = _FINAL_RANK_PROMPT.format(
        date=date, count=len(candidates), candidates_block=candidates_block
    )
    ok, text = call_llm(prompt, _PICKS_SCHEMA)
    if not ok:
        return text, "", []
    try:
        parsed = _extract_json(text)
    except Exception as exc:  # noqa: BLE001 - 需要把任何解析例外轉成使用者看得懂的訊息
        return f"回覆的 JSON 無法解析（錯誤: {exc}）\n\n原始回覆:\n{text[:500]}", "", []
    return None, parsed.get("summary", ""), parsed.get("picks", [])


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


def _fetch_missing_content(articles: list[dict], progress_callback=None) -> dict[int, str | None]:
    """抓取缺少內文的新聞（主要是 Google News RSS 來源）。
    優先用 Firecrawl（如果有設定 API Key，免費額度每月1000次，抓取品質通常較好），
    抓不到或沒設定 Key 的部分，退回本機 Playwright（免費、無次數限制但較慢）。"""
    if not articles:
        return {}

    fetched: dict[int, str | None] = {}
    remaining = articles

    firecrawl_key = load_scraping_settings().get("firecrawl_api_key", "")
    if firecrawl_key:
        remaining = []
        for i, article in enumerate(articles, start=1):
            content = firecrawl_fetcher.fetch(article["url"], firecrawl_key)
            if content:
                fetched[article["id"]] = content
            else:
                remaining.append(article)  # Firecrawl 抓不到的，留給 Playwright 再試一次
            if progress_callback:
                progress_callback(i, len(articles), f"Firecrawl 抓取中: {article['title'][:20]}")

    if remaining:
        try:
            with ArticleFetcher() as fetcher:
                for i, article in enumerate(remaining, start=1):
                    fetched[article["id"]] = fetcher.fetch(article["url"])
                    if progress_callback:
                        progress_callback(
                            i, len(remaining), f"Playwright 抓取中: {article['title'][:20]}"
                        )
        except Exception:  # noqa: BLE001 - Playwright若因環境問題整批失敗，優雅降級全部改用標題/短摘要
            pass

    return fetched


def _gather_and_summarize(
    date: str, summarize_fn, progress_callback=None, inter_call_delay: float = 0.0
) -> tuple[str | None, list[str], list[dict]]:
    """深度分析共用的第一階段：取每則新聞的內文（鉅亨網已經有、Google News RSS 用
    headless 瀏覽器解析JS轉址後抓取），逐篇呼叫 summarize_fn(title, content) -> str 摘要。

    summarize_fn 是唯一跟供應商相關的部分（Ollama本機 / Gemini / Claude / GPT），
    抓內文與批次處理邏輯都共用，避免每個供應商各寫一份。

    inter_call_delay：每次呼叫 summarize_fn 之間的間隔秒數，付費/雲端 API 有請求頻率限制時用。

    回傳 (錯誤訊息或None, 逐篇摘要文字清單, article_excerpts清單)"""
    news_rows = db.query_news(date)
    if not news_rows:
        return "此日期尚無新聞資料，請先收集資料", [], []

    # 分開取鉅亨網一般新聞 + RSS 個股延伸新聞，避免其中一種來源（通常是較多筆的鉅亨網）
    # 把另一種排擠掉——RSS 雖然筆數少，但是針對觀察名單個股的精準新聞，很重要
    cnyes_rows = [r for r in news_rows if r["source"] == "cnyes"][:_MAX_CNYES_FOR_DEEP]
    rss_rows = [r for r in news_rows if r["source"] != "cnyes"][:_MAX_RSS_FOR_DEEP]
    articles = cnyes_rows + rss_rows
    total = len(articles)

    # 先批次抓取缺少內文的新聞（主要是 Google News RSS 來源）
    needs_fetch = [a for a in articles if not a.get("content") and a.get("url")]
    fetched_content = _fetch_missing_content(needs_fetch, progress_callback)

    summaries = []
    article_excerpts = []
    for i, article in enumerate(articles, start=1):
        content = (
            article.get("content")
            or fetched_content.get(article["id"])
            or article.get("summary")
            or ""
        )
        excerpt = summarize_fn(article["title"], content) if content else article["title"]
        summaries.append(f"{i}. {article['title']} — {excerpt}")
        db.save_news_excerpt(article["id"], excerpt)
        article_excerpts.append(
            {
                "title": article["title"],
                "url": article.get("url"),
                "source": article["source"],
                "excerpt": excerpt,
            }
        )
        if progress_callback:
            progress_callback(i, total, f"摘要中: {article['title'][:20]}")
        if inter_call_delay and i < total:
            time.sleep(inter_call_delay)

    return None, summaries, article_excerpts


def analyze_with_ollama_deep(
    date: str, host: str, model: str, progress_callback=None
) -> dict:
    """深度分析（本機 Ollama 版）：先幫每則新聞抓內文，逐篇送AI摘要，
    最後把所有摘要彙整起來再送一次AI挑出前20檔。

    這個做法比 analyze_with_ollama() 準確（qwen2.5:7b 自己沒辦法爬網頁，
    只能靠我們先把內文準備好給它），但因為要逐篇呼叫AI，會慢很多（視新聞則數可能要幾分鐘）。

    progress_callback(current, total, message) 可選，用於UI顯示進度。
    """

    def _summarize(title: str, content: str) -> str:
        prompt = _ARTICLE_SUMMARY_PROMPT.format(title=title, content=content)
        ok, text = generate_ollama_text(host, model, prompt)
        return text if ok else title

    error, summaries, article_excerpts = _gather_and_summarize(
        date, _summarize, progress_callback
    )
    if error:
        return {"ok": False, "message": error, "summary": "", "picks": []}

    def _call_llm(prompt: str, schema: dict) -> tuple[bool, str]:
        return generate_ollama_json(host, model, prompt, schema)

    error, summary, raw_picks = _select_top_picks(date, summaries, _call_llm)
    if error:
        return {
            "ok": False,
            "message": error,
            "summary": "",
            "picks": [],
            "article_excerpts": article_excerpts,
        }

    result = _save_result(date, f"ollama-deep:{model}", summary, raw_picks)
    result["article_excerpts"] = article_excerpts
    return result


# 雲端 API（Gemini 免費額度 / Claude、GPT 付費）沒有像 Ollama 一樣可以強制 JSON schema，
# 每次呼叫之間留一點間隔避免碰到免費額度的請求頻率限制
_PAID_API_INTER_CALL_DELAY = 2.0


def analyze_deep_with_provider(
    date: str, provider: str, api_key: str, progress_callback=None
) -> dict:
    """深度分析（雲端 API 版：Gemini/Claude/GPT）：跟 analyze_with_ollama_deep 同一套
    「抓內文→逐篇摘要→彙整挑股」流程，只是換成呼叫 src/ai_providers.py 的付費/免費雲端 API。
    Gemini 有真正免費額度（不用綁信用卡），Claude/GPT 是計費API。

    progress_callback(current, total, message) 可選，用於UI顯示進度。
    """

    def _summarize(title: str, content: str) -> str:
        prompt = _ARTICLE_SUMMARY_PROMPT.format(title=title, content=content)
        ok, text = generate_text(provider, api_key, prompt, max_tokens=300)
        return text if ok else title

    error, summaries, article_excerpts = _gather_and_summarize(
        date, _summarize, progress_callback, inter_call_delay=_PAID_API_INTER_CALL_DELAY
    )
    if error:
        return {"ok": False, "message": error, "summary": "", "picks": []}

    def _call_llm(prompt: str, schema: dict) -> tuple[bool, str]:
        return generate_text(provider, api_key, prompt, max_tokens=3000)

    error, summary, raw_picks = _select_top_picks(date, summaries, _call_llm)
    if error:
        return {
            "ok": False,
            "message": error,
            "summary": "",
            "picks": [],
            "article_excerpts": article_excerpts,
        }

    result = _save_result(date, f"{provider}-deep", summary, raw_picks)
    result["article_excerpts"] = article_excerpts
    return result


def analyze_with_codex_deep(date: str, progress_callback=None) -> dict:
    """Codex CLI 摘要與挑股，失敗時保留既有總結及觀察名單。"""
    from src.codex_cli import generate_codex_text

    def summarize(title, content):
        ok, text = generate_codex_text(_ARTICLE_SUMMARY_PROMPT.format(title=title, content=content))
        if not ok:
            raise RuntimeError(text)
        return text

    def call_llm(prompt, schema):
        ok, text = generate_codex_text(prompt, schema=schema)
        if not ok:
            raise RuntimeError(text)
        return ok, text

    try:
        error, summaries, excerpts = _gather_and_summarize(date, summarize, progress_callback)
        if error:
            return {"ok": False, "message": error, "summary": "", "picks": []}
        if progress_callback:
            progress_callback(0, 1, "Codex 正在彙整摘要並挑選焦點個股")
        error, summary, picks = _select_top_picks(date, summaries, call_llm)
        if error:
            return {"ok": False, "message": error, "summary": "", "picks": [], "article_excerpts": excerpts}
        result = _save_result(date, "codex-cli", summary, picks)
        result["article_excerpts"] = excerpts
        return result
    except RuntimeError as exc:
        return {"ok": False, "message": str(exc), "summary": "", "picks": []}
