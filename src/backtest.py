"""訊號回測：統計每種訊號出現後 N 個交易日的報酬分布。

用的是 signals.compute_signals() 同一套訊號定義，避免「畫面上的訊號」與「回測的訊號」算法不一致。

幾個刻意的設計，避免回測結果過度樂觀：
- 進場價用「訊號隔天的開盤價」，不是訊號當天收盤價——收盤後才知道訊號，當天收盤價其實買不到。
- 出場價用「訊號日後第 N 個交易日的收盤價」。
- 只計「新出現」的訊號（前一天沒有、今天有）；均線多頭排列這種會連續好幾週成立的訊號，
  如果每天都算一次，同一段行情會被重複計數幾十次，勝率看起來會很漂亮但其實是同一件事。
- 同時算「同一天全市場（符合流動性門檻的股票）平均報酬」當基準，回報超額報酬；
  大多頭時什麼訊號看起來都會賺，要跟大盤比才看得出訊號本身有沒有用。

限制（UI 上也要說明）：未扣手續費與交易稅；漲停鎖死買不到、停牌等情況未處理；
樣本期間只有本地資料庫累積的歷史，期間短時結論很容易受單一行情影響。
"""

import pandas as pd

from src.signals import SIGNALS

DEFAULT_HORIZONS = (5, 20)
MIN_EVENTS_FOR_STATS = 10


def add_forward_returns(signal_df: pd.DataFrame, horizons=DEFAULT_HORIZONS) -> pd.DataFrame:
    """加上 fwd_ret_{N}（%）：隔天開盤進場、第 N 個交易日收盤出場。資料不足的列為 NaN。"""
    df = signal_df.sort_values(["code", "date"]).reset_index(drop=True)
    g = df.groupby("code", sort=False)
    entry = g["open"].shift(-1)
    for n in horizons:
        exit_price = g["close"].shift(-n)
        valid = entry.notna() & (entry > 0)
        df[f"fwd_ret_{n}"] = ((exit_price / entry.where(valid)) - 1) * 100
    return df


def _new_trigger(df: pd.DataFrame, signal: str) -> pd.Series:
    previous = df.groupby("code", sort=False)[signal].shift(1).fillna(False).astype(bool)
    return df[signal] & ~previous


def backtest_signal(df: pd.DataFrame, signal: str, horizon: int, min_avg_volume_lots: float = 500,
                    new_only: bool = True) -> dict:
    """單一訊號、單一持有天數的報酬統計。df 需已經過 add_forward_returns()。"""
    column = f"fwd_ret_{horizon}"
    liquid = df["vol_ma20"].fillna(0) >= min_avg_volume_lots * 1000
    usable = liquid & df[column].notna()

    # 基準：同一天所有流動性足夠股票的平均報酬
    baseline_by_date = df[usable].groupby("date")[column].mean()

    trigger = _new_trigger(df, signal) if new_only else df[signal]
    events = df[usable & trigger]
    returns = events[column]
    stats = {"signal": signal, "label": SIGNALS[signal], "horizon": horizon, "events": int(len(events)),
             "mean": None, "median": None, "win_rate": None, "p25": None, "p75": None,
             "baseline_mean": None, "excess_mean": None, "returns": returns.tolist()}
    if events.empty:
        return stats
    baseline = events["date"].map(baseline_by_date)
    stats.update({
        "mean": float(returns.mean()),
        "median": float(returns.median()),
        "win_rate": float((returns > 0).mean() * 100),
        "p25": float(returns.quantile(0.25)),
        "p75": float(returns.quantile(0.75)),
        "baseline_mean": float(baseline.mean()),
        "excess_mean": float((returns - baseline).mean()),
    })
    return stats


def backtest_all(df: pd.DataFrame, horizon: int, min_avg_volume_lots: float = 500,
                 new_only: bool = True) -> pd.DataFrame:
    """所有訊號的統計表（不含逐筆報酬）。樣本數不足 MIN_EVENTS_FOR_STATS 的仍列出，UI 端提示參考性低。"""
    rows = []
    for signal in SIGNALS:
        stats = backtest_signal(df, signal, horizon, min_avg_volume_lots, new_only)
        stats.pop("returns")
        rows.append(stats)
    return pd.DataFrame(rows)


def sample_period(df: pd.DataFrame, horizon: int) -> tuple[str | None, str | None]:
    """實際有前瞻報酬可算的訊號日期範圍（最後 horizon 天因為還沒有未來資料，不在回測範圍內）"""
    column = f"fwd_ret_{horizon}"
    dates = df.loc[df[column].notna(), "date"]
    if dates.empty:
        return None, None
    return dates.min(), dates.max()
