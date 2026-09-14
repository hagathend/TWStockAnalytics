"""籌碼延伸指標：從本地累積的三大法人／融資融券歷史計算。

原本個股提示詞只丟「最近幾天的法人買賣超原始數字」給 AI 自己看，跟技術面當初的問題一樣：
能用程式算出確定數值的東西，就先算好再給 AI 判讀（見 indicators.py 的設計說明）。

單位：法人買賣超、成交量為「股」；融資融券餘額為「張」（TWSE MI_MARGN 交易單位）。

資料不足時一律回傳 None，不用部分資料硬算——例如只有 3 天歷史就不回報「5日累計」，
避免把 3 天的加總當成 5 天誤導判斷。
"""

from datetime import date as _date, timedelta

import pandas as pd

from src.storage import db

NET_COLUMNS = ["foreign_net", "trust_net", "dealer_net", "total_net"]
_NUMERIC_COLUMNS = ["open", "high", "low", "close", "change", "volume", "turnover",
                    *NET_COLUMNS, "margin_balance", "short_balance"]


def prepare_history(rows: list[dict]) -> pd.DataFrame:
    """把 db.query_market_history() 的結果轉成 DataFrame，並處理法人欄位的缺值。

    某天整個市場有收集法人資料、但這檔股票不在 T86 名單裡 → 代表當天沒有法人交易，補 0。
    某天整個市場根本沒收集法人資料 → 保持 NaN（未知），不能當成 0，否則會算出錯誤的連買天數。
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
    # SQLite 的 NULL 進 pandas 可能變成 None（object 型別）而不是 NaN，
    # 統一轉成 float，後續的缺值判斷與數值運算才會一致
    for column in _NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    collected = df["inst_collected"] == 1
    for column in NET_COLUMNS:
        df.loc[collected & df[column].isna(), column] = 0
    return df


def signed_streak(values) -> int:
    """從最後一筆往前數連續同號的天數：正數＝連續買超天數、負數＝連續賣超天數。
    最後一筆為 0 或缺值時回傳 0；往前數遇到缺值（未收集）就停止，不跨越未知的日子。"""
    series = list(values)
    if not series or pd.isna(series[-1]) or series[-1] == 0:
        return 0
    sign = 1 if series[-1] > 0 else -1
    count = 0
    for value in reversed(series):
        if pd.isna(value) or value == 0 or (value > 0) != (sign > 0):
            break
        count += 1
    return sign * count


def _tail_sum(series: pd.Series, n: int):
    tail = series.tail(n)
    if len(tail) < n or tail.isna().any():
        return None
    return float(tail.sum())


def _pct(numerator, denominator):
    if numerator is None or denominator in (None, 0) or pd.isna(numerator) or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator) * 100


def compute_chip_metrics(stock_df: pd.DataFrame) -> dict:
    """計算單一股票最新一個交易日的籌碼延伸指標。stock_df 需依日期由舊到新排序。"""
    if stock_df.empty:
        return {}
    df = stock_df.sort_values("date").reset_index(drop=True)
    last = df.iloc[-1]

    volume_5d = _tail_sum(df["volume"], 5)
    total_5d = _tail_sum(df["total_net"], 5)
    trust_5d = _tail_sum(df["trust_net"], 5)

    metrics = {
        "code": last["code"],
        "name": last.get("name"),
        "date": last["date"],
        "days": len(df),
        "foreign_streak": signed_streak(df["foreign_net"]),
        "trust_streak": signed_streak(df["trust_net"]),
        "dealer_streak": signed_streak(df["dealer_net"]),
        "foreign_net_5d": _tail_sum(df["foreign_net"], 5),
        "foreign_net_20d": _tail_sum(df["foreign_net"], 20),
        "trust_net_5d": trust_5d,
        "trust_net_20d": _tail_sum(df["trust_net"], 20),
        "dealer_net_5d": _tail_sum(df["dealer_net"], 5),
        "total_net_5d": total_5d,
        "total_net_20d": _tail_sum(df["total_net"], 20),
        "inst_volume_ratio_1d": _pct(last["total_net"], last["volume"]),
        "inst_volume_ratio_5d": _pct(total_5d, volume_5d),
        "trust_volume_ratio_5d": _pct(trust_5d, volume_5d),
        "margin_balance": None if pd.isna(last.get("margin_balance")) else float(last["margin_balance"]),
        "short_margin_ratio": None,
        "margin_change_5d": None,
        "margin_change_5d_pct": None,
        "price_change_5d_pct": None,
        "margin_price_signal": None,
    }

    if metrics["margin_balance"] and not pd.isna(last.get("short_balance")):
        metrics["short_margin_ratio"] = _pct(last["short_balance"], metrics["margin_balance"])

    if len(df) >= 6:
        base = df.iloc[-6]
        if not pd.isna(last.get("margin_balance")) and not pd.isna(base.get("margin_balance")):
            change = float(last["margin_balance"]) - float(base["margin_balance"])
            metrics["margin_change_5d"] = change
            metrics["margin_change_5d_pct"] = _pct(change, base["margin_balance"])
        if not pd.isna(last["close"]) and not pd.isna(base["close"]) and base["close"]:
            metrics["price_change_5d_pct"] = (float(last["close"]) / float(base["close"]) - 1) * 100

    margin_change = metrics["margin_change_5d"]
    price_change = metrics["price_change_5d_pct"]
    if margin_change is not None and price_change is not None:
        if margin_change > 0 and price_change < 0:
            metrics["margin_price_signal"] = "融資增、股價跌（散戶可能在接刀）"
        elif margin_change < 0 and price_change > 0:
            metrics["margin_price_signal"] = "融資減、股價漲（籌碼沉澱）"

    return metrics


def metrics_for_code(code: str, lookback_days: int = 120) -> dict:
    """單一股票的籌碼延伸指標（個股詳情頁、個股分析提示詞用）。
    自動判斷上市或上櫃：上櫃股只有「有收集的那幾天」，天數會比較少，指標可能多半是資料不足。"""
    since = (_date.today() - timedelta(days=lookback_days)).isoformat()
    for market in ("TWSE", "TPEx"):
        rows = db.query_market_history(market=market, since=since, codes=[code])
        if rows:
            return compute_chip_metrics(prepare_history(rows))
    return {}


def compute_all_chip_metrics(history: pd.DataFrame) -> pd.DataFrame:
    """對整個市場每檔股票計算籌碼延伸指標（選股篩選器用）"""
    if history.empty:
        return pd.DataFrame()
    records = [compute_chip_metrics(group) for _, group in history.groupby("code", sort=False)]
    return pd.DataFrame([r for r in records if r])


def _fmt_shares(value) -> str:
    if value is None:
        return "資料不足"
    return f"{value / 1000:+,.0f} 張"


def _fmt_pct(value, digits: int = 1) -> str:
    return "資料不足" if value is None else f"{value:+.{digits}f}%"


def _fmt_streak(value: int) -> str:
    if value > 0:
        return f"連買 {value} 天"
    if value < 0:
        return f"連賣 {-value} 天"
    return "無連續"


def summarize_for_prompt(metrics: dict) -> str:
    """整理成給 AI 判讀的文字，只陳述算出來的數值，不下多空結論"""
    if not metrics:
        return "（無籌碼歷史資料）"
    lines = [
        f"資料天數: {metrics['days']} 個交易日（截至 {metrics['date']}）",
        f"外資: {_fmt_streak(metrics['foreign_streak'])}，5日 {_fmt_shares(metrics['foreign_net_5d'])}、"
        f"20日 {_fmt_shares(metrics['foreign_net_20d'])}",
        f"投信: {_fmt_streak(metrics['trust_streak'])}，5日 {_fmt_shares(metrics['trust_net_5d'])}、"
        f"20日 {_fmt_shares(metrics['trust_net_20d'])}",
        f"自營商: {_fmt_streak(metrics['dealer_streak'])}，5日 {_fmt_shares(metrics['dealer_net_5d'])}",
        f"三大法人合計: 5日 {_fmt_shares(metrics['total_net_5d'])}、20日 {_fmt_shares(metrics['total_net_20d'])}",
        f"法人買賣超佔成交量: 當日 {_fmt_pct(metrics['inst_volume_ratio_1d'])}、"
        f"5日 {_fmt_pct(metrics['inst_volume_ratio_5d'])}（投信5日 {_fmt_pct(metrics['trust_volume_ratio_5d'])}）",
    ]
    if metrics["margin_balance"] is not None:
        change = metrics["margin_change_5d"]
        change_text = "資料不足" if change is None else f"{change:+,.0f} 張"
        ratio = metrics["short_margin_ratio"]
        ratio_text = "資料不足" if ratio is None else f"{ratio:.1f}%"
        lines.append(
            f"融資餘額: {metrics['margin_balance']:,.0f} 張，5日變化 {change_text}"
            f"（{_fmt_pct(metrics['margin_change_5d_pct'])}）；券資比 {ratio_text}"
        )
    else:
        lines.append("融資融券: 無資料（可能不可信用交易）")
    lines.append(f"近5日股價變化: {_fmt_pct(metrics['price_change_5d_pct'])}")
    if metrics["margin_price_signal"]:
        lines.append(f"融資與股價: {metrics['margin_price_signal']}")
    return "\n".join(lines)
