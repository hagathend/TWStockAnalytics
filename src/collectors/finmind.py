"""FinMind API 收集器：作為官方 OpenAPI 的補充/交叉驗證來源。

https://api.finmindtrade.com/api/v4/data
"""

import requests

from src.config import FINMIND_TOKEN

_BASE_URL = "https://api.finmindtrade.com/api/v4/data"
_TIMEOUT = 20


def _request(dataset: str, data_id: str, start_date: str, end_date: str) -> list[dict]:
    params = {
        "dataset": dataset,
        "data_id": data_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN

    resp = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        return []
    return payload.get("data", [])


def fetch_stock_price(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """個股每日收盤價量，欄位: date, stock_id, open, max, min, close, Trading_Volume ...

    暫停交易的日子 FinMind 會回傳開高低收全是 0 的列（例如 3665 貿聯-KY 2026-06-10），
    留著會讓均線、K 線被拉到 0、支撐壓力計算除以 0，所以直接去掉"""
    rows = _request("TaiwanStockPrice", stock_id, start_date, end_date)
    return [r for r in rows if all((r.get(k) or 0) > 0 for k in ("max", "min", "close"))]


def fetch_institutional_investors(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """個股三大法人買賣超，欄位: date, stock_id, name(Foreign_Investor/Investment_Trust/Dealer_self/Dealer_Hedging), buy, sell"""
    return _request("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start_date, end_date)


def fetch_margin_trading(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """個股融資融券，欄位: date, stock_id, MarginPurchaseTodayBalance, ShortSaleTodayBalance ..."""
    return _request("TaiwanStockMarginPurchaseShortSale", stock_id, start_date, end_date)


def fetch_dividends(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """股利政策（每次董事會／股東會決議一筆），欄位: year(所屬期間，如「114年第2季」), CashEarningsDistribution,
    CashStatutorySurplus, StockEarningsDistribution, StockStatutorySurplus, CashExDividendTradingDate ..."""
    return _request("TaiwanStockDividend", stock_id, start_date, end_date)


def fetch_dividend_results(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """除權息結果（實際除權息日），欄位: date, before_price(除權息前收盤), after_price, stock_and_cache_dividend"""
    return _request("TaiwanStockDividendResult", stock_id, start_date, end_date)
