"""個股歷年股利：每年配多少、盈餘分配率、殖利率、填息天數。資料向 FinMind 現抓（股利一年只變幾次，頁面快取一天）。

- 所屬年度：股利政策的「year」欄是民國年（例如「114年第2季」「113年」），同一年度的季配息加總成年度股利
- 盈餘分配率＝年度現金股利 ÷ 該年度 EPS（本地季報第 4 季累計 EPS，季報只回補近兩年，更早的年度沒有）
- 殖利率（每次）＝股利 ÷ 除權息前一天收盤價；年度殖利率＝同一年除息的各次加總
- 填息天數：除權息日起，收盤價回到除權息前收盤價所需的交易日數；還沒回到就是「尚未填息」
"""

import re
from datetime import date as _date, timedelta

import pandas as pd

from src.collectors import finmind

DEFAULT_YEARS = 10


def _western_year(text: str) -> int | None:
    match = re.search(r"(\d+)\s*年", str(text or ""))
    return int(match.group(1)) + 1911 if match else None


def _amount(row: dict, *keys) -> float:
    return float(sum(float(row.get(k) or 0) for k in keys))


def build_events(policies: list[dict], results: list[dict], prices: list[dict]) -> pd.DataFrame:
    """每次除權息一列：所屬年度、除權息日、現金／股票股利、除權息前股價、殖利率、填息天數"""
    closes = sorted((p["date"], float(p["close"])) for p in prices if p.get("close"))
    before = {r["date"]: float(r["before_price"]) for r in results if r.get("before_price")}
    rows = []
    for policy in policies:
        cash = _amount(policy, "CashEarningsDistribution", "CashStatutorySurplus")
        stock = _amount(policy, "StockEarningsDistribution", "StockStatutorySurplus")
        if cash <= 0 and stock <= 0:
            continue
        ex_date = policy.get("CashExDividendTradingDate") or policy.get("StockExDividendTradingDate") or ""
        price = before.get(ex_date)
        rows.append({
            "fiscal_year": _western_year(policy.get("year")), "period": str(policy.get("year") or ""),
            "ex_date": ex_date or None, "cash": cash, "stock": stock, "before_price": price,
            # 股票股利每 1 元＝配 0.1 股，以除權前股價換算價值
            "yield_pct": (cash + stock / 10 * price) / price * 100 if price else None,
            "fill_days": _fill_days(closes, ex_date, price) if price else None,
        })
    # 股利政策資料偶爾比除權息結果晚更新：已經除息、但政策還沒進來的，用除權息結果補一列（所屬期間不明）
    known = {row["ex_date"] for row in rows}
    for result in results:
        amount = float(result.get("stock_and_cache_dividend") or 0)
        if result["date"] in known or amount <= 0 or result.get("stock_or_cache_dividend") != "息":
            continue
        price = before[result["date"]] if result["date"] in before else None
        rows.append({"fiscal_year": None, "period": "-", "ex_date": result["date"], "cash": amount, "stock": 0.0,
                     "before_price": price, "yield_pct": amount / price * 100 if price else None,
                     "fill_days": _fill_days(closes, result["date"], price) if price else None})
    frame = pd.DataFrame(rows, columns=["fiscal_year", "period", "ex_date", "cash", "stock", "before_price",
                                        "yield_pct", "fill_days"])
    return frame.sort_values("ex_date", na_position="last").reset_index(drop=True)


def _fill_days(closes: list[tuple[str, float]], ex_date: str, target: float) -> int | None:
    """除權息日當天算第 1 天；收盤 ≥ 除權息前收盤即填息。價格資料沒涵蓋到的回 None"""
    after = [c for d, c in closes if d >= ex_date]
    for index, close in enumerate(after, start=1):
        if close >= target:
            return index
    return None


def annual_table(events: pd.DataFrame, eps_by_year: dict[int, float] | None = None) -> pd.DataFrame:
    """依所屬年度加總；盈餘分配率只在有該年度 EPS 時計算"""
    eps_by_year = eps_by_year or {}
    frame = events.dropna(subset=["fiscal_year"])
    if frame.empty:
        return pd.DataFrame(columns=["fiscal_year", "cash", "stock", "total", "eps", "payout_pct"])
    table = frame.groupby("fiscal_year", as_index=False)[["cash", "stock"]].sum()
    table["fiscal_year"] = table["fiscal_year"].astype(int)
    table["total"] = table["cash"] + table["stock"]
    table["eps"] = table["fiscal_year"].map(eps_by_year)
    table["payout_pct"] = (table["cash"] / table["eps"].where(table["eps"] > 0)) * 100
    return table.sort_values("fiscal_year").reset_index(drop=True)


def consecutive_years(annual: pd.DataFrame, this_year: int) -> int:
    """連續配發現金股利的年數（從最近一個有配的年度往回數，中間斷一年就停）"""
    years = set(annual.loc[annual["cash"] > 0, "fiscal_year"])
    if not years:
        return 0
    year = max(y for y in years if y <= this_year)
    count = 0
    while year in years:
        count += 1
        year -= 1
    return count


def trailing_cash(events: pd.DataFrame, today: _date) -> float:
    """近一年（除息日在 365 天內）配發的現金股利合計"""
    since = (today - timedelta(days=365)).isoformat()
    recent = events[events["ex_date"].notna() & (events["ex_date"] >= since) & (events["ex_date"] <= today.isoformat())]
    return float(recent["cash"].sum())


def fetch(code: str, years: int = DEFAULT_YEARS, today: _date | None = None) -> pd.DataFrame:
    today = today or _date.today()
    start = (today - timedelta(days=365 * years)).isoformat()
    policies = finmind.fetch_dividends(code, start, today.isoformat())
    if not policies:
        return build_events([], [], [])
    results = finmind.fetch_dividend_results(code, start, today.isoformat())
    prices = finmind.fetch_stock_price(code, start, today.isoformat())
    return build_events(policies, results, prices)
