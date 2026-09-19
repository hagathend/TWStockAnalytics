"""個股比較：多檔股票同期間的相對走勢（起點＝100）與估值、獲利、籌碼指標並排。

- 走勢以「每一檔都有資料的第一天」為共同起點，之後停牌的日子沿用前一天收盤
- 報酬率為期間內收盤價變化，未含股利
- 指標表只從本地資料庫取最新值（各指標的資料日可能不同），沒有資料的欄位留空
"""

import pandas as pd

PERIODS = {"3 個月": 90, "6 個月": 180, "1 年": 365, "3 年": 1095}
MAX_STOCKS = 6

METRIC_LABELS = {
    "name": "名稱", "industry": "產業", "close": "收盤", "period_return": "期間報酬%", "max_drawdown": "期間最大回檔%",
    "pe_ratio": "本益比", "pb_ratio": "淨值比", "dividend_yield": "殖利率%", "yoy_pct": "營收年增%",
    "eps_ttm": "近四季EPS", "roe_annualized": "ROE年化%", "gross_margin": "毛利率%", "debt_ratio": "負債比%",
    "foreign_pct": "外資持股%", "big1000_pct": "千張大戶%", "day_trade_pct": "當沖比%",
}


def normalize(closes: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """{代號: DataFrame(date, close)} → 以日期為索引、每檔一欄、共同起點＝100 的走勢"""
    series = {code: frame.drop_duplicates("date").set_index("date")["close"].astype(float)
              for code, frame in closes.items() if not frame.empty}
    if not series:
        return pd.DataFrame()
    wide = pd.DataFrame(series).sort_index()
    start = max(s.index.min() for s in series.values())
    wide = wide[wide.index >= start].ffill()
    return wide / wide.iloc[0] * 100


def _max_drawdown(values: pd.Series) -> float | None:
    values = values.dropna()
    if values.empty:
        return None
    return float((values / values.cummax() - 1).min() * 100)


def metrics_table(codes: list[str], names: dict[str, str], trend: pd.DataFrame, latest: dict[str, float],
                  tables: list[pd.DataFrame]) -> pd.DataFrame:
    """每檔一列。tables：各種以 code 為鍵的最新指標表（基本面、季報、外資、大戶、當沖、產業）"""
    frame = pd.DataFrame({"code": codes})
    frame["name"] = frame["code"].map(names)
    frame["close"] = frame["code"].map(latest)
    frame["period_return"] = [float(trend[c].iloc[-1] - 100) if c in trend and len(trend) else None for c in codes]
    frame["max_drawdown"] = [_max_drawdown(trend[c]) if c in trend else None for c in codes]
    for table in tables:
        if table is None or table.empty:
            continue
        extra = [c for c in table.columns if c != "code" and c in METRIC_LABELS and c not in frame.columns]
        if extra:
            frame = frame.merge(table[["code", *extra]].drop_duplicates("code"), on="code", how="left")
    for column in METRIC_LABELS:
        if column not in frame.columns:
            frame[column] = None
    return frame[["code", *METRIC_LABELS]]
