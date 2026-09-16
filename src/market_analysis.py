"""大盤整體籌碼分析：複製貼上流程。

跟個股分析（src/stock_analysis.py）、新聞分析（src/ai_analysis.py）同樣的做法：
產生一份包含大盤籌碼與當日新聞重點的提示詞，使用者自己複製貼到平常用的 AI 網頁版，
再把結果貼回來存起來，收錄進「每日報告」。
"""

from datetime import date as _date

from src.storage import db

_MARKET_ANALYSIS_PROMPT = """你是台股大盤分析助手。以下是 {date} 的大盤與市場資訊。

【大盤三大法人買賣超合計】（上市櫃個股加總，已排除權證與 ETF，股數）
外資: {foreign_total}
投信: {trust_total}
自營商: {dealer_total}
合計: {total_net}

【當日漲跌家數】（上市，不含權證）
上漲 {up_count} 檔／下跌 {down_count} 檔／平盤 {flat_count} 檔

【今日新聞摘要】
{news_summary}

【今日新聞焦點個股 Top 20】
{picks_block}

請根據以上資料，用簡潔的條列式回答，總字數控制在 1000 字以內，「每一項都要精簡」，
不要長篇大論、不要有開場白，直接條列以下四項結果：

短期展望（1-2週）：
中期展望（1-3個月）：
籌碼分析：（大盤三大法人買賣超趨勢代表什麼意義？目前籌碼是偏多方掌控還是空方？）
目前熱門產業和股票消息：（綜合新聞與焦點個股，總結目前市場關注的產業與個股）

請直接用繁體中文條列輸出這四項，不需要輸出 JSON 格式，也不要輸出這四項以外的內容。
"""


def _fmt(value) -> str:
    return f"{value:+,}" if isinstance(value, (int, float)) else "無資料"


def _format_picks_block(picks: list[dict]) -> str:
    if not picks:
        return "（無資料）"
    return "\n".join(f"- {p['code']} {p['name']}：{p['reason']}" for p in picks)


def build_market_analysis_prompt(date: str | None = None) -> tuple[bool, str]:
    """回傳 (是否成功, 提示詞文字或錯誤訊息)"""
    date = date or _date.today().isoformat()

    inst_summary = db.query_market_institutional_summary(date)
    breadth = db.query_market_breadth(date)
    ai_summary = db.query_ai_analysis_summary(date)
    picks = db.query_ai_picks(date)

    has_data = inst_summary.get("total_net") is not None or breadth.get("up") or ai_summary
    if not has_data:
        return False, "此日期尚無足夠資料，請先收集資料並完成新聞分析"

    prompt = _MARKET_ANALYSIS_PROMPT.format(
        date=date,
        foreign_total=_fmt(inst_summary.get("foreign_total")),
        trust_total=_fmt(inst_summary.get("trust_total")),
        dealer_total=_fmt(inst_summary.get("dealer_total")),
        total_net=_fmt(inst_summary.get("total_net")),
        up_count=breadth.get("up") or 0,
        down_count=breadth.get("down") or 0,
        flat_count=breadth.get("flat") or 0,
        news_summary=(ai_summary["summary"] if ai_summary else "（尚無新聞分析摘要）"),
        picks_block=_format_picks_block(picks),
    )
    return True, prompt


def save_market_analysis(analysis_text: str, date: str | None = None) -> dict:
    """儲存使用者貼回來的大盤分析結果。回傳 {"ok": bool, "message": str}"""
    if not analysis_text.strip():
        return {"ok": False, "message": "尚未貼上任何內容"}
    date = date or _date.today().isoformat()
    db.save_market_analysis(date, analysis_text.strip())
    return {"ok": True, "message": "大盤分析已儲存"}
