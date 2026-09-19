"""季度財報指標：單季與累計 EPS、毛利率、營益率、ROE（年化）、近四季 EPS。

官方損益表是「年初累計到該季」：第 2 季的營收是上半年合計。
- 單季值＝本季累計 − 上一季累計（第 1 季直接用）；上一季缺資料時單季值為 None，不硬算
- 毛利率／營益率用單季數字計算（反映最新一季的獲利能力）
- ROE（年化）＝累計歸屬母公司淨利 ÷ 期末歸屬母公司權益 × (4 ÷ 季別)
- 近四季 EPS＝最近四個單季 EPS 相加（四季都要有）
- 資產負債比率用期末數：負債比＝負債 ÷ 資產、流動比＝流動資產 ÷ 流動負債（金融業沒有流動分類，為 None）
- ROA（年化）＝累計淨利 ÷ 期末資產 × (4 ÷ 季別)
- 杜邦分析（年化）：ROE ≈ 淨利率 × 總資產週轉率 × 權益乘數（淨利用歸屬母公司，營收為合併數，所以乘積與 ROE 會有些微差距）
- 現金流量：單季營業／投資／籌資現金流；自由現金流＝營業＋投資現金流（台股網站常見算法，投資含資本支出以外的項目）；
  盈餘品質＝累計營業現金流 ÷ 累計淨利（長期小於 1 代表帳上賺的錢沒有真的收到現金）
"""

import time
from datetime import date as _date

import pandas as pd

from src.collectors import mops_financials
from src.storage import db

DEFAULT_BACKFILL_QUARTERS = 8
_POLITE_SECONDS = 3.0
_MIN_ROWS_COMPLETE = {"TWSE": 900, "TPEx": 700}


def latest_published_quarter(today: _date | None = None) -> tuple[int, int]:
    """依法定公布期限推估「應該已經公布」的最新一季（Q1 5/15、Q2 8/14、Q3 11/14、年報 3/31）"""
    today = today or _date.today()
    y, m, d = today.year, today.month, today.day
    if (m, d) >= (11, 15):
        return y, 3
    if (m, d) >= (8, 15):
        return y, 2
    if (m, d) >= (5, 16):
        return y, 1
    if (m, d) >= (4, 1):
        return y - 1, 4
    return y - 1, 3


def _previous_quarters(year: int, quarter: int, n: int) -> list[tuple[int, int]]:
    result = []
    for _ in range(n):
        result.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return result


def backfill(quarters: int = DEFAULT_BACKFILL_QUARTERS, progress=None, sleep_seconds: float = _POLITE_SECONDS,
             today: _date | None = None, refresh_latest: bool = False) -> dict:
    """回補近 N 季；已完整的季跳過（refresh_latest=True 時最新一季一定重抓，給每日收集補晚公布的公司）"""
    counts = db.query_financials_counts()
    stats = {"filled": 0, "skipped": 0, "failed": []}
    targets = _previous_quarters(*latest_published_quarter(today), quarters)
    for index, (year, quarter) in enumerate(targets):
        for market in ("TWSE", "TPEx"):
            complete = counts.get((year, quarter, market), 0) >= _MIN_ROWS_COMPLETE[market]
            if complete and not (refresh_latest and index == 0):
                stats["skipped"] += 1
                continue
            try:
                rows = mops_financials.fetch_quarter(year, quarter, market)
                db.save_financials(rows)
                stats["filled"] += 1
                if progress:
                    progress(f"{year}Q{quarter} {market} 財報 {len(rows)} 家")
            except Exception as exc:  # noqa: BLE001 - 單季失敗下次重跑會再補
                stats["failed"].append(f"{year}Q{quarter} {market}: {exc}")
            if sleep_seconds:
                time.sleep(sleep_seconds)
    return stats


_FRAME_COLUMNS = ["code", "year", "quarter", "label", "eps_cum", "eps_q", "revenue_q", "gross_margin",
                  "operating_margin", "roe_annualized", "eps_ttm", "net_income_q", "debt_ratio", "current_ratio",
                  "roa_annualized", "net_margin", "asset_turnover", "equity_multiplier", "operating_cf_q",
                  "investing_cf_q", "financing_cf_q", "free_cf_q", "ocf_to_net_income"]
_NUMERIC_COLUMNS = ("revenue", "gross_profit", "operating_income", "net_income", "eps", "equity", "total_assets",
                    "total_liabilities", "current_assets", "current_liabilities", "operating_cf", "investing_cf",
                    "financing_cf")


def _compute(rows: list[dict]) -> pd.DataFrame:
    """全部股票一起向量化計算（每檔依季別排序）"""
    if not rows:
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    df = pd.DataFrame(rows).sort_values(["code", "year", "quarter"]).reset_index(drop=True)
    for column in _NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce") if column in df else float("nan")
    grouped = df.groupby("code", sort=False)
    period = df["year"] * 4 + df["quarter"]
    prev_is_last_quarter = (grouped["year"].shift(1) == df["year"]) & (grouped["quarter"].shift(1) == df["quarter"] - 1)

    def single(column):
        previous = grouped[column].shift(1)
        diff = (df[column] - previous).where(prev_is_last_quarter)
        return df[column].where(df["quarter"] == 1, diff)

    out = pd.DataFrame({"code": df["code"], "year": df["year"], "quarter": df["quarter"],
                        "label": df["year"].astype(str) + "Q" + df["quarter"].astype(str),
                        "eps_cum": df["eps"], "eps_q": single("eps"), "revenue_q": single("revenue")})
    gross_q, operating_q = single("gross_profit"), single("operating_income")
    revenue_ok = out["revenue_q"].where(out["revenue_q"] != 0)
    out["gross_margin"] = gross_q / revenue_ok * 100
    out["operating_margin"] = operating_q / revenue_ok * 100
    out["roe_annualized"] = df["net_income"] / df["equity"].where(df["equity"] != 0) * (4 / df["quarter"]) * 100
    # 近四季 EPS：四個單季都要有，而且季度連續
    rolling = out.groupby("code", sort=False)["eps_q"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    consecutive = (period - df.groupby("code", sort=False)["year"].shift(3) * 4
                   - df.groupby("code", sort=False)["quarter"].shift(3)) == 3
    out["eps_ttm"] = rolling.where(consecutive)

    def ratio(numerator, denominator):
        return numerator / denominator.where(denominator != 0)

    annualize = 4 / df["quarter"]
    out["net_income_q"] = single("net_income")
    out["debt_ratio"] = ratio(df["total_liabilities"], df["total_assets"]) * 100
    out["current_ratio"] = ratio(df["current_assets"], df["current_liabilities"]) * 100
    out["roa_annualized"] = ratio(df["net_income"], df["total_assets"]) * annualize * 100
    out["net_margin"] = ratio(df["net_income"], df["revenue"]) * 100
    out["asset_turnover"] = ratio(df["revenue"], df["total_assets"]) * annualize
    out["equity_multiplier"] = ratio(df["total_assets"], df["equity"])
    out["operating_cf_q"], out["investing_cf_q"] = single("operating_cf"), single("investing_cf")
    out["financing_cf_q"] = single("financing_cf")
    out["free_cf_q"] = out["operating_cf_q"] + out["investing_cf_q"]
    # 淨利是負的時候比值沒有意義（負除負會變成好看的正數）
    out["ocf_to_net_income"] = ratio(df["operating_cf"], df["net_income"].where(df["net_income"] > 0))
    return out[_FRAME_COLUMNS]


def quarterly_frame(rows: list[dict]) -> pd.DataFrame:
    """同一檔股票的季報列（任意順序）→ 加上單季值與比率，由舊到新"""
    return _compute(rows).drop(columns="code").reset_index(drop=True)


def code_frame(code: str) -> pd.DataFrame:
    return quarterly_frame(db.query_financials(code))


def latest_table() -> pd.DataFrame:
    """每檔最新一季的 ROE（年化）、單季毛利率、近四季 EPS、負債比（選股器、個股比較用）"""
    columns = ["code", "roe_annualized", "gross_margin", "eps_ttm", "debt_ratio"]
    frame = _compute(db.query_financials())
    if frame.empty:
        return pd.DataFrame(columns=columns)
    return frame.groupby("code", sort=False).tail(1)[columns].reset_index(drop=True)


def summarize_for_prompt(code: str) -> str | None:
    frame = code_frame(code)
    if frame.empty:
        return None

    def num(v, spec, suffix=""):
        return "無資料" if v is None or pd.isna(v) else f"{v:{spec}}{suffix}"

    lines = []
    for row in frame.tail(4).itertuples():
        lines.append(f"{row.label}：單季 EPS {num(row.eps_q, '.2f')} 元、毛利率 {num(row.gross_margin, '.1f', '%')}、"
                     f"營益率 {num(row.operating_margin, '.1f', '%')}、ROE（年化）{num(row.roe_annualized, '.1f', '%')}")
    last = frame.iloc[-1]
    lines.append(f"近四季 EPS {num(last['eps_ttm'], '.2f', ' 元')}")
    lines.append(f"{last['label']} 負債比 {num(last['debt_ratio'], '.1f', '%')}、流動比 {num(last['current_ratio'], '.0f', '%')}、"
                 f"ROA（年化）{num(last['roa_annualized'], '.1f', '%')}、"
                 f"累計營業現金流 ÷ 淨利 {num(last['ocf_to_net_income'], '.2f', ' 倍')}")
    return "\n".join(lines)
