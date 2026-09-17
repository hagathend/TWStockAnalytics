"""股權分散（集保）指標：千張大戶、400 張以上大戶、50 張以下散戶的持股比例與週變化。

台股常用的籌碼判讀：大戶持股比例上升、散戶比例與股東人數下降，代表籌碼往少數人集中（俗稱籌碼集中）。
比例的週變化單位是「百分點」（例如 84.5% → 85.0% 是 +0.5 個百分點）。
資料每週一筆；只有一週資料時沒有週變化（回傳 None，不硬算）。
"""

import pandas as pd

from src.storage import db

METRICS = ("big1000_pct", "big400_pct", "retail_pct")


def _with_changes(history: list[dict]) -> dict | None:
    if not history:
        return None
    latest = dict(history[-1])
    previous = history[-2] if len(history) >= 2 else None
    for key in METRICS:
        latest[f"{key}_change"] = (latest[key] - previous[key]
                                   if previous and latest[key] is not None and previous[key] is not None else None)
    holders, prev_holders = latest.get("total_holders"), previous.get("total_holders") if previous else None
    latest["holders_change_pct"] = (holders / prev_holders - 1) * 100 if holders and prev_holders else None
    latest["previous_date"] = previous["date"] if previous else None
    latest["weeks"] = len(history)
    return latest


def code_summary(code: str) -> dict | None:
    return _with_changes(db.query_shareholding_history(code))


def latest_table() -> pd.DataFrame:
    """每檔最新一週的指標與週變化（選股器用）"""
    columns = ["code", "big1000_pct", "big1000_pct_change", "big400_pct", "retail_pct", "total_holders",
               "holders_change_pct"]
    dates = db.query_shareholding_dates()
    if not dates:
        return pd.DataFrame(columns=columns)
    latest = pd.DataFrame(db.query_shareholding_on(dates[-1]))
    if len(dates) >= 2:
        previous = pd.DataFrame(db.query_shareholding_on(dates[-2]))[["code", "big1000_pct", "total_holders"]]
        latest = latest.merge(previous, on="code", how="left", suffixes=("", "_prev"))
        latest["big1000_pct_change"] = latest["big1000_pct"] - latest["big1000_pct_prev"]
        latest["holders_change_pct"] = (latest["total_holders"] / latest["total_holders_prev"] - 1) * 100
    else:
        latest["big1000_pct_change"] = None
        latest["holders_change_pct"] = None
    return latest[columns]


def summarize_for_prompt(code: str) -> str:
    summary = code_summary(code)
    if not summary:
        return "（無集保股權分散資料）"

    def change(key, unit="個百分點"):
        value = summary.get(key)
        return "" if value is None else f"（較上週 {value:+.2f} {unit}）"

    lines = [
        f"資料週：{summary['date']}（已累積 {summary['weeks']} 週）",
        f"千張以上大戶持股 {summary['big1000_pct']:.2f}%{change('big1000_pct_change')}",
        f"400 張以上大戶持股 {summary['big400_pct']:.2f}%{change('big400_pct_change')}",
        f"50 張以下散戶持股 {summary['retail_pct']:.2f}%{change('retail_pct_change')}",
    ]
    if summary.get("total_holders"):
        holders_change = summary.get("holders_change_pct")
        lines.append(f"總股東人數 {summary['total_holders']:,} 人"
                     + ("" if holders_change is None else f"（較上週 {holders_change:+.2f}%）"))
    return "\n".join(lines)
