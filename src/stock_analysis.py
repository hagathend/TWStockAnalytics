"""個股籌碼分析 + 未來展望：複製貼上流程。

跟新聞分析（src/ai_analysis.py）用一樣的做法：產生一份包含籌碼與新聞的提示詞，
使用者自己複製貼到平常用的 AI 網頁版（Claude/ChatGPT/Gemini），再把結果貼回來存起來。
不需要另外接 API，個股分析這種需要判斷力的任務用網頁版大模型效果通常比本機小模型好。
"""

from datetime import date as _date, timedelta

from bs4 import BeautifulSoup

from src.chip_metrics import metrics_for_code
from src.chip_metrics import summarize_for_prompt as summarize_chip_metrics
from src.collectors import finmind
from src.fundamentals import summarize_for_prompt as summarize_fundamentals
from src.indicators import (
    RECOMMENDED_HISTORY_DAYS,
    add_indicators,
    summarize_for_prompt,
    to_dataframe,
)
from src.storage import db

_PRICE_ROWS_SHOWN = 15
_NEWS_LIMIT = 8

_STOCK_ANALYSIS_PROMPT = """你是台股個股分析助手。以下是 {code} {name} 的近期資料（資料日期：{date}）。

【技術指標】（由程式依收盤價量計算，非估算值）
{indicator_block}

【籌碼延伸指標】（由程式依本地累積的法人／融資歷史計算，非估算值）
{chip_block}

【基本面】（本益比／殖利率／淨值比與月營收，官方公開資料；營收年增率已由來源計算）
{fundamental_block}

【近期股價】（最近 {price_rows} 個交易日，資料來源 FinMind）
{price_block}

【近期三大法人買賣超】（股數，本地資料庫累積收集，愈近期資料愈完整）
{institutional_block}

【近期融資融券】（本地資料庫累積收集）
{margin_block}

【相關新聞】
{news_block}

請根據以上資料，用簡潔的條列式回答，「每一項都必須嚴格限制在800字以內」，
不要長篇大論、不要有開場白，直接條列以下四項結果：

技術面分析：（依據上面已算好的均線、RSI、KD、MACD、布林通道與量能判讀目前技術面，
　　　　　　　請直接引用這些數值，不要自己重新估算，800字以內）
籌碼面分析：（依據上面已算好的法人連買連賣天數、累計買賣超、佔成交量比重與融資變化，
　　　　　　　判斷目前籌碼偏多方還是空方掌控，請直接引用這些數值，800字以內）
未來1~2週展望：（綜合技術、籌碼與基本面（營收成長、本益比）判斷，800字以內）
總結：（800字以內）

請直接用繁體中文條列輸出這四項，不需要輸出 JSON 格式，也不要輸出這四項以外的內容。
"""


def _fetch_price_rows(code: str) -> list[dict]:
    """抓一次就好，價格表與技術指標共用同一份資料（技術指標需要較長歷史才算得出 MA60）"""
    end_date = _date.today().isoformat()
    start_date = (_date.today() - timedelta(days=RECOMMENDED_HISTORY_DAYS)).isoformat()
    try:
        return finmind.fetch_stock_price(code, start_date, end_date)
    except Exception:  # noqa: BLE001 - 抓不到歷史股價不應該擋住整份提示詞產生
        return []


def _format_price_history(rows: list[dict]) -> str:
    if not rows:
        return "（無法取得股價歷史）"
    lines = []
    for r in rows[-_PRICE_ROWS_SHOWN:]:
        lines.append(
            f"{r['date']} 開{r['open']} 高{r['max']} 低{r['min']} 收{r['close']} 量{r['Trading_Volume']}"
        )
    return "\n".join(lines)


def _format_indicators(rows: list[dict]) -> str:
    if not rows:
        return "（無法取得股價歷史，無法計算技術指標）"
    return summarize_for_prompt(add_indicators(to_dataframe(rows)))


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


def _strip_html(text: str) -> str:
    """Google News RSS 的 summary 欄位是 HTML（含 <a href=...> 連結標籤），
    直接塞進提示詞會變成一堆雜訊，要先去掉標籤只留純文字。
    （已經做過 AI 逐篇摘要的新聞會優先用 excerpt 欄位，走不到這裡）"""
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


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
        text = row.get("excerpt") or _strip_html(row.get("summary") or "")
        lines.append(f"- {row['title']}：{text[:100]}")
    return "\n".join(lines)


def build_stock_analysis_prompt(code: str) -> str:
    """回傳這檔股票的分析提示詞（含技術指標、籌碼歷史、股價、相關新聞）"""
    name = db.lookup_stock_name(code) or code
    price_rows = _fetch_price_rows(code)
    return _STOCK_ANALYSIS_PROMPT.format(
        code=code,
        name=name,
        date=_date.today().isoformat(),
        price_rows=_PRICE_ROWS_SHOWN,
        indicator_block=_format_indicators(price_rows),
        chip_block=summarize_chip_metrics(metrics_for_code(code)),
        fundamental_block=summarize_fundamentals(code),
        price_block=_format_price_history(price_rows),
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
