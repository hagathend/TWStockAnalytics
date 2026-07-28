"""個股籌碼分析 + 未來展望：複製貼上流程。

跟新聞分析（src/ai_analysis.py）用一樣的做法：產生一份包含籌碼與新聞的提示詞，
使用者自己複製貼到平常用的 AI 網頁版（Claude/ChatGPT/Gemini），再把結果貼回來存起來。
不需要另外接 API，個股分析這種需要判斷力的任務用網頁版大模型效果通常比本機小模型好。
"""

from datetime import date as _date, timedelta

from src.collectors import finmind
from src.storage import db

_PRICE_HISTORY_DAYS = 30
_PRICE_ROWS_SHOWN = 15
_NEWS_LIMIT = 8

_STOCK_ANALYSIS_PROMPT = """你是台股個股分析助手。以下是 {code} {name} 的近期資料（資料日期：{date}）。

【近期股價】（最近 {price_rows} 個交易日，資料來源 FinMind）
{price_block}

【近期三大法人買賣超】（股數，本地資料庫累積收集，愈近期資料愈完整）
{institutional_block}

【近期融資融券】（本地資料庫累積收集）
{margin_block}

【相關新聞】
{news_block}

請根據以上資料，用簡潔的條列式回答，「每一項都必須嚴格限制在800字以內」，
不要長篇大論、不要有開場白，直接條列以下三項結果：

籌碼面分析：（目前籌碼是偏多方掌控還是空方？依據是什麼，800字以內）
未來1~2週展望：（800字以內）
總結：（800字以內）

請直接用繁體中文條列輸出這三項，不需要輸出 JSON 格式，也不要輸出這三項以外的內容。
"""


def _format_price_history(code: str) -> str:
    end_date = _date.today().isoformat()
    start_date = (_date.today() - timedelta(days=_PRICE_HISTORY_DAYS)).isoformat()
    try:
        rows = finmind.fetch_stock_price(code, start_date, end_date)
    except Exception:  # noqa: BLE001 - 抓不到歷史股價不應該擋住整份提示詞產生
        rows = []
    if not rows:
        return "（無法取得股價歷史）"
    lines = []
    for r in rows[-_PRICE_ROWS_SHOWN:]:
        lines.append(
            f"{r['date']} 開{r['open']} 高{r['max']} 低{r['min']} 收{r['close']} 量{r['Trading_Volume']}"
        )
    return "\n".join(lines)


def _format_institutional_history(code: str) -> str:
    rows = db.query_code_history("institutional", code, limit=10)
    if not rows:
        return "（無資料）"
    lines = []
    for r in rows:
        lines.append(
            f"{r['date']} 外資{r['foreign_net']:+} 投信{r['trust_net']:+} "
            f"自營商{r['dealer_net']:+} 合計{r['total_net']:+}"
        )
    return "\n".join(lines)


def _format_margin_history(code: str) -> str:
    rows = db.query_code_history("margin", code, limit=10)
    if not rows:
        return "（無資料）"
    lines = []
    for r in rows:
        lines.append(f"{r['date']} 融資餘額{r['margin_balance']} 融券餘額{r['short_balance']}")
    return "\n".join(lines)


def _format_related_news(code: str, name: str) -> str:
    by_code = db.query_news_by_keyword(code, days=7, limit=_NEWS_LIMIT)
    by_name = db.query_news_by_keyword(name, days=7, limit=_NEWS_LIMIT)
    seen_urls = set()
    merged = []
    for row in by_code + by_name:
        url = row.get("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(row)
        if len(merged) >= _NEWS_LIMIT:
            break
    if not merged:
        return "（近期無相關新聞）"
    lines = []
    for row in merged:
        text = row.get("excerpt") or row.get("summary") or ""
        lines.append(f"- {row['title']}：{text[:100]}")
    return "\n".join(lines)


def build_stock_analysis_prompt(code: str) -> str:
    """回傳這檔股票的分析提示詞（含籌碼歷史、股價、相關新聞）"""
    name = db.lookup_stock_name(code) or code
    return _STOCK_ANALYSIS_PROMPT.format(
        code=code,
        name=name,
        date=_date.today().isoformat(),
        price_rows=_PRICE_ROWS_SHOWN,
        price_block=_format_price_history(code),
        institutional_block=_format_institutional_history(code),
        margin_block=_format_margin_history(code),
        news_block=_format_related_news(code, name),
    )


def save_stock_analysis(code: str, analysis_text: str, date: str | None = None) -> dict:
    """儲存使用者貼回來的個股分析結果。回傳 {"ok": bool, "message": str}"""
    if not analysis_text.strip():
        return {"ok": False, "message": "尚未貼上任何內容"}
    date = date or _date.today().isoformat()
    name = db.lookup_stock_name(code) or code
    db.save_stock_analysis(date, code, name, analysis_text.strip())
    return {"ok": True, "message": "個股分析已儲存"}
