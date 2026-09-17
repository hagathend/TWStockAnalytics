"""收集完之後的 AI 分析：新聞焦點、持股個股、觀察名單個股。

每一項都可以在設定（codex_settings.json）單獨開關：個股分析是「每檔一次 Codex 呼叫」，
持股加觀察名單可能有幾十檔，預設關閉，避免每天排程把帳號額度用光。
同一天已經分析過的個股會跳過，重跑排程不會重複花額度。
"""

from src import portfolio
from src.config_ai import load_codex_settings
from src.config_watchlist import load_watchlist
from src.storage import db


def stock_targets(settings: dict | None = None) -> list[dict]:
    """依設定列出要分析的個股：[{"code", "name", "source": "持股"|"觀察名單"}]，持股優先、不重複"""
    settings = settings or load_codex_settings()
    targets: dict[str, dict] = {}
    if settings.get("auto_analyze_holdings"):
        for p in portfolio.load_positions():
            targets.setdefault(p["code"], {"code": p["code"], "name": p["name"], "source": "持股"})
    if settings.get("auto_analyze_watchlist"):
        for code, name in load_watchlist().items():
            targets.setdefault(code, {"code": code, "name": name, "source": "觀察名單"})
    return list(targets.values())


def analyze_stocks(stocks: list[dict], date: str, progress=None, skip_existing: bool = True) -> dict:
    """逐檔用 Codex 做個股分析並儲存（含預測摘要追蹤）。
    回傳 {"done": [代號], "skipped": [代號], "failed": [(代號, 錯誤訊息)]}"""
    from src.codex_cli import generate_codex_text
    from src.stock_analysis import build_stock_analysis_prompt, save_stock_analysis

    result = {"done": [], "skipped": [], "failed": []}
    for index, stock in enumerate(stocks, start=1):
        code = stock["code"]
        if progress:
            progress(index - 1, len(stocks), f"分析 {code} {stock.get('name', '')}")
        if skip_existing and db.query_stock_analysis(date, code):
            result["skipped"].append(code)
            continue
        ok, text = generate_codex_text(build_stock_analysis_prompt(code))
        if ok:
            save_stock_analysis(code, text, date)
            result["done"].append(code)
        else:
            result["failed"].append((code, text))
    return result


def run_after_collect(date: str, log=print) -> bool:
    """每日排程收集完後呼叫：依設定執行新聞分析與個股分析。回傳是否全部成功"""
    from src.ai_analysis import analyze_with_codex_deep, news_top_n

    settings = load_codex_settings()
    all_ok = True
    if settings.get("auto_analyze_after_collect", True):
        log(f"新聞分析（焦點個股最多 {news_top_n()} 檔）")
        analysis = analyze_with_codex_deep(date)
        log(analysis["message"])
        all_ok = all_ok and analysis["ok"]
    else:
        log("新聞分析：設定為不執行")

    targets = stock_targets(settings)
    if not targets:
        log("個股分析：設定為不執行（或持股／觀察名單沒有股票）")
        return all_ok
    log(f"個股分析 {len(targets)} 檔：" + "、".join(f"{t['code']}{t['name']}" for t in targets))
    outcome = analyze_stocks(targets, date)
    log(f"完成 {len(outcome['done'])} 檔、今天已分析過跳過 {len(outcome['skipped'])} 檔、失敗 {len(outcome['failed'])} 檔")
    for code, message in outcome["failed"]:
        log(f"  {code} 失敗：{message[:300]}")
    return all_ok and not outcome["failed"]
