"""台股每日資訊收集 - Streamlit UI

版面規則（見 src/ui.py）：頁面標題用 ui.page_header、每個獨立主題用 ui.panel 包成有邊框的區塊，
不要直接用 st.title / st.header / st.subheader，也不要用 emoji 當圖示。
"""

import sys
from pathlib import Path

# 用 `streamlit run src/app.py` 啟動時，Streamlit 只會把腳本所在的 src/ 加進 sys.path，
# 專案根目錄不在裡面，下面的 `from src.xxx import ...` 就會噴 ModuleNotFoundError: No module named 'src'。
# （改用 `python -m streamlit run` 剛好能動，是因為 -m 會把當前工作目錄加進 sys.path，屬於巧合。）
# 這裡主動把專案根目錄補進 sys.path，讓兩種啟動方式（含 start_ui.bat）都能正常運作。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os  # noqa: E402
from functools import partial  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import date as _date, timedelta  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402
import streamlit as st  # noqa: E402

from src.ai_analysis import (NEWS_TOP_N_OPTIONS, analyze_with_codex_deep, build_prompt,  # noqa: E402
                             news_top_n, parse_and_save)
from src.codex_cli import generate_codex_text, check_codex_login, list_codex_models
from src import charting
from src.chip_metrics import metrics_for_code
from src.chip_metrics import summarize_for_prompt as summarize_chip_metrics
from src.collect_all import run_daily_collect
from src.collectors.firecrawl_fetcher import test_connection as firecrawl_test_connection
from src.config_ai import (
    load_codex_settings,
    load_report_settings,
    load_scraping_settings,
    update_codex_settings,
    save_report_settings,
    save_scraping_settings,
)
from src import config_screener, config_watchlist, history, scheduled_ai
from src.config_watchlist import add_stocks, load_watchlist
from src.market_analysis import build_market_analysis_prompt, save_market_analysis
from src.report_pdf import markdown_to_pdf
from src import (alerts, backtest, calendar_events, desktop, financials, futures, pe_river, rankings, fundamentals, heatmap, market_breadth, market_index, notify, portfolio,
                 ownership, prediction_views, predictions,
                 revenue, shareholding, signals, ui, updater)
from src.config import IS_INSTALLED
from src.codex_cli import _executable as find_codex_executable
from src.config_app import load_app_settings, save_app_settings
from src.version import __version__
from src.stock_analysis import build_stock_analysis_prompt, save_stock_analysis, strip_holding_section
from src.storage import db

st.set_page_config(page_title="TWStockAnalytics", page_icon=str(_PROJECT_ROOT / "src/assets/brand.svg"), layout="wide")
ui.inject_css()

db.init_db()

_PRICE_COLUMNS = {
    "date": "日期",
    "market": "市場",
    "code": "代號",
    "name": "名稱",
    "open": "開盤價",
    "high": "最高價",
    "low": "最低價",
    "close": "收盤價",
    "change": "漲跌",
    "volume": "成交量(股)",
    "turnover": "成交金額(元)",
}

_INSTITUTIONAL_COLUMNS = {
    "date": "日期",
    "market": "市場",
    "code": "代號",
    "name": "名稱",
    "foreign_net": "外資買賣超(股)",
    "trust_net": "投信買賣超(股)",
    "dealer_net": "自營商買賣超(股)",
    "total_net": "三大法人合計(股)",
}

# 融資融券官方資料的單位是「張」（交易單位），不是股
_MARGIN_COLUMNS = {
    "date": "日期",
    "market": "市場",
    "code": "代號",
    "name": "名稱",
    "margin_balance": "融資餘額(張)",
    "margin_buy": "融資買進(張)",
    "margin_sell": "融資賣出(張)",
    "short_balance": "融券餘額(張)",
    "short_sell": "融券賣出(張)",
    "short_cover": "融券償還(張)",
}

_LOG_COLUMNS = {
    "id": "編號",
    "run_at": "執行時間",
    "step": "項目",
    "status": "狀態",
    "detail": "詳細",
}

_PICK_COLUMNS = {"rank": "排名", "code": "代號", "name": "名稱", "reason": "原因"}

# collect_log 的 status 存英文識別字，顯示時轉成中文（不用 emoji，改用文字顏色區分）
_LOG_STATUS_LABELS = {"success": "成功", "no_data": "無資料", "failed": "失敗"}
_LOG_STATUS_COLORS = {"成功": "#8FA3BF", "無資料": "#F5B942", "失敗": ui.UP_COLOR}


def _display_df(rows: list[dict], column_labels: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.rename(columns=column_labels)[
        [column_labels[c] for c in column_labels if c in df.columns]
    ]


def _styled_table(df: pd.DataFrame, signed: list[str] = (), thousands: list[str] = (), decimals: list[str] = ()):
    """表格共用樣式：正負數紅漲綠跌、千分位、小數兩位、缺值顯示「-」。

    st.dataframe 的前端對空值一律顯示「None」，不理會 Styler 的 na_rep；混合數字與「-」又會讓 Arrow 序列化失敗。
    所以有缺值的數值欄位整欄先格式化成文字（缺值「-」），沒有缺值的欄位維持數值、交給 Styler 格式化；
    紅漲綠跌一律依原始數值判斷。"""
    present = set(df.columns)
    specs = {c: ",.0f" for c in thousands if c in present} | {c: ",.2f" for c in decimals if c in present}
    signed_cols = [c for c in signed if c in present]
    df = df.copy()
    numeric = {}
    for column in {*specs, *signed_cols}:
        values = pd.to_numeric(df[column], errors="coerce")
        numeric[column] = values
        if values.isna().any():
            spec = specs.get(column)
            df[column] = ["-" if pd.isna(v) else (f"{v:{spec}}" if spec else f"{v:g}") for v in values]
        else:
            df[column] = values
    styler = df.style

    def _tones(col: pd.Series) -> list[str]:
        return [f"color: {ui.UP_COLOR}" if ui.tone_of(v) == "up" else f"color: {ui.DOWN_COLOR}" if ui.tone_of(v) == "down" else ""
                for v in numeric[col.name]]

    if signed_cols:
        styler = styler.apply(_tones, subset=signed_cols)
    for spec in (",.0f", ",.2f"):
        cols = [c for c, s_ in specs.items() if s_ == spec and not numeric[c].isna().any()]
        if cols:
            styler = styler.format(f"{{:{spec}}}", subset=cols)
    return styler


_CLICK_MAX_AGE = 3.0  # 秒：雙擊會送出兩次點擊，第二次可能在換頁後才到，太舊的點擊不理會


def _on_table_click(key: str):
    """表格選取改變時的回呼：點到儲存格就記下那一列（附時間），並把儲存格選取清掉、勾選框的列選取保留"""
    selection = (st.session_state.get(key) or {}).get("selection", {})
    cells = selection.get("cells") or []
    if cells:
        st.session_state[f"{key}__click"] = (cells[0][0], time.time())
        st.session_state[key] = {"selection": {"rows": list(selection.get("rows") or []), "columns": [], "cells": []}}


def _take_table_click(key: str) -> int | None:
    clicked = st.session_state.pop(f"{key}__click", None)
    if clicked and time.time() - clicked[1] <= _CLICK_MAX_AGE:
        return clicked[0]
    return None


def _clickable_table(data, key: str, **kwargs):
    """點任一格（單擊或雙擊）就回傳那一列的位置（沒點回傳 None）。只用「單格選取」，表格左邊不會出現勾選框"""
    st.dataframe(data, key=key, on_select=partial(_on_table_click, key), selection_mode="single-cell", **kwargs)
    return _take_table_click(key)


def _checkable_table(data, key: str, selected_rows: list[int] | None = None, **kwargs):
    """左邊有勾選框可以複選（搭配表格上方的按鈕），點其他儲存格則回傳那一列（開個股詳情用）。
    回傳 (勾選的列, 點到的列或 None)；selected_rows 是這個表格第一次畫出來時要預先勾選的列（換頁回來還原用）"""
    options = {"selection_default": {"selection": {"rows": selected_rows}}} if selected_rows else {}
    event = st.dataframe(data, key=key, on_select=partial(_on_table_click, key),
                         selection_mode=["multi-row", "single-cell"], **options, **kwargs)
    return list(event.selection.rows), _take_table_click(key)


def _clear_table_click(key: str):
    st.session_state[key] = {"selection": {"rows": [], "columns": [], "cells": []}}


def _md_linebreaks(text: str) -> str:
    """AI回覆通常一行一個重點，但 Markdown 規則裡單一換行會被當成空白吃掉、
    不會顯示成新的一行，要轉成 Markdown 的強制換行語法（兩個空白+換行）才會正確顯示。"""
    return (text or "").replace("\n", "  \n")


def _go_to_detail(code: str):
    """開個股詳情，並記住是從哪一頁來的（個股詳情上方會出現「返回」按鈕）"""
    origin = st.session_state.get("tw_nav_page")
    if origin and origin != "detail":
        st.session_state["detail_return"] = origin
    st.session_state["selected_code"] = code
    st.switch_page(DETAIL_PAGE)


def _run_collect_from_sidebar():
    with st.spinner("收集中（官方資料、FinMind、新聞來源）..."):
        result = run_daily_collect()
    st.success("收集完成")
    with st.expander("收集明細"):
        st.json(result)

    today = _date.today().isoformat()
    codex_settings = load_codex_settings()
    if codex_settings.get("auto_analyze_after_collect"):
        progress_bar = st.progress(0.0, text="準備深度分析（先抓內文再逐篇摘要，可能要幾分鐘）...")

        def _update_progress(cur, total, msg):
            progress_bar.progress(cur / total if total else 0.0, text=f"{msg} ({cur}/{total})")

        ai_result = analyze_with_codex_deep(today, progress_callback=_update_progress)
        progress_bar.empty()
        if ai_result["ok"]:
            st.success(f"AI 深度分析完成，已產生 {len(ai_result['picks'])} 檔新聞焦點")
        else:
            st.warning(f"自動 AI 分析失敗（可到「AI 分析」頁改用複製貼上）：{ai_result['message']}")
    else:
        ok, prompt_or_msg = build_prompt(today)
        if ok:
            st.session_state["pending_ai_prompt"] = prompt_or_msg
            st.info("新聞分析提示詞已產生，請到「AI 分析」頁複製使用")


def _render_sidebar() -> str:
    """畫出各頁共用的側邊欄（收集按鈕、查詢日期、新聞焦點），回傳目前選擇的查詢日期。
    區塊標題一律用 ui.sidebar_label（比導覽列小一級的灰字），不要用 st.header。"""
    with st.sidebar:
        ui.sidebar_label("資料收集")
        if st.button("立即收集今日資料", type="primary", width="stretch"):
            _run_collect_from_sidebar()

        ui.sidebar_label("查詢日期")
        available_dates = db.query_available_dates()
        if available_dates:
            selected_date = st.selectbox("查詢日期", available_dates, label_visibility="collapsed")
        else:
            selected_date = st.text_input(
                "查詢日期", value=_date.today().isoformat(), label_visibility="collapsed"
            )

        ui.sidebar_label(f"新聞焦點 Top {news_top_n()}")
        ai_picks = db.query_ai_picks(selected_date)
        if ai_picks:
            for pick in ai_picks:
                label = f"{pick['rank']:>2}.　{pick['code']}　{pick['name']}"
                if st.button(label, key=f"pick_{pick['code']}_{pick['rank']}", type="tertiary",
                             width="stretch", help=pick.get("reason")):
                    _go_to_detail(pick["code"])
        else:
            st.caption("此日期尚無 AI 分析結果")

    return selected_date


# ─────────────────────────────── 總覽 ───────────────────────────────


def _market_summary_cards(selected_date: str):
    # 只算個股：價量表混有上萬筆上櫃權證、法人表混有權證與 ETF，直接加總會失真
    price_rows = [r for r in db.query_stock_price(selected_date) if db.is_stock_code(r["code"])]
    inst_rows = [r for r in db.query_institutional(selected_date) if db.is_stock_code(r["code"])]
    news_rows = db.query_news(selected_date)
    up = sum(1 for r in price_rows if (r.get("change") or 0) > 0)
    down = sum(1 for r in price_rows if (r.get("change") or 0) < 0)
    total_net = sum(r.get("total_net") or 0 for r in inst_rows)
    ui.cards([
        {"label": "上漲家數（個股）", "value": f"{up:,}", "tone": "up" if up else ""},
        {"label": "下跌家數", "value": f"{down:,}", "tone": "down" if down else ""},
        {"label": "持平／無交易", "value": f"{len(price_rows) - up - down:,}"},
        {"label": "法人合計（個股）", "value": f"{total_net / 1000:+,.0f} 張" if inst_rows else "無資料",
         "tone": ui.tone_of(total_net) if inst_rows else ""},
        {"label": "新聞則數", "value": f"{len(news_rows):,}"},
    ])


_INDUSTRY_COLUMNS = {
    "industry": "產業", "count": "家數", "weighted_change": "成交值加權漲跌%", "avg_change": "平均漲跌%",
    "up_ratio": "上漲家數比例%", "turnover_share": "成交值占比%",
}


@st.cache_data(ttl=600, show_spinner=False)
def _cached_breadth(date: str) -> pd.DataFrame:
    return market_breadth.breadth_until(date)


def _render_market_thermometer(selected_date: str):
    breadth = _cached_breadth(selected_date)
    with ui.panel("市場溫度計", "上市個股・收盤創 N 日新高／新低家數；新高多於新低代表上漲較普遍"):
        if breadth.empty:
            st.caption("本地資料庫沒有足夠的上市歷史資料")
            return
        last = breadth.iloc[-1]

        def _count(value):
            return "-" if pd.isna(value) else f"{int(value):,}"

        ad = last["ad_ratio"]
        heat = last["turnover_ma20_ratio"]
        index = market_index.index_summary(selected_date)
        index_card = [] if not index else [{
            "label": f"加權指數（{index['date'][5:]}）", "value": f"{index['taiex']:,.0f}",
            "sub": f"{index['change']:+,.0f} 點（{index['change_pct']:+.2f}%）", "sub_tone": ui.tone_of(index["change"]),
        }]
        ui.cards(index_card + [
            {"label": "漲跌家數比", "value": "-" if pd.isna(ad) else f"{ad:.2f}",
             "tone": "" if pd.isna(ad) else ("up" if ad > 1 else "down" if ad < 1 else ""),
             "sub": f"上漲 {int(last['up'])}／下跌 {int(last['down'])}"},
            {"label": "創 20 日新高", "value": _count(last["new_high_20"]), "tone": "up"},
            {"label": "創 20 日新低", "value": _count(last["new_low_20"]), "tone": "down"},
            {"label": "創 60 日新高／新低", "value": f"{_count(last['new_high_60'])}／{_count(last['new_low_60'])}"},
            {"label": "成交值熱度", "value": "-" if pd.isna(heat) else f"{heat:.2f} 倍",
             "sub": "相對前 20 日平均"},
        ])
        recent = breadth.dropna(subset=["new_high_20"]).tail(60)
        if len(recent) >= 2:
            fig = go.Figure()
            fig.add_bar(x=recent["date"], y=recent["new_high_20"], name="創 20 日新高", marker_color=ui.UP_COLOR)
            fig.add_bar(x=recent["date"], y=-recent["new_low_20"], name="創 20 日新低", marker_color=ui.DOWN_COLOR,
                        customdata=recent["new_low_20"], hovertemplate="%{x}<br>創 20 日新低 %{customdata} 家<extra></extra>")
            fig.update_layout(barmode="relative", bargap=0.15, yaxis_title="家數")
            fig.update_xaxes(type="category", nticks=10)
            st.plotly_chart(ui.style_chart(fig, height=280), width="stretch", key="breadth_chart")


def _render_adl(selected_date: str):
    """騰落線與加權指數：指數創高但騰落線沒跟上，代表上漲集中在少數權值股"""
    breadth = _cached_breadth(selected_date)
    if len(breadth) < 2:
        return
    recent = breadth.tail(120)
    index = pd.DataFrame(db.query_market_index(recent["date"].iloc[0], selected_date))
    with ui.panel("騰落線（ADL）", "每天上漲家數減下跌家數的累計（上市個股）・和加權指數對照：指數上漲但騰落線走平或下滑，"
                                  "代表上漲集中在少數股票"):
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_scatter(x=recent["date"], y=recent["adl"], mode="lines", name="騰落線",
                        line={"color": ui.ACCENT_COLOR, "width": 2.2}, secondary_y=False)
        if not index.empty:
            fig.add_scatter(x=index["date"], y=index["taiex"], mode="lines", name="加權指數",
                            line={"color": "#8792A6", "width": 1.4}, secondary_y=True)
        fig.update_xaxes(type="category", nticks=10)
        fig.update_yaxes(title_text="累計家數", secondary_y=False)
        fig.update_yaxes(title_text="加權指數", secondary_y=True, showgrid=False)
        st.plotly_chart(ui.style_chart(fig, height=300), width="stretch", key="adl_chart")


def _lots_change(frame: pd.DataFrame, column: str, n: int) -> int | None:
    return int(frame[column].iloc[-1] - frame[column].iloc[-1 - n]) if len(frame) > n else None


def _render_margin_trend(selected_date: str):
    """大盤（上市個股）融資、融券餘額合計的走勢；融資大增而指數沒漲，代表散戶追價、籌碼變亂"""
    since = (_date.fromisoformat(selected_date) - timedelta(days=180)).isoformat()
    frame = pd.DataFrame(db.query_margin_totals(since, selected_date))
    if len(frame) < 2:
        return
    last = frame.iloc[-1]
    ratio = last["short_balance"] / last["margin_balance"] * 100 if last["margin_balance"] else None
    with ui.panel("大盤融資融券", f"上市個股合計・資料日 {last['date']}・單位：張"):
        cards = []
        for label, column in (("融資餘額", "margin_balance"), ("融券餘額", "short_balance")):
            day, week = _lots_change(frame, column, 1), _lots_change(frame, column, 5)
            sub = "較前一日 " + ("-" if day is None else f"{day:+,}") + "・5 日 " + ("-" if week is None else f"{week:+,}")
            cards.append({"label": label, "value": f"{int(last[column]):,}", "sub": sub, "sub_tone": ui.tone_of(day or 0)})
        cards.append({"label": "券資比", "value": "-" if ratio is None else f"{ratio:.2f}%", "sub": "融券 ÷ 融資"})
        ui.cards(cards)
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_scatter(x=frame["date"], y=frame["margin_balance"], mode="lines", name="融資餘額",
                        line={"color": ui.UP_COLOR, "width": 2}, secondary_y=False)
        fig.add_scatter(x=frame["date"], y=frame["short_balance"], mode="lines", name="融券餘額",
                        line={"color": ui.DOWN_COLOR, "width": 1.6}, secondary_y=True)
        fig.update_xaxes(type="category", nticks=10)
        fig.update_yaxes(title_text="融資（張）", secondary_y=False)
        fig.update_yaxes(title_text="融券（張）", secondary_y=True, showgrid=False)
        st.plotly_chart(ui.style_chart(fig, height=280), width="stretch", key="margin_trend_chart")


def _render_futures_panel(selected_date: str):
    frame = futures.net_oi_frame(selected_date)
    summary = futures.summary(selected_date)
    if frame.empty or not summary:
        st.info("尚無期貨三大法人資料，請先收集資料或執行 scripts/backfill_history.py")
        return
    with ui.panel("期貨三大法人未平倉", f"臺股期貨多空未平倉口數淨額（{summary['date']}）・正＝淨多單、負＝淨空單；"
                                   "期貨部位也可能是現貨的避險"):
        cards = []
        for key, label in futures.IDENTITY_LABELS.items():
            value = summary[key]
            if value is None:
                continue
            day, week = summary[f"{key}_change_1"], summary[f"{key}_change_5"]
            sub = "較前一日 " + ("-" if day is None else f"{day:+,}") + "・5 日 " + ("-" if week is None else f"{week:+,}")
            cards.append({"label": label, "value": f"{value:+,} 口", "tone": ui.tone_of(value),
                          "sub": sub, "sub_tone": ui.tone_of(day or 0)})
        ui.cards(cards)
        recent = frame.tail(60)
        if len(recent) >= 2:
            fig = go.Figure()
            colors = {"foreign": ui.ACCENT_COLOR, "trust": "#e0a84f", "dealer": "#8792a6"}
            for key, label in futures.IDENTITY_LABELS.items():
                fig.add_scatter(x=recent["date"], y=recent[key], mode="lines", name=label,
                                line={"color": colors[key], "width": 2.2 if key == "foreign" else 1.5},
                                hovertemplate=f"%{{x}}<br>{label} %{{y:+,}} 口<extra></extra>")
            fig.add_hline(y=0, line={"color": "rgba(201, 209, 222, 0.35)", "width": 1})
            fig.update_layout(yaxis_title="淨未平倉口數")
            fig.update_xaxes(type="category", nticks=10)
            st.plotly_chart(ui.style_chart(fig, height=280), width="stretch", key="futures_oi_chart")


@st.cache_data(ttl=600, show_spinner=False)
def _cached_ranking_table(date: str) -> pd.DataFrame:
    return rankings.daily_table(date)


_RANK_COLUMNS = {
    "rank": "名次", "code": "代號", "name": "名稱", "market": "市場", "close": "收盤", "change_pct": "漲跌%",
    "volume_lots": "成交量(張)", "turnover_billion": "成交值(億)", "turnover_rate": "週轉率%",
    "foreign_lots": "外資(張)", "trust_lots": "投信(張)", "dividend_yield": "殖利率%",
}


def _render_rankings(selected_date: str):
    col_metric, col_market = st.columns([4, 1.2], vertical_alignment="bottom")
    metric = col_metric.pills("排行項目", list(rankings.METRICS), default="漲幅", key="rank_metric") or "漲幅"
    market = col_market.segmented_control("市場", list(rankings.MARKETS), default="全部", key="rank_market") or "全部"
    table = _cached_ranking_table(selected_date)
    result = rankings.rank(table, metric, market)
    note = "週轉率只有上市股（需要發行股數）" if metric == "週轉率" else "只算個股，不含 ETF 與權證"
    with ui.panel(f"{metric}排行", f"{selected_date}・{market}・前 {len(result)} 名・{note}・點一下股票開啟個股詳情"):
        if result.empty:
            st.caption("這天沒有資料")
            return
        view = result.assign(rank=range(1, len(result) + 1), market=result["market"].map({"TWSE": "上市", "TPEx": "上櫃"}))
        view = view[list(_RANK_COLUMNS)].rename(columns=_RANK_COLUMNS)
        styler = _styled_table(view, signed=["漲跌%", "外資(張)", "投信(張)"],
                               thousands=["成交量(張)", "外資(張)", "投信(張)"],
                               decimals=["收盤", "漲跌%", "成交值(億)", "週轉率%", "殖利率%"])
        clicked = _clickable_table(styler, "rank_table", width="stretch", hide_index=True, height=600)
        if clicked is not None and clicked < len(result):
            _go_to_detail(result.iloc[clicked]["code"])


def _render_industry_heatmap(selected_date: str):
    with ui.panel("產業熱力圖", "方塊大小＝成交值、顏色＝漲跌幅（紅漲綠跌）・點產業可放大，點上方路徑返回"):
        col_market, _ = st.columns([1, 3])
        market = col_market.segmented_control("市場", list(heatmap.MARKET_OPTIONS), default="上市",
                                              key="heatmap_market", label_visibility="collapsed") or "上市"
        df = heatmap.industry_frame(selected_date, heatmap.MARKET_OPTIONS[market])
        if df.empty:
            st.caption("此日期沒有股價資料")
            return
        summary = heatmap.industry_summary(df)
        st.plotly_chart(heatmap.build_treemap(df, summary), width="stretch", key="industry_treemap")
        with st.expander("產業彙總表"):
            view = summary[list(_INDUSTRY_COLUMNS)].rename(columns=_INDUSTRY_COLUMNS)
            pct = ["成交值加權漲跌%", "平均漲跌%", "上漲家數比例%", "成交值占比%"]
            st.dataframe(_styled_table(view, signed=["成交值加權漲跌%", "平均漲跌%"], decimals=pct),
                         width="stretch", hide_index=True)


def home_page():
    selected_date = _render_sidebar()
    ui.page_header("市場總覽", f"{selected_date} 盤後價量、三大法人、融資融券與新聞")

    _market_summary_cards(selected_date)

    tab, body = ui.page_tabs("home", NAV_TABS["home"])
    with body:
        if tab == "市場溫度計":
            _render_market_thermometer(selected_date)
            _render_adl(selected_date)
        elif tab == "期貨法人":
            _render_futures_panel(selected_date)
        elif tab == "產業熱力圖":
            _render_industry_heatmap(selected_date)
        elif tab == "排行":
            _render_rankings(selected_date)
        elif tab == "股價":
            filter_code = st.text_input("搜尋", placeholder="依代號或名稱搜尋，例如 2330 或 台積",
                                        key="price_code", label_visibility="collapsed")
            rows = db.query_stock_price(selected_date, filter_code or None)
            if rows:
                df = _display_df(rows, _PRICE_COLUMNS)
                st.dataframe(
                    _styled_table(df, signed=["漲跌"], thousands=["成交量(股)", "成交金額(元)"],
                                  decimals=["開盤價", "最高價", "最低價", "收盤價", "漲跌"]),
                    width="stretch", hide_index=True, height=520,
                )
                st.caption(f"共 {len(df):,} 筆")
            else:
                st.info("此日期尚無股價資料，請先點擊左側「立即收集今日資料」")

        elif tab == "三大法人":
            filter_code = st.text_input("搜尋", placeholder="依代號或名稱搜尋", key="inst_code",
                                        label_visibility="collapsed")
            rows = db.query_institutional(selected_date, filter_code or None)
            if rows:
                df = _display_df(rows, _INSTITUTIONAL_COLUMNS)
                net_cols = [c for c in df.columns if "(股)" in c]
                st.dataframe(_styled_table(df, signed=net_cols, thousands=net_cols),
                             width="stretch", hide_index=True, height=520)
                st.caption(f"共 {len(df):,} 筆")
            else:
                st.info("此日期尚無三大法人資料")

        elif tab == "融資融券":
            _render_margin_trend(selected_date)
            filter_code = st.text_input("搜尋", placeholder="依代號或名稱搜尋", key="margin_code",
                                        label_visibility="collapsed")
            rows = db.query_margin(selected_date, filter_code or None)
            if rows:
                df = _display_df(rows, _MARGIN_COLUMNS)
                st.dataframe(_styled_table(df, thousands=[c for c in df.columns if "(張)" in c]),
                             width="stretch", hide_index=True, height=520)
                st.caption(f"共 {len(df):,} 筆")
            else:
                st.info("此日期尚無融資融券資料")

        elif tab == "新聞":
            filter_code = st.text_input("搜尋", placeholder="依代號或標題關鍵字搜尋", key="news_code",
                                        label_visibility="collapsed")
            rows = db.query_news(selected_date, filter_code or None)
            if rows:
                for row in rows:
                    meta = [row["source"]]
                    if row.get("related_code"):
                        meta.append(f"關聯 {row['related_code']}")
                    if row.get("published_at"):
                        meta.append(row["published_at"])
                    ui.news_item(row["title"], row.get("url"), "・".join(meta),
                                 ui.strip_html(row.get("summary") or ""))
                st.caption(f"共 {len(rows):,} 則")
            else:
                st.info("此日期尚無新聞資料")

        elif tab == "收集紀錄":
            logs = db.query_recent_logs()
            if logs:
                logs = [{**row, "status": _LOG_STATUS_LABELS.get(row["status"], row["status"])} for row in logs]
                df = _display_df(logs, _LOG_COLUMNS)
                styler = df.style.map(lambda v: f"color: {_LOG_STATUS_COLORS.get(v, '')}" if v in _LOG_STATUS_COLORS else "",
                                      subset=["狀態"])
                st.dataframe(styler, width="stretch", hide_index=True, height=520)
            else:
                st.info("尚無收集紀錄")


# ─────────────────────────────── 個股詳情 ───────────────────────────────


def _lots(value) -> str:
    return "資料不足" if value is None else f"{value / 1000:+,.0f} 張"


def _streak_text(value: int) -> str:
    return f"連買 {value} 天" if value > 0 else f"連賣 {-value} 天" if value < 0 else "無連續"


def _render_quote(code: str, name: str):
    rows = db.query_code_history("stock_price", code, limit=1)
    if not rows:
        ui.quote_header(code, name)
        return
    last = rows[0]
    close, change = last.get("close"), last.get("change")
    change_pct = None
    if close is not None and change is not None and close - change:
        change_pct = change / (close - change) * 100
    ui.quote_header(code, name, close, change, change_pct, last["date"])


def _render_chip_panel(code: str):
    with ui.panel("籌碼", "依本地累積的法人／融資歷史計算"):
        metrics = metrics_for_code(code)
        if not metrics:
            st.caption("尚無籌碼歷史資料")
        else:
            margin_change = metrics["margin_change_5d"]
            ratio = metrics["inst_volume_ratio_5d"]
            short_ratio = metrics["short_margin_ratio"]
            ui.cards([
                {"label": "外資", "value": _streak_text(metrics["foreign_streak"]),
                 "tone": ui.tone_of(metrics["foreign_streak"]),
                 "sub": f"5日 {_lots(metrics['foreign_net_5d'])}", "sub_tone": ui.tone_of(metrics["foreign_net_5d"])},
                {"label": "投信", "value": _streak_text(metrics["trust_streak"]),
                 "tone": ui.tone_of(metrics["trust_streak"]),
                 "sub": f"5日 {_lots(metrics['trust_net_5d'])}", "sub_tone": ui.tone_of(metrics["trust_net_5d"])},
                {"label": "三大法人 20 日", "value": _lots(metrics["total_net_20d"]),
                 "tone": ui.tone_of(metrics["total_net_20d"]),
                 "sub": f"5日 {_lots(metrics['total_net_5d'])}", "sub_tone": ui.tone_of(metrics["total_net_5d"])},
                {"label": "法人佔成交量（5日）", "value": "資料不足" if ratio is None else f"{ratio:+.1f}%",
                 "tone": ui.tone_of(ratio)},
                {"label": "融資 5 日變化", "value": "無資料" if margin_change is None else f"{margin_change:+,.0f} 張",
                 "sub": "券資比 " + ("-" if short_ratio is None else f"{short_ratio:.1f}%")},
            ])

        latest = signals.latest_rows(_cached_signal_history())
        row = latest[latest["code"] == code] if not latest.empty else latest
        if not row.empty:
            active = signals.active_signals(row.iloc[0])
            st.caption(f"今日訊號（{row.iloc[0]['date']}）")
            ui.chips([(signals.SIGNALS[k], "down" if k in signals.BEARISH_SIGNALS else "up") for k in active],
                     empty_text="今日無觸發訊號")

        if metrics:
            with st.expander("完整籌碼指標文字（與送給 AI 的內容相同）"):
                st.text(summarize_chip_metrics(metrics))


def _render_shareholding_panel(code: str):
    summary = shareholding.code_summary(code)
    with ui.panel("股權分散（集保）", f"每週資料・{summary['date']}・已累積 {summary['weeks']} 週" if summary else "每週資料"):
        if not summary:
            st.caption("尚無集保股權分散資料（每日收集時會抓最新一週）")
            return

        def _pp(value):
            return None if value is None else f"週變化 {value:+.2f} 個百分點"

        holders_change = summary.get("holders_change_pct")
        ui.cards([
            {"label": "千張以上大戶", "value": f"{summary['big1000_pct']:.2f}%",
             "sub": _pp(summary["big1000_pct_change"]), "sub_tone": ui.tone_of(summary["big1000_pct_change"])},
            {"label": "400 張以上大戶", "value": f"{summary['big400_pct']:.2f}%",
             "sub": _pp(summary["big400_pct_change"]), "sub_tone": ui.tone_of(summary["big400_pct_change"])},
            {"label": "50 張以下散戶", "value": f"{summary['retail_pct']:.2f}%",
             "sub": _pp(summary["retail_pct_change"])},
            {"label": "總股東人數", "value": f"{summary['total_holders']:,}" if summary.get("total_holders") else "-",
             "sub": None if holders_change is None else f"週變化 {holders_change:+.2f}%"},
        ])
        history = db.query_shareholding_history(code)
        if len(history) >= 2:
            df = pd.DataFrame(history)
            fig = px.line(df, x="date", y=["big1000_pct", "big400_pct"], markers=True,
                          labels={"value": "持股比例%", "date": "", "variable": ""},
                          color_discrete_sequence=[ui.UP_COLOR, "#F5B942"])
            fig.for_each_trace(lambda t: t.update(name={"big1000_pct": "千張以上", "big400_pct": "400 張以上"}[t.name]))
            st.plotly_chart(ui.style_chart(fig, height=260), width="stretch")
        else:
            st.caption("累積兩週以上資料後會顯示大戶持股趨勢圖")


def _render_fundamentals_panel(code: str):
    data = db.query_code_fundamentals(code)
    valuation, revenue = data["valuation"], data["revenue"]
    with ui.panel("基本面", f"估值日 {valuation['date']}" if valuation else None):
        if not valuation and not revenue:
            st.caption("尚無基本面資料")
            return

        def _fmt(value, spec, suffix=""):
            return "無資料" if value is None else f"{value:{spec}}{suffix}"

        items = []
        if valuation:
            items += [
                {"label": "本益比", "value": _fmt(valuation["pe_ratio"], ".2f"),
                 "sub": "無資料通常代表近四季虧損" if valuation["pe_ratio"] is None else None},
                {"label": "殖利率", "value": _fmt(valuation["dividend_yield"], ".2f", "%")},
                {"label": "股價淨值比", "value": _fmt(valuation["pb_ratio"], ".2f")},
            ]
        if revenue:
            r = revenue[0]
            items.append({"label": f"{r['year_month']} 營收年增", "value": _fmt(r["yoy_pct"], "+.1f", "%"),
                          "tone": ui.tone_of(r["yoy_pct"]),
                          "sub": f"月增 {_fmt(r['mom_pct'], '+.1f', '%')}", "sub_tone": ui.tone_of(r["mom_pct"])})
        ui.cards(items)


def _render_revenue_panel(code: str):
    history = revenue.code_history(code)
    if len(history) < 2:
        return
    signal = revenue.compute_signals(history.assign(code=code)).iloc[0]
    notes = [f"{len(history)} 個月"]
    if signal["revenue_high_12m"]:
        notes.append("最新月營收創 12 個月新高")
    if signal["yoy_growth_streak"]:
        notes.append(f"年增率連續成長 {int(signal['yoy_growth_streak'])} 個月")
    with ui.panel("月營收趨勢", "・".join(notes)):
        fig = go.Figure()
        fig.add_bar(x=history["year_month"], y=history["revenue"] / 100_000, name="營收（億元）",
                    marker_color=ui.ACCENT_COLOR, hovertemplate="%{x}<br>營收 %{y:,.2f} 億<extra></extra>")
        fig.add_scatter(x=history["year_month"], y=history["yoy_pct"], name="年增率%", yaxis="y2", mode="lines+markers",
                        line={"color": "#F5B942", "width": 2}, hovertemplate="%{x}<br>年增 %{y:+.1f}%<extra></extra>")
        fig.update_layout(yaxis={"title": "億元"}, yaxis2={"title": "年增率%", "overlaying": "y", "side": "right",
                                                           "showgrid": False, "zeroline": True, "zerolinecolor": "#3A4356"})
        fig.update_xaxes(type="category")
        st.plotly_chart(ui.style_chart(fig, height=300), width="stretch", key=f"revenue_chart_{code}")


def _render_relative_strength_panel(code: str):
    frame = market_index.relative_strength(code)
    if len(frame) < 2:
        return
    excess = market_index.excess_returns(frame)
    notes = []
    for n, item in excess.items():
        if item:
            notes.append(f"近 {n} 日超額 {item['excess']:+.1f} 個百分點")
    with ui.panel("相對大盤", "・".join(notes) or "個股與加權指數以期初為 100 比較"):
        fig = go.Figure()
        fig.add_scatter(x=frame["date"], y=frame["stock_index"], name="個股", mode="lines",
                        line={"color": ui.ACCENT_COLOR, "width": 2})
        fig.add_scatter(x=frame["date"], y=frame["taiex_index"], name="加權指數", mode="lines",
                        line={"color": "#8792A6", "width": 1.5, "dash": "dot"})
        fig.add_hline(y=100, line_color="#3A4356", line_width=1)
        fig.update_layout(yaxis_title="期初＝100")
        fig.update_xaxes(type="category", nticks=8)
        st.plotly_chart(ui.style_chart(fig, height=260), width="stretch", key=f"rs_chart_{code}")


def _render_ownership_panel(code: str):
    summary = ownership.code_summary(code)
    if not summary:
        return
    with ui.panel("外資持股與借券賣出", "證交所每日資料・上市股"):
        def _pp(value):
            return None if value is None else f"20 日 {value:+.2f} 個百分點"

        items = []
        if summary["foreign_pct"] is not None:
            items.append({"label": "外資持股比例", "value": f"{summary['foreign_pct']:.2f}%",
                          "sub": _pp(summary["foreign_change_20"]), "sub_tone": ui.tone_of(summary["foreign_change_20"])})
        if summary["sbl_lots"] is not None:
            change = summary["sbl_change_20"]
            items.append({"label": "借券賣出餘額", "value": f"{summary['sbl_lots']:,.0f} 張",
                          "sub": None if change is None else f"20 日 {change:+,.0f} 張",
                          # 借券賣出增加是潛在賣壓，顏色刻意反過來：增加顯示綠色
                          "sub_tone": None if change is None else ("down" if change > 0 else "up" if change < 0 else "")})
            if summary["sbl_days_of_volume"] is not None:
                items.append({"label": "借券餘額相當成交量", "value": f"{summary['sbl_days_of_volume']:.1f} 天",
                              "sub": "餘額 ÷ 20 日平均成交量"})
        ui.cards(items)

        foreign, sbl = summary["foreign"], summary["sbl"]
        if len(foreign) >= 2 or len(sbl) >= 2:
            fig = go.Figure()
            if len(sbl) >= 2:
                fig.add_bar(x=sbl["date"], y=sbl["balance"] / 1000, name="借券賣出餘額（張）", marker_color="#3A4A66",
                            hovertemplate="%{x}<br>借券賣出餘額 %{y:,.0f} 張<extra></extra>")
            if len(foreign) >= 2:
                fig.add_scatter(x=foreign["date"], y=foreign["foreign_pct"], name="外資持股比例%", yaxis="y2",
                                mode="lines", line={"color": "#F5B942", "width": 2},
                                hovertemplate="%{x}<br>外資持股 %{y:.2f}%<extra></extra>")
            fig.update_layout(yaxis={"title": "張"}, yaxis2={"title": "%", "overlaying": "y", "side": "right",
                                                            "showgrid": False})
            fig.update_xaxes(type="category", nticks=8)
            st.plotly_chart(ui.style_chart(fig, height=260), width="stretch", key=f"ownership_chart_{code}")


def _render_financials_panel(code: str):
    frame = financials.code_frame(code)
    if frame.empty:
        return
    last = frame.iloc[-1]

    def num(v, spec, suffix=""):
        return "-" if v is None or pd.isna(v) else f"{v:{spec}}{suffix}"

    with ui.panel("季度財報", f"最新 {last['label']}・毛利率與營益率為單季・ROE 以累計淨利年化"):
        ui.cards([
            {"label": f"{last['label']} 單季 EPS", "value": num(last["eps_q"], ".2f", " 元"),
             "sub": f"累計 {num(last['eps_cum'], '.2f', ' 元')}", "tone": ui.tone_of(last["eps_q"])},
            {"label": "近四季 EPS", "value": num(last["eps_ttm"], ".2f", " 元")},
            {"label": "毛利率", "value": num(last["gross_margin"], ".1f", "%"),
             "sub": f"營益率 {num(last['operating_margin'], '.1f', '%')}"},
            {"label": "ROE（年化）", "value": num(last["roe_annualized"], ".1f", "%")},
        ])
        if len(frame) >= 2:
            fig = go.Figure()
            fig.add_bar(x=frame["label"], y=frame["eps_q"], name="單季 EPS（元）",
                        marker_color=[ui.UP_COLOR if (v or 0) >= 0 else ui.DOWN_COLOR for v in frame["eps_q"].fillna(0)],
                        hovertemplate="%{x}<br>單季 EPS %{y:.2f} 元<extra></extra>")
            if frame["gross_margin"].notna().any():
                fig.add_scatter(x=frame["label"], y=frame["gross_margin"], name="毛利率%", yaxis="y2",
                                mode="lines+markers", line={"color": "#F5B942", "width": 2})
            if frame["operating_margin"].notna().any():
                fig.add_scatter(x=frame["label"], y=frame["operating_margin"], name="營益率%", yaxis="y2",
                                mode="lines+markers", line={"color": "#A78BFA", "width": 2})
            fig.update_layout(yaxis={"title": "元"}, yaxis2={"title": "%", "overlaying": "y", "side": "right",
                                                            "showgrid": False})
            fig.update_xaxes(type="category")
            st.plotly_chart(ui.style_chart(fig, height=280), width="stretch", key=f"financials_chart_{code}")


_RIVER_COLORS = {10: "rgba(34, 181, 115, 0.22)", 25: "rgba(34, 181, 115, 0.12)", 50: "rgba(135, 146, 166, 0.10)",
                 75: "rgba(240, 82, 79, 0.12)", 90: "rgba(240, 82, 79, 0.22)"}


def _render_pe_river_panel(code: str):
    results = {key: pe_river.river(code, metric=key) for key in pe_river.METRICS}
    available = [key for key, value in results.items() if value]
    if not available:
        return
    with ui.panel("河流圖", "用這檔自己過去的倍數區間畫出價格帶，看目前股價偏貴還是偏便宜；只比較自己的歷史，不同產業不能互比"):
        labels = {key: pe_river.METRICS[key]["label"] for key in available}
        key = st.segmented_control("倍數", available, default=available[0], format_func=labels.get,
                                   key=f"river_metric_{code}") or available[0]
        result = results[key]
        frame, multiples = result["frame"], result["multiples"]
        percentile = result["percentile"]
        position = "偏便宜" if percentile <= 25 else "偏貴" if percentile >= 75 else "中間"
        st.caption(f"{labels[key]}目前 {result['current_pe']:.2f} 倍・位於近 {result['days']} 個交易日第 "
                   f"{percentile:.0f} 百分位（{position}）・價格帶＝推算的{pe_river.METRICS[key]['base']} × 歷史倍數")
        fig = go.Figure()
        levels = list(pe_river.BAND_PERCENTILES)
        for i, p in enumerate(levels):
            fig.add_scatter(x=frame["date"], y=frame[f"band_{p}"], mode="lines", name=f"{multiples[p]:.2f} 倍（{p}%）",
                            line={"width": 1, "color": "rgba(201, 209, 222, 0.35)"},
                            fill="tonexty" if i else None, fillcolor=_RIVER_COLORS[p],
                            hovertemplate=f"%{{x}}<br>{multiples[p]:.2f} 倍價格 %{{y:,.2f}}<extra></extra>")
        fig.add_scatter(x=frame["date"], y=frame["close"], mode="lines", name="收盤價",
                        line={"color": ui.ACCENT_COLOR, "width": 2.2})
        fig.update_xaxes(type="category", nticks=8)
        st.plotly_chart(ui.style_chart(fig, height=320), width="stretch", key=f"river_{key}_{code}")


def _render_history_panel(code: str):
    with ui.panel("法人與融資歷史", "本地資料庫累積，每個交易日一筆"):
        tab_inst, tab_margin = st.tabs(["三大法人買賣超", "融資融券"])
        with tab_inst:
            rows = db.query_code_history("institutional", code)
            if rows:
                df = _display_df(rows, _INSTITUTIONAL_COLUMNS).drop(columns=["市場", "代號", "名稱"])
                net_cols = [c for c in df.columns if "(股)" in c]
                st.dataframe(_styled_table(df, signed=net_cols, thousands=net_cols),
                             width="stretch", hide_index=True, height=320)
            else:
                st.caption("尚無資料")
        with tab_margin:
            rows = db.query_code_history("margin", code)
            if rows:
                df = _display_df(rows, _MARGIN_COLUMNS).drop(columns=["市場", "代號", "名稱"])
                st.dataframe(_styled_table(df, thousands=[c for c in df.columns if "(張)" in c]),
                             width="stretch", hide_index=True, height=320)
            else:
                st.caption("尚無資料")


def _render_stock_ai_panel(code: str):
    with ui.panel("AI 個股分析", "Codex CLI 依技術面、籌碼、基本面與新聞分析，儲存後收錄每日報告"):
        col1, col2, _ = st.columns([1.3, 1.1, 2])
        if col1.button("用 Codex 分析並儲存", key="codex_stock", type="primary",
                       width="stretch"):
            with st.spinner("Codex 正在分析個股..."):
                ok, text = generate_codex_text(build_stock_analysis_prompt(code))
                if ok:
                    result = save_stock_analysis(code, text)
                    (st.success if result["ok"] else st.error)(result["message"])
                else:
                    st.error(text)
        if col2.button("產生提示詞", key="gen_stock_prompt", width="stretch"):
            st.session_state["stock_prompt_code"] = code
            st.session_state["stock_prompt"] = build_stock_analysis_prompt(code)

        if st.session_state.get("stock_prompt_code") == code and st.session_state.get("stock_prompt"):
            st.caption("複製下面的內容（右上角有複製按鈕）貼到網頁版 AI，再把回覆貼回下方")
            st.code(st.session_state["stock_prompt"], language=None)

        with st.expander("手動貼上 AI 回覆"):
            raw_stock_analysis = st.text_area("AI 的分析結果", height=200, key="stock_analysis_input")
            if st.button("儲存個股分析", key="save_stock_analysis_btn"):
                result = save_stock_analysis(code, raw_stock_analysis)
                (st.success if result["ok"] else st.warning)(result["message"])

        stock_views = prediction_views.build_views(code)
        if stock_views:
            st.divider()
            st.caption("這檔的 AI 觀點與實際走勢（底色：紅＝偏多、綠＝偏空、灰＝中性）")
            _render_view_chart(code, stock_views)
            _views_table(stock_views, show_stock=False)

        existing_analysis = db.query_stock_analysis(_date.today().isoformat(), code)
        if existing_analysis:
            st.divider()
            st.caption(f"今天已儲存的分析・{existing_analysis[0]['created_at']}")
            st.markdown(_md_linebreaks(existing_analysis[0]["analysis"]))


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_chart_rows(code: str, days: int, today: str) -> list[dict]:
    """同一個週期切換期間不用重抓：一律抓該週期最長期間所需的歷史"""
    return charting.fetch_rows(code, days, _date.fromisoformat(today))


_KLINE_DEFAULTS = {"kline_period": "日K", "kline_indicators": []}


def _render_kline_panel(code: str, name: str):
    ui.restore_widgets(_KLINE_DEFAULTS | {f"kline_range_{p}": spec["default"] for p, spec in charting.PERIODS.items()})
    with ui.panel("K 線走勢", "均線・支撐壓力與成交量密集區・週 K／月 K 由日線合併・資料來源 FinMind"):
        col_period, col_range, col_ind = st.columns([1.1, 1.5, 1.6], vertical_alignment="bottom")
        period = col_period.segmented_control("週期", list(charting.PERIODS), key="kline_period") or "日K"
        spec = charting.PERIODS[period]
        range_label = col_range.segmented_control("期間", list(spec["ranges"]), key=f"kline_range_{period}")             or spec["default"]
        indicators = col_ind.pills("指標", charting.INDICATORS, selection_mode="multi", key="kline_indicators") or []
        ui.remember_widgets(["kline_period", "kline_indicators", f"kline_range_{period}"])
        longest = max(spec["ranges"], key=spec["ranges"].get)
        with st.spinner("讀取 K 線資料中..."):
            rows = _cached_chart_rows(code, charting.fetch_days(period, longest), _date.today().isoformat())
            fig = charting.build_candlestick(code, name, period, range_label, indicators, rows=rows)
        if fig:
            ma = "／".join(f"{n}{spec['unit']}" for n in spec["ma"])
            st.caption(f"均線 {ma}・虛線為支撐壓力、點線為成交量最密集價位、右側灰色長條為價量分布")
            st.plotly_chart(fig, width="stretch", key="kline_chart")
        else:
            st.warning("查無此股票的歷史價量資料（可能代號輸入錯誤，或 FinMind 目前沒有資料）")


def detail_page():
    selected_date = _render_sidebar()
    origin = st.session_state.get("detail_return")
    if origin in NAV_PAGES:
        if st.button(f"返回{NAV_PAGES[origin].title}", key="detail_back"):
            st.switch_page(NAV_PAGES[origin])
    ui.page_header("個股詳情", "K 線、籌碼、基本面、新聞與 AI 分析")

    col_input, _ = st.columns([1, 3])
    code = col_input.text_input("股票代號", value=st.session_state.get("selected_code", ""),
                                placeholder="輸入股票代號，例如 2330", label_visibility="collapsed")
    if not code:
        st.info("請輸入股票代號，或從左側新聞焦點、「選股工具 › 觀察名單」點選")
        return
    st.session_state["selected_code"] = code  # 切換分頁或頁面後回來仍停在這檔

    name = db.lookup_stock_name(code) or code
    _render_quote(code, name)
    _render_position_panel(code)

    tab, body = ui.page_tabs("detail", NAV_TABS["detail"])
    with body:
        if tab == "技術面":
            _render_kline_panel(code, name)
            _render_relative_strength_panel(code)
        elif tab == "籌碼面":
            _render_chip_panel(code)
            _render_shareholding_panel(code)
            _render_ownership_panel(code)
            _render_history_panel(code)
        elif tab == "基本面":
            _render_fundamentals_panel(code)
            _render_revenue_panel(code)
            _render_financials_panel(code)
            _render_pe_river_panel(code)
        elif tab == "新聞":
            with ui.panel("相關新聞", selected_date):
                news_rows = db.query_news(selected_date, code)
                if news_rows:
                    for row in news_rows:
                        ui.news_item(row["title"], row.get("url"), row.get("source") or "",
                                     ui.strip_html(row.get("summary") or ""))
                else:
                    st.caption("此日期尚無相關新聞（目前只有標題含代號的新聞會被標記關聯）")
        elif tab == "AI 分析":
            _render_stock_ai_panel(code)


# ─────────────────────────────── 我的持股 ───────────────────────────────

_POSITION_COLUMNS = {
    "code": "代號", "name": "名稱", "holding": "持有", "avg_cost": "平均成本", "close": "收盤",
    "price_date": "價格日期", "market_value": "市值", "pnl": "未實現損益", "pnl_pct": "報酬率%",
    "weight": "佔比%", "holding_days": "持有天數", "signals": "今日訊號",
}


def _render_position_panel(code: str):
    """個股詳情頁：有持有這檔才顯示"""
    p = next((pos for pos in portfolio.load_positions() if pos["code"] == code), None)
    if not p:
        return
    with ui.panel("我的持股", "成本含買進手續費；損益以本地最新收盤價計算，未扣將來賣出的稅費"):
        items = [
            {"label": "持有", "value": portfolio.lots_text(p["shares"]), "sub": f"{p['records']} 筆買進"},
            {"label": "平均成本", "value": f"{p['avg_cost']:,.2f}",
             "sub": f"從 {p['first_buy_date']} 開始持有" if p["first_buy_date"] else None},
        ]
        if p["pnl"] is not None:
            items += [
                {"label": "未實現損益", "value": f"{p['pnl']:+,.0f}", "tone": ui.tone_of(p["pnl"]),
                 "sub": f"市值 {p['market_value']:,.0f}"},
                {"label": "報酬率", "value": f"{p['pnl_pct']:+.2f}%", "tone": ui.tone_of(p["pnl_pct"]),
                 "sub": f"持有 {p['holding_days']} 天" if p["holding_days"] is not None else None},
            ]
        ui.cards(items)


def _trade_form_key(name: str) -> str:
    return f"trade_{name}_{st.session_state.get('trade_form_version', 0)}"


def _render_add_trade_form():
    settings = load_app_settings()
    discount = float(settings.get("fee_discount") or 1.0)

    c1, c2, c3, c4 = st.columns([1, 1.2, 1, 1])
    side_label = c1.segmented_control("買賣", ["買進", "賣出"], default="買進", key=_trade_form_key("side")) or "買進"
    side = "buy" if side_label == "買進" else "sell"
    code = c2.text_input("股票代號", placeholder="例如 2330", key=_trade_form_key("code")).strip()
    lots = c3.number_input("張數", min_value=0, value=1, step=1, key=_trade_form_key("lots"))
    odd = c4.number_input("零股（股）", min_value=0, max_value=999, value=0, step=100, key=_trade_form_key("odd"))

    c5, c6, c7, c8 = st.columns([1, 1.2, 1, 1])
    price = c5.number_input("成交價", min_value=0.0, value=None, step=0.5, format="%.2f", key=_trade_form_key("price"))
    trade_date = c6.date_input("成交日期", value=_date.today(), max_value=_date.today(), key=_trade_form_key("date"))
    shares = int(lots) * portfolio.SHARES_PER_LOT + int(odd)
    auto_fee = portfolio.estimate_fee(shares, price, discount) if price and shares else 0
    auto_tax = portfolio.estimate_tax(code, shares, price) if price and shares and side == "sell" and code else 0
    fee = c7.number_input("手續費", min_value=0, value=None, step=1, placeholder=f"自動 {auto_fee:,}",
                          key=_trade_form_key("fee"), help=f"留空＝依折扣 {discount:g} 自動試算")
    tax = c8.number_input("證交稅", min_value=0, value=None, step=1, placeholder=f"自動 {auto_tax:,}",
                          key=_trade_form_key("tax"), disabled=side == "buy", help="只有賣出要繳；留空＝自動試算")
    reason = st.text_area("進出場理由（交易日誌，AI 覆盤時會參考）", height=80, key=_trade_form_key("reason"),
                          placeholder="例如：站回月線、投信連買三天，停損設在前波低點")

    if st.button("新增交易", type="primary", key="trade_submit"):
        if not code or not shares or not price:
            st.warning("請填入股票代號、股數與成交價")
            return
        name = db.lookup_stock_name(code) or code
        new_trade = {"id": 10**9, "date": trade_date.isoformat(), "code": code, "name": name, "side": side,
                     "shares": shares, "price": float(price),
                     "fee": auto_fee if fee is None else fee, "tax": (auto_tax if tax is None else tax) if side == "sell" else 0}
        error = portfolio.validate(db.query_trades(code) + [new_trade])
        if error:
            st.error(error)
            return
        db.add_trade(new_trade["date"], code, name, side, shares, float(price), new_trade["fee"], new_trade["tax"], reason)
        st.session_state["trade_form_version"] = st.session_state.get("trade_form_version", 0) + 1
        st.session_state["trade_notice"] = f"已新增：{side_label} {code} {name} {portfolio.lots_text(shares)} @ {price:,.2f}"
        st.rerun()

    with st.expander("手續費設定"):
        new_discount = st.number_input("券商手續費折扣（例如 2.8 折填 0.28，沒有折扣填 1）", min_value=0.01, max_value=1.0,
                                       value=discount, step=0.01, format="%.2f", key="fee_discount_input")
        if new_discount != discount:
            save_app_settings({"fee_discount": new_discount})
            st.rerun()


_TRADE_SIDE_LABELS = {"buy": "買進", "sell": "賣出"}


def _render_trade_records():
    trades = db.query_trades()
    if not trades:
        st.caption("尚無交易紀錄")
        return
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["side"] = df["side"].map(_TRADE_SIDE_LABELS)
    df["delete"] = False
    df = df.iloc[::-1].reset_index(drop=True)  # 新的在上面
    edited = st.data_editor(
        df[["id", "date", "side", "code", "name", "shares", "price", "fee", "tax", "reason", "delete"]],
        hide_index=True, width="stretch", key=f"trade_editor_{st.session_state.get('trade_form_version', 0)}",
        disabled=["id", "code", "name"],
        column_config={
            "id": None,
            "date": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "side": st.column_config.SelectboxColumn("買賣", options=list(_TRADE_SIDE_LABELS.values()), required=True),
            "code": st.column_config.TextColumn("代號"),
            "name": st.column_config.TextColumn("名稱"),
            "shares": st.column_config.NumberColumn("股數", min_value=1, step=1, format="%d"),
            "price": st.column_config.NumberColumn("成交價", min_value=0.01, format="%.2f"),
            "fee": st.column_config.NumberColumn("手續費", min_value=0, format="%d"),
            "tax": st.column_config.NumberColumn("證交稅", min_value=0, format="%d"),
            "reason": st.column_config.TextColumn("理由", width="large"),
            "delete": st.column_config.CheckboxColumn("刪除"),
        },
    )
    if st.button("儲存變更", key="save_trades"):
        sides = {v: k for k, v in _TRADE_SIDE_LABELS.items()}
        original = {t["id"]: t for t in trades}
        kept, deleted, updated = [], [], []
        for row in edited.to_dict("records"):
            trade_id = int(row["id"])
            if row["delete"]:
                deleted.append(trade_id)
                continue
            new = {**original[trade_id], "date": row["date"].isoformat() if pd.notna(row["date"]) else original[trade_id]["date"],
                   "side": sides.get(row["side"], original[trade_id]["side"]), "shares": int(row["shares"]),
                   "price": float(row["price"]), "fee": float(row["fee"] or 0), "tax": float(row["tax"] or 0),
                   "reason": row["reason"] or ""}
            kept.append(new)
            if any(new[k] != original[trade_id][k] for k in ("date", "side", "shares", "price", "fee", "tax", "reason")):
                updated.append(new)
        error = portfolio.validate(kept)
        if error:
            st.error(f"無法儲存：{error}")
            return
        for trade_id in deleted:
            db.delete_trade(trade_id)
        for t in updated:
            db.update_trade(t["id"], date=t["date"], side=t["side"], shares=t["shares"], price=t["price"],
                            fee=t["fee"], tax=t["tax"], reason=t["reason"])
        if deleted or updated:
            st.session_state["trade_form_version"] = st.session_state.get("trade_form_version", 0) + 1
            st.session_state["trade_notice"] = f"已更新 {len(updated)} 筆、刪除 {len(deleted)} 筆"
            st.rerun()
        st.info("沒有變更")


_REALIZED_COLUMNS = {
    "date": "賣出日", "code": "代號", "name": "名稱", "shares_text": "股數", "avg_cost": "平均成本", "price": "賣出價",
    "pnl": "已實現損益", "return_pct": "報酬率%", "holding_days": "持有天數", "reviewed": "覆盤",
}


def _render_realized_panel():
    records = portfolio.realized_trades()
    with ui.panel("已實現損益與 AI 覆盤", "已扣手續費與證交稅；選一筆賣出，用 Codex 檢討這次的進出場"):
        if not records:
            st.caption("還沒有賣出紀錄")
            return
        this_year = [r for r in records if r["date"].startswith(str(_date.today().year))]
        wins = [r for r in records if r["pnl"] > 0]
        ui.cards([
            {"label": f"{_date.today().year} 已實現", "value": f"{sum(r['pnl'] for r in this_year):+,.0f}",
             "tone": ui.tone_of(sum(r["pnl"] for r in this_year)), "sub": f"{len(this_year)} 筆賣出"},
            {"label": "累計已實現", "value": f"{sum(r['pnl'] for r in records):+,.0f}",
             "tone": ui.tone_of(sum(r["pnl"] for r in records)), "sub": f"{len(records)} 筆賣出"},
            {"label": "獲利筆數比例", "value": f"{len(wins) / len(records) * 100:.0f}%"},
        ])
        reviews = db.query_trade_reviews()
        rows = [{**r, "shares_text": portfolio.lots_text(r["shares"]), "reviewed": "有" if r["id"] in reviews else ""}
                for r in records]
        view = pd.DataFrame(rows)[list(_REALIZED_COLUMNS)].rename(columns=_REALIZED_COLUMNS)
        st.dataframe(_styled_table(view, signed=["已實現損益", "報酬率%"], thousands=["已實現損益"],
                                   decimals=["平均成本", "賣出價", "報酬率%"]), width="stretch", hide_index=True)

        options = {r["id"]: f"{r['date']}　{r['code']} {r['name']}　{portfolio.lots_text(r['shares'])}　{r['pnl']:+,.0f}"
                   for r in records}
        col_pick, col_btn = st.columns([3, 1], vertical_alignment="bottom")
        chosen = col_pick.selectbox("選擇要覆盤的賣出交易", list(options), format_func=options.get, key="review_pick")
        if col_btn.button("用 Codex 覆盤", type="primary", width="stretch", key="review_run"):
            with st.spinner("Codex 正在覆盤..."):
                ok, text = generate_codex_text(portfolio.build_review_prompt(chosen))
            if ok:
                db.save_trade_review(chosen, text)
                reviews = db.query_trade_reviews()
            else:
                st.error(text)
        if chosen in reviews:
            st.caption(f"覆盤結果・{reviews[chosen]['created_at']}")
            st.markdown(_md_linebreaks(reviews[chosen]["review"]))
        with st.expander("覆盤提示詞（也可以複製到網頁版 AI）"):
            st.code(portfolio.build_review_prompt(chosen), language=None)


def _analyze_stocks_with_codex(stocks: list[dict], label: str):
    """逐檔用 Codex 做個股分析並儲存（持股、觀察名單共用），顯示進度與結果"""
    progress = st.progress(0.0, text="準備中...")

    def _update(done, total, message):
        progress.progress(done / total if total else 0.0, text=f"{message}（{done + 1}/{total}）")

    outcome = scheduled_ai.analyze_stocks(stocks, _date.today().isoformat(), progress=_update, skip_existing=False)
    progress.empty()
    if outcome["failed"]:
        st.error(f"完成 {len(outcome['done'])} 檔；部分分析失敗：\n"
                 + "\n".join(f"{code}：{message}" for code, message in outcome["failed"]))
    else:
        st.success(f"已完成 {len(outcome['done'])} 檔{label}分析，並收錄到每日報告")


def _render_saved_analyses(stocks: list[dict]):
    """列出這些股票今天已儲存的分析（可展開）"""
    today = _date.today().isoformat()
    for stock in stocks:
        saved = db.query_stock_analysis(today, stock["code"])
        if saved:
            with st.expander(f"{stock['code']} {stock['name']}・今天的分析（{saved[0]['created_at']}）"):
                st.markdown(_md_linebreaks(saved[0]["analysis"]))


def portfolio_page():
    _render_sidebar()
    ui.page_header("我的持股", "由交易紀錄以平均成本法計算；成本含買進手續費，未實現損益未扣將來賣出的稅費；資料只存在本機資料庫")

    notice = st.session_state.pop("trade_notice", None)
    if notice:
        st.success(notice)
    trade_error = portfolio.validate(db.query_trades())
    if trade_error:
        st.error(f"交易紀錄有誤，請到「交易紀錄」修正：{trade_error}")

    positions = portfolio.load_positions()
    totals = portfolio.portfolio_totals(positions) if positions else None
    if positions:
        ui.cards([
            {"label": "持股檔數", "value": f"{totals['positions']}"},
            {"label": "總成本", "value": f"{totals['cost']:,.0f}"},
            {"label": "總市值", "value": f"{totals['market_value']:,.0f}",
             "sub": f"{totals['unpriced']} 檔查無收盤價未計入" if totals["unpriced"] else None},
            {"label": "未實現損益", "value": f"{totals['pnl']:+,.0f}", "tone": ui.tone_of(totals["pnl"])},
            {"label": "報酬率", "value": "-" if totals["pnl_pct"] is None else f"{totals['pnl_pct']:+.2f}%",
             "tone": ui.tone_of(totals["pnl_pct"])},
        ])

    tab, body = ui.page_tabs("portfolio", NAV_TABS["portfolio"])
    with body:
        if tab in ("持倉明細", "持股訊號", "AI 持股分析") and not positions:
            st.info("目前沒有持有中的股票，請到「新增交易」記錄買進")
        elif tab == "持倉明細":
            _render_positions_table(positions, totals)
        elif tab == "持股訊號":
            with ui.panel("持股訊號", "僅上市股・區分今日新出現與持續中的訊號"):
                _render_signal_alerts(signals.watchlist_alerts(_cached_signal_history(), [p["code"] for p in positions]),
                                      "持股今天沒有觸發任何訊號")
        elif tab == "AI 持股分析":
            with ui.panel("AI 持股分析", "逐檔用 Codex 分析，提示詞附上你的成本與損益，列出續抱／減碼／停損的觀察條件"):
                if st.button("用 Codex 逐檔分析持股並儲存", type="primary"):
                    _analyze_stocks_with_codex(positions, "持股")
                _render_saved_analyses(positions)
        elif tab == "新增交易":
            with ui.panel("新增交易", "買進、賣出都記一筆；手續費與證交稅留空會自動試算"):
                _render_add_trade_form()
        elif tab == "交易紀錄":
            with ui.panel("交易紀錄", "可直接修改或勾選刪除；儲存前會檢查賣出股數有沒有超過當時持有"):
                _render_trade_records()
        elif tab == "已實現損益":
            _render_realized_panel()


def _render_positions_table(positions: list[dict], totals: dict):
    signal_df = _cached_signal_history()
    latest = signals.latest_rows(signal_df)
    active_by_code = {}
    if not latest.empty:
        held = latest[latest["code"].isin([p["code"] for p in positions])]
        active_by_code = {r["code"]: "、".join(signals.SIGNALS[k] for k in signals.active_signals(r))
                          for _, r in held.iterrows()}

    with ui.panel("持倉明細", "點一下任一列開啟個股詳情"):
        rows = [{
            **p,
            "holding": portfolio.lots_text(p["shares"]),
            "weight": p["market_value"] / totals["market_value"] * 100
            if p["market_value"] is not None and totals["market_value"] else None,
            "signals": active_by_code.get(p["code"], ""),
        } for p in positions]
        view = pd.DataFrame(rows)[list(_POSITION_COLUMNS)].rename(columns=_POSITION_COLUMNS)
        clicked = _clickable_table(
            _styled_table(view, signed=["未實現損益", "報酬率%"], thousands=["市值", "未實現損益", "持有天數"],
                          decimals=["平均成本", "收盤", "報酬率%", "佔比%"]),
            "position_table", width="stretch", hide_index=True,
            column_config={"今日訊號": st.column_config.TextColumn("今日訊號", width="large")},
        )
        if clicked is not None:
            _go_to_detail(positions[clicked]["code"])


# ─────────────────────────────── AI 預測追蹤 ───────────────────────────────

_VIEW_COLUMNS = {
    "code": "代號", "name": "名稱", "direction": "方向", "start_date": "開始日", "end_date": "結束日",
    "days": "持續(交易日)", "analyses": "分析次數", "start_close": "開始價", "end_close": "結束／最新價",
    "return_pct": "報酬%", "market_return": "同期大盤%", "excess": "超額%", "support": "支撐", "resistance": "壓力",
    "end_reason": "結束原因", "result_text": "結果",
}
_FLIP_COLUMNS = {"code": "代號", "name": "名稱", "analyses": "分析次數", "views": "觀點段數", "flips": "方向翻轉",
                 "flip_rate": "翻轉率%", "scored": "已計分", "hits": "命中"}
_VIEW_RULE = (f"同方向的連續預測合併成一段觀點，方向改變或滿 {prediction_views.VIEW_MAX_DAYS} 個交易日結算；"
              f"不到 {prediction_views.MIN_SCORED_DAYS} 天就翻轉的不計分・偏多須漲超過 {predictions.BULL_MIN_PCT:g}%、"
              f"偏空須跌超過 {abs(predictions.BEAR_MAX_PCT):g}%、中性須在 ±{predictions.NEUTRAL_BAND_PCT:g}% 內")


def _view_result_text(v: dict) -> str:
    if v["status"] == "done":
        return "命中" if v["hit"] else "未命中"
    if v["status"] == "active":
        return f"進行中 {v['days']}/{prediction_views.VIEW_MAX_DAYS} 天"
    return prediction_views.STATUS_LABELS[v["status"]]


def _views_table(views: list[dict], show_stock: bool = True, key: str | None = None, height: int | None = None):
    rows = [{**v, "result_text": _view_result_text(v)} for v in views]
    columns = [c for c in _VIEW_COLUMNS if show_stock or c not in ("code", "name")]
    view = pd.DataFrame(rows)[columns].rename(columns=_VIEW_COLUMNS)
    view["結束日"] = view["結束日"].fillna("")
    styler = _styled_table(view, signed=["報酬%", "同期大盤%", "超額%"],
                           decimals=["開始價", "結束／最新價", "報酬%", "同期大盤%", "超額%", "支撐", "壓力"])
    styler = styler.map(lambda v: f"color: {ui.UP_COLOR}" if v == "偏多" else f"color: {ui.DOWN_COLOR}" if v == "偏空" else "",
                        subset=["方向"])
    styler = styler.map(lambda v: "font-weight: 600" if v in ("命中", "未命中") else f"color: {ui.MUTED_COLOR}",
                        subset=["結果"])
    options = {"width": "stretch", "hide_index": True}
    if height:
        options["height"] = height
    if key is None:
        st.dataframe(styler, **options)
        return None
    return _clickable_table(styler, key, **options)


def _view_summary_cards(views: list[dict]):
    summary = prediction_views.summarize(views)
    directional = summary["directional"]
    neutral = summary["by_direction"].get("中性")
    items = [
        {"label": "觀點段數", "value": f"{summary['total']}", "sub": f"進行中 {summary['active']} 段"},
        {"label": "偏多＋偏空命中率",
         "value": "-" if not directional else f"{directional['hit_rate']:.0f}%",
         "sub": f"已結算 {directional['count'] if directional else 0} 段" + ("・樣本少參考性低" if not directional or directional["count"] < 20 else "")},
        {"label": "中性命中率（條件寬鬆，另計）",
         "value": "-" if not neutral else f"{neutral['hit_rate']:.0f}%",
         "sub": f"已結算 {neutral['count'] if neutral else 0} 段"},
        {"label": "方向翻轉", "value": f"{summary['flips']} 次", "sub": f"太短不計分 {summary['too_short']} 段"},
    ]
    for direction in ("偏多", "偏空"):
        stats = summary["by_direction"].get(direction)
        if stats:
            excess = stats["avg_excess"]
            items.append({"label": f"{direction}（{stats['count']} 段）", "value": f"平均 {stats['avg_return']:+.1f}%",
                          "tone": ui.tone_of(stats["avg_return"]),
                          "sub": "" if excess is None else f"超額 {excess:+.1f}%", "sub_tone": ui.tone_of(excess)})
    ui.cards(items)


_VIEW_BAND_COLORS = {"偏多": "rgba(240, 82, 79, 0.14)", "偏空": "rgba(34, 181, 115, 0.16)", "中性": "rgba(135, 146, 166, 0.14)"}


def _render_view_chart(code: str, views: list[dict]):
    """個股收盤價，底色標出每段觀點的方向（紅＝偏多、綠＝偏空、灰＝中性）"""
    if not views:
        return
    first = min(v["start_date"] for v in views)
    since = (_date.fromisoformat(first) - timedelta(days=14)).isoformat()
    prices = db.query_price_range(code, since)
    if len(prices) < 2:
        return
    frame = pd.DataFrame(prices)
    fig = go.Figure()
    for v in views:
        fig.add_vrect(x0=v["start_date"], x1=v["end_date"] or frame["date"].iloc[-1],
                      fillcolor=_VIEW_BAND_COLORS[v["direction"]], line_width=0, layer="below")
    fig.add_scatter(x=frame["date"], y=frame["close"], mode="lines", name="收盤價",
                    line={"color": ui.ACCENT_COLOR, "width": 2})
    starts = [v for v in views if v["start_date"] in set(frame["date"])]
    fig.add_scatter(x=[v["start_date"] for v in starts], y=[v["start_close"] for v in starts], mode="markers+text",
                    text=[v["direction"] for v in starts], textposition="middle left", name="觀點開始",
                    marker={"size": 8, "color": [ui.UP_COLOR if v["direction"] == "偏多" else ui.DOWN_COLOR
                                                 if v["direction"] == "偏空" else ui.MUTED_COLOR for v in starts]},
                    hovertemplate="%{x} 觀點開始：%{text}<extra></extra>")
    low, high = frame["close"].min(), frame["close"].max()
    fig.update_yaxes(range=[low - (high - low) * 0.08, high + (high - low) * 0.12])
    fig.update_xaxes(type="category", nticks=8)
    st.plotly_chart(ui.style_chart(fig, height=260), width="stretch", key=f"view_chart_{code}")


def _render_prediction_tracking():
    with ui.panel("AI 預測追蹤", _VIEW_RULE):
        views = prediction_views.build_views()
        if not views:
            st.caption("還沒有預測紀錄。之後用 Codex 做個股分析時，會自動記錄 AI 的預測摘要。")
            return
        _view_summary_cards(views)
    with ui.panel("目前觀點", "每檔股票最新的一段觀點；持續中的報酬算到最新收盤"):
        _views_table(prediction_views.current_views(views))
    with ui.panel("觀點紀錄", "全部觀點，新到舊"):
        _views_table(views, height=380)
    with ui.panel("各股翻轉統計", "翻轉率＝方向改變次數 ÷（分析次數 − 1）；常常翻來翻去的股票，AI 的看法參考價值較低"):
        stats = prediction_views.flip_stats(views)
        st.dataframe(_styled_table(pd.DataFrame(stats)[list(_FLIP_COLUMNS)].rename(columns=_FLIP_COLUMNS),
                                   decimals=["翻轉率%"]), width="stretch", hide_index=True)


# ─────────────────────────────── AI 分析 ───────────────────────────────


def _render_article_excerpts(selected_date: str):
    """顯示深度分析逐篇產生的新聞摘要：優先顯示這次剛跑完、還在記憶體裡的結果，
    沒有的話就從資料庫撈上一次分析存下來的紀錄（excerpt 欄位）。"""
    last_result = st.session_state.get("last_deep_result")
    if st.session_state.get("last_deep_result_date") == selected_date and last_result:
        excerpts = last_result.get("article_excerpts", [])
        source_label = "剛剛這次分析"
    else:
        rows = db.query_news_excerpts(selected_date)
        excerpts = [
            {"title": r["title"], "url": r["url"], "source": r["source"], "excerpt": r["excerpt"]}
            for r in rows
        ]
        source_label = "先前分析留下的紀錄"

    if not excerpts:
        return

    with ui.panel("逐篇新聞摘要", f"{source_label}・共 {len(excerpts)} 則"):
        with st.container(height=520, border=False):
            for item in excerpts:
                ui.news_item(item["title"], item.get("url"), item["source"], item["excerpt"])


def ai_analysis_page():
    ui.page_header("AI 分析", "使用已登入的 Codex CLI 摘要新聞、彙整焦點個股與大盤籌碼，結果直接收錄報告")

    today = _date.today().isoformat()
    available_dates = db.query_available_dates() or [today]
    col_date, _ = st.columns([1, 3])
    selected_date = col_date.selectbox("分析日期", available_dates)

    tab, body = ui.page_tabs("ai", NAV_TABS["ai"])
    with body:
        if tab == "新聞深度分析":
            with ui.panel("新聞深度分析", "先取得新聞內文，逐篇摘要後挑出有新聞依據的焦點個股；檔數越多，彙整時用的額度越多"):
                col_top, _ = st.columns([2, 3])
                with col_top:
                    _render_news_top_n("ai_news_top_n")
                if st.button("用 Codex 分析這天的新聞", type="primary"):
                    progress_bar = st.progress(0.0, text="準備中...")

                    def _update_progress(cur, total, msg):
                        progress_bar.progress(cur / total if total else 0.0, text=f"{msg} ({cur}/{total})")

                    result = analyze_with_codex_deep(selected_date, progress_callback=_update_progress)
                    progress_bar.empty()
                    st.session_state["last_deep_result_date"] = selected_date
                    st.session_state["last_deep_result"] = result
                    (st.success if result["ok"] else st.error)(result["message"])

            with ui.panel("分析結果", selected_date):
                summary = db.query_ai_analysis_summary(selected_date)
                if summary:
                    st.markdown(_md_linebreaks(summary["summary"]))
                    st.caption(f"分析來源 {summary['provider']}・產生時間 {summary['created_at']}")
                picks = db.query_ai_picks(selected_date)
                if picks:
                    st.dataframe(_display_df(picks, _PICK_COLUMNS), width="stretch", hide_index=True)
                elif not summary:
                    st.caption("尚無分析結果")

            _render_article_excerpts(selected_date)
        elif tab == "大盤籌碼分析":
            with ui.panel("大盤整體籌碼分析", "整合籌碼、短中期展望、熱門產業與個股消息，總計 1000 字內"):
                col1, col2, _ = st.columns([1.3, 1.1, 2])
                if col1.button("用 Codex 分析大盤並儲存", key="codex_market", type="primary", width="stretch"):
                    with st.spinner("Codex 正在分析大盤..."):
                        ok, text = build_market_analysis_prompt(selected_date)
                        if ok:
                            ok, text = generate_codex_text(text)
                            if ok:
                                result = save_market_analysis(text, selected_date)
                                (st.success if result["ok"] else st.error)(result["message"])
                        if not ok:
                            st.error(text)
                if col2.button("產生提示詞", key="gen_market_prompt", width="stretch"):
                    ok, prompt_or_msg = build_market_analysis_prompt(selected_date)
                    if ok:
                        st.session_state["market_prompt"] = prompt_or_msg
                    else:
                        st.warning(prompt_or_msg)

                market_prompt = st.session_state.get("market_prompt", "")
                if market_prompt:
                    st.caption("複製下面的內容貼到網頁版 AI，再把回覆貼回下方")
                    st.code(market_prompt, language=None)

                with st.expander("手動貼上 AI 回覆"):
                    raw_market_analysis = st.text_area("AI 的大盤分析結果", height=200, key="market_analysis_input")
                    if st.button("儲存大盤分析", key="save_market_analysis_btn"):
                        result = save_market_analysis(raw_market_analysis, selected_date)
                        (st.success if result["ok"] else st.warning)(result["message"])

                existing_market = db.query_market_analysis(selected_date)
                if existing_market:
                    st.divider()
                    st.caption(f"已儲存的大盤分析・{existing_market['created_at']}")
                    st.markdown(_md_linebreaks(existing_market["analysis"]))
        elif tab == "預測追蹤":
            _render_prediction_tracking()
        elif tab == "手動貼上":
            with ui.panel("手動複製貼上流程", "不使用 Codex 時：產生新聞分析提示詞，貼到網頁版 AI 後把回覆貼回來"):
                if st.button("產生新聞分析提示詞"):
                    ok, prompt_or_msg = build_prompt(selected_date)
                    if ok:
                        st.session_state["pending_ai_prompt"] = prompt_or_msg
                    else:
                        st.warning(prompt_or_msg)

                prompt = st.session_state.get("pending_ai_prompt", "")
                if prompt:
                    st.caption("複製下面的內容（右上角有複製按鈕），貼到 claude.ai／chatgpt.com／gemini.google.com")
                    st.code(prompt, language=None)

                raw_response = st.text_area("貼上 AI 回覆的完整內容", height=180, key="ai_raw_response")
                if st.button("解析並儲存"):
                    result = parse_and_save(selected_date, "manual_paste", raw_response)
                    (st.success if result["ok"] else st.error)(result["message"])


# ─────────────────────────────── AI 設定 ───────────────────────────────


def ai_settings_page():
    ui.page_header("AI 設定", "分析引擎與內文擷取服務")

    tab, body = ui.page_tabs("ai_settings", NAV_TABS["ai_settings"])
    with body:
        if tab == "Codex CLI":
            with ui.panel("Codex CLI", "使用這台電腦的 Codex 登入與帳號額度，不需在本程式填 API Key"):
                settings = load_codex_settings()
                col1, col2 = st.columns(2)
                executable = col1.text_input("Codex 執行檔（通常填 codex 即可）", value=settings["executable"])
                catalog = list_codex_models()
                models = {m["slug"]: m for m in catalog}
                options = [""] + list(models)
                current = settings.get("model", "")
                if current and current not in options:
                    options.append(current)
                labels = {"": "使用 CLI 預設模型"}
                labels.update({slug: entry.get("display_name", slug) for slug, entry in models.items()})
                model = col2.selectbox("分析模型", options, index=options.index(current),
                                       format_func=lambda value: labels.get(value, value))
                if model in models and models[model].get("description"):
                    col2.caption(models[model]["description"])
                if not catalog:
                    st.info("尚未取得模型清單，請先登入並開啟 Codex CLI，再重新整理本頁。")
                if st.checkbox("手動指定其他模型"):
                    model = st.text_input("模型代號", value=current)

                col3, _ = st.columns(2)
                timeout = col3.number_input("每次分析最長等待秒數", min_value=30, max_value=1800,
                                            value=int(settings["timeout_seconds"]))
                edited = {**settings, "executable": executable, "model": model, "timeout_seconds": int(timeout)}

                b1, b2, b3, _ = st.columns([1, 1, 1, 2])
                if b1.button("儲存設定", type="primary", width="stretch"):
                    update_codex_settings({k: edited[k] for k in ("executable", "model", "timeout_seconds")})
                    st.success("已儲存")
                if b2.button("測試所選模型", width="stretch"):
                    with st.spinner("測試模型中..."):
                        ok, message = generate_codex_text("請只回覆：連線成功", settings=edited)
                    (st.success if ok else st.error)(message)
                if b3.button("檢查登入", width="stretch"):
                    ok, message = check_codex_login(edited)
                    (st.success if ok else st.error)(message)
        elif tab == "每日排程":
            with ui.panel("每日排程", "自動收集的時間，以及收集完要用 Codex 做哪些分析"):
                _render_schedule_setup()
        elif tab == "Firecrawl":
            with ui.panel("Firecrawl 內文擷取", "選用・免費額度每月 1000 次，沒設定 Key 會自動改用本機 Playwright"):
                scraping_settings = load_scraping_settings()
                firecrawl_key = st.text_input(
                    "Firecrawl API Key（到 https://www.firecrawl.dev/ 申請）",
                    value=scraping_settings.get("firecrawl_api_key", ""),
                    type="password",
                    placeholder="留空則不使用，改用 Playwright",
                )
                b1, b2, _ = st.columns([1, 1, 3])
                if b1.button("儲存設定", key="save_firecrawl", width="stretch"):
                    save_scraping_settings({"firecrawl_api_key": firecrawl_key})
                    st.success("已儲存")
                if b2.button("測試連線", key="test_firecrawl", width="stretch"):
                    ok, message = firecrawl_test_connection(firecrawl_key)
                    (st.success if ok else st.error)(message)


# ─────────────────────────────── 選股工具 ───────────────────────────────


@st.cache_data(ttl=600, show_spinner="計算全市場訊號中...")
def _cached_signal_history(as_of: str | None = None) -> pd.DataFrame:
    """全市場訊號計算約需數秒，快取 10 分鐘；收集完新資料後最多 10 分鐘就會反映"""
    return signals.load_signal_history(as_of=as_of)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_screen_tables() -> dict[str, pd.DataFrame]:
    """選股篩選要合併的各種最新資料（基本面、營收訊號、大戶、外資持股、季報、本益比百分位），快取 10 分鐘"""
    return {
        "fundamentals": fundamentals.latest_fundamentals(),
        "revenue": revenue.latest_signals()[["code", "revenue_high_12m", "yoy_growth_streak"]],
        "shareholding": shareholding.latest_table()[["code", "big1000_pct", "big1000_pct_change"]],
        "ownership": ownership.latest_table(),
        "financials": financials.latest_table(),
        "pe_percentile": pe_river.latest_percentiles(),
        "industry": pd.DataFrame(list(db.query_industry_map().items()), columns=["code", "industry"]),
        "issued": pd.DataFrame(db.query_issued_shares(_date.today().isoformat()), columns=["code", "issued_shares"]),
    }


@st.cache_data(ttl=600, show_spinner="計算回測資料中...")
def _cached_backtest_frame() -> pd.DataFrame:
    """回測用盡量長的歷史（本地資料庫有多少用多少）"""
    return backtest.add_forward_returns(signals.load_signal_history(lookback_days=3650))


_BACKTEST_COLUMNS = {
    "label": "訊號", "events": "樣本數", "mean": "平均報酬%", "median": "中位數%", "win_rate": "勝率%",
    "p25": "P25%", "p75": "P75%", "baseline_mean": "同期大盤平均%", "excess_mean": "平均超額報酬%",
}


def _render_backtest_tab():
    with ui.panel("回測設定", "隔天開盤買進、第 N 個交易日收盤賣出；只計新出現的訊號"):
        frame = _cached_backtest_frame()
        if frame.empty:
            st.warning("本地資料庫沒有足夠的上市歷史資料")
            return
        col1, col2, col3 = st.columns([1.2, 1, 1.6])
        horizon = col1.segmented_control("持有天數", backtest.DEFAULT_HORIZONS, default=backtest.DEFAULT_HORIZONS[0],
                                         format_func=lambda n: f"{n} 個交易日") or backtest.DEFAULT_HORIZONS[0]
        min_lots = col2.number_input("20日均量至少（張）", min_value=0, value=500, step=100, key="bt_min_lots")
        start, end = backtest.sample_period(frame, horizon)
        col3.caption("樣本期間")
        col3.markdown(f"訊號日 {start} ～ {end}")
        st.caption("未扣手續費與交易稅、未處理漲停買不到；樣本期間短時結論容易受單一行情影響，僅供檢驗訊號參考。")

    with ui.panel("各訊號統計", f"樣本數少於 {backtest.MIN_EVENTS_FOR_STATS} 筆參考性很低・超額報酬 = 訊號股報酬 − 同一天全市場平均"):
        table = backtest.backtest_all(frame, horizon, min_avg_volume_lots=min_lots)
        view = table[list(_BACKTEST_COLUMNS)].rename(columns=_BACKTEST_COLUMNS)
        pct_cols = ["平均報酬%", "中位數%", "P25%", "P75%", "同期大盤平均%", "平均超額報酬%"]
        st.dataframe(
            _styled_table(view, signed=pct_cols, thousands=["樣本數"], decimals=pct_cols + ["勝率%"]),
            width="stretch", hide_index=True,
            column_config={"勝率%": st.column_config.ProgressColumn("勝率%", min_value=0, max_value=100, format="%.1f")},
        )

    with ui.panel("報酬分布"):
        labels = {v: k for k, v in signals.SIGNALS.items()}
        col_select, _ = st.columns([1, 2])
        chosen = col_select.selectbox("訊號", list(labels), label_visibility="collapsed")
        stats = backtest.backtest_signal(frame, labels[chosen], horizon, min_avg_volume_lots=min_lots)
        if stats["events"]:
            fig = px.histogram(pd.DataFrame({"報酬%": stats["returns"]}), x="報酬%", nbins=50,
                               color_discrete_sequence=[ui.ACCENT_COLOR])
            fig.add_vline(x=0, line_dash="dash", line_color="#5A6477")
            fig.add_vline(x=stats["baseline_mean"], line_color="#F5B942", annotation_text="同期大盤平均",
                          annotation_font_color="#F5B942")
            fig.update_layout(bargap=0.05, yaxis_title="次數")
            st.plotly_chart(ui.style_chart(fig, height=360), width="stretch")
        else:
            st.caption("這個訊號在樣本期間沒有出現")


_TREND_DAYS = 90  # 迷你走勢圖涵蓋的日曆天（約 60 個交易日）
_TREND_COLUMN = "60日走勢"


def _trend_config() -> dict:
    return {_TREND_COLUMN: st.column_config.LineChartColumn(_TREND_COLUMN, width="small",
                                                            help="近約 60 個交易日的收盤價走勢")}


def _trend_series(codes: list[str]) -> dict[str, list[float]]:
    since = (_date.today() - timedelta(days=_TREND_DAYS)).isoformat()
    return db.query_close_series(list(codes), since)


_SCREEN_COLUMNS = {
    "code": "代號", "name": "名稱", "industry": "產業", "trend": _TREND_COLUMN, "close": "收盤", "change_pct": "漲跌%",
    "return_20d": "20日報酬%", "rs_rank_pct": "相對強弱",
    "foreign_streak": "外資連買賣", "trust_streak": "投信連買賣",
    "vol_ma20_lots": "20日均量(張)", "turnover_rate": "週轉率%", "pe_ratio": "本益比", "dividend_yield": "殖利率%",
    "pb_ratio": "淨值比", "yoy_pct": "營收年增%", "revenue_high_text": "營收創高", "yoy_growth_streak": "年增連續月",
    "big1000_pct": "千張大戶%", "big1000_pct_change": "大戶週增(百分點)", "foreign_pct": "外資持股%",
    "foreign_change_20": "外資20日增(百分點)", "roe_annualized": "ROE年化%", "gross_margin": "毛利率%",
    "eps_ttm": "近四季EPS", "pe_percentile": "本益比百分位",
    "signals": "觸發訊號",
}


def _add_selected_to_watchlist(table_key: str, stocks: list[tuple[str, str]]):
    """「加入觀察名單」按鈕的回呼。

    用回呼而不是 `if st.button(): ... st.rerun()`：回呼只會在按下時執行一次；
    後者在 st.rerun() 重跑時按鈕仍是按下狀態，會再加一次。
    加完換一個新的表格 key 讓勾選真的歸零——直接刪 session_state 裡的選取狀態，
    瀏覽器上的勾勾還會留著，畫面和程式認知的選取會不同步。"""
    rows = (st.session_state.get(table_key) or {}).get("selection", {}).get("rows", [])
    chosen = [stocks[i] for i in rows if i < len(stocks)]
    if not chosen:
        return
    group = st.session_state.get("screen_watch_group")
    added, existing = add_stocks(chosen, group)
    message = f"已加入 {len(added)} 檔到「{group}」" if added else f"勾選的股票都已經在「{group}」裡"
    if added and existing:
        message += f"（{len(existing)} 檔原本就在名單裡）"
    st.session_state["screen_notice"] = message
    st.session_state["screen_table_version"] = st.session_state.get("screen_table_version", 0) + 1
    st.session_state["screen_checked_codes"] = []


# 篩選條件的 widget key 與預設值；換頁時 Streamlit 會清掉沒畫出來的 widget 狀態，
# 靠 ui.restore_widgets／remember_widgets 保存，從個股詳情返回時條件還在
_SCREEN_DEFAULTS = {
    "scr_signals": [signals.SIGNALS["breakout_20d"]], "scr_mode": "全部符合", "scr_min_lots": 500,
    "scr_pe_max": None, "scr_yield_min": None, "scr_pb_max": None, "scr_yoy_min": None,
    "scr_roe_min": None, "scr_gross_min": None, "scr_eps_ttm_min": None, "scr_pe_pct_max": None,
    "scr_revenue_high": False, "scr_yoy_streak": 0,
    "scr_big_min": None, "scr_big_change_min": None, "scr_foreign_change_min": None,
    "scr_price_min": None, "scr_price_max": None, "scr_turnover_min": None, "scr_industries": [],
}


def _apply_screen_preset():
    """套用範本：回呼在重跑前執行，可以直接改條件 widget 的值"""
    values = config_screener.load_presets().get(st.session_state.get("scr_preset"), {})
    store = st.session_state.setdefault(ui._KEPT_WIDGETS, {})
    for key, default in _SCREEN_DEFAULTS.items():
        value = values.get(key, default)
        st.session_state[key] = value
        store[key] = value
    st.session_state["screen_preset_notice"] = f"已套用「{st.session_state.get('scr_preset')}」"


def _save_screen_preset():
    name = st.session_state.get("scr_preset_name", "")
    values = {key: st.session_state.get(key, default) for key, default in _SCREEN_DEFAULTS.items()}
    try:
        saved = config_screener.save_preset(name, values)
    except config_screener.PresetError as exc:
        st.session_state["screen_preset_notice"] = str(exc)
        return
    st.session_state["scr_preset_pending"] = saved
    st.session_state["scr_preset_name"] = ""
    st.session_state["screen_preset_notice"] = f"已存成範本「{saved}」"


def _delete_screen_preset():
    name = st.session_state.get("scr_preset")
    config_screener.delete_preset(name)
    st.session_state["screen_preset_notice"] = f"已刪除範本「{name}」"


def _render_screen_presets():
    presets = config_screener.load_presets()
    pending = st.session_state.pop("scr_preset_pending", None)
    if pending in presets:
        st.session_state["scr_preset"] = pending
    col_pick, col_apply, col_delete, col_save = st.columns([2.2, 0.8, 0.8, 1.2], vertical_alignment="bottom")
    col_pick.selectbox("條件範本", list(presets) or ["（還沒有範本）"], key="scr_preset", disabled=not presets)
    col_apply.button("套用", width="stretch", disabled=not presets, key="scr_preset_apply", on_click=_apply_screen_preset)
    col_delete.button("刪除", width="stretch", disabled=not presets, key="scr_preset_delete", on_click=_delete_screen_preset)
    with col_save.popover("存成範本", width="stretch"):
        st.text_input("範本名稱", placeholder="例如：高殖利率＋外資買", key="scr_preset_name",
                      help="把目前所有篩選條件存起來；同名會覆蓋")
        st.button("儲存", type="primary", width="stretch", key="scr_preset_save", on_click=_save_screen_preset)
    notice = st.session_state.pop("screen_preset_notice", None)
    if notice:
        st.caption(notice)


def _render_screen_tab(signal_df: pd.DataFrame):
    ui.restore_widgets(_SCREEN_DEFAULTS)
    with ui.panel("篩選條件", "常用的條件組合可以存成範本，下次一鍵套用"):
        _render_screen_presets()
        labels = {v: k for k, v in signals.SIGNALS.items()}
        chosen = st.multiselect("訊號條件", list(labels), key="scr_signals")
        col1, col2, _ = st.columns([1, 1, 2])
        mode = col1.segmented_control("條件組合", ["全部符合", "符合任一"], key="scr_mode") or "全部符合"
        min_lots = col2.number_input("20日均量至少（張）", min_value=0, step=100, key="scr_min_lots")
        with st.expander("基本面條件（留空＝不限制；設了條件時缺資料的股票會被排除）"):
            f1, f2, f3, f4 = st.columns(4)
            pe_max = f1.number_input("本益比 ≤", min_value=0.0, value=None, step=1.0, key="scr_pe_max")
            yield_min = f2.number_input("殖利率% ≥", min_value=0.0, value=None, step=0.5, key="scr_yield_min")
            pb_max = f3.number_input("淨值比 ≤", min_value=0.0, value=None, step=0.5, key="scr_pb_max")
            yoy_min = f4.number_input("營收年增% ≥", value=None, step=5.0, key="scr_yoy_min")
        with st.expander("獲利條件（季度財報）"):
            q1, q2, q3, q4 = st.columns([1, 1, 1, 1])
            roe_min = q1.number_input("ROE（年化）% ≥", value=None, step=5.0, key="scr_roe_min")
            gross_min = q2.number_input("單季毛利率% ≥", value=None, step=5.0, key="scr_gross_min")
            eps_ttm_min = q3.number_input("近四季 EPS ≥（元）", value=None, step=1.0, key="scr_eps_ttm_min")
            pe_pct_max = q4.number_input("本益比歷史百分位 ≤", min_value=0.0, max_value=100.0, value=None, step=10.0,
                                         key="scr_pe_pct_max",
                                         help="目前本益比在自己近兩年（或已收集期間）的位置，0＝最便宜；只有上市股")
        with st.expander("營收條件（月營收，需累積歷史資料）"):
            r1, r2, _ = st.columns([1, 1, 2], vertical_alignment="bottom")
            revenue_high_only = r1.checkbox("營收創 12 個月新高", key="scr_revenue_high")
            yoy_streak_min = r2.number_input("年增率連續成長 ≥（月）", min_value=0, step=1, key="scr_yoy_streak")
        with st.expander("籌碼集中條件（集保股權分散，每週資料）"):
            s1, s2, s3, _ = st.columns([1, 1, 1, 1])
            big_min = s1.number_input("千張大戶持股% ≥", min_value=0.0, max_value=100.0, value=None, step=5.0,
                                      key="scr_big_min")
            big_change_min = s2.number_input("大戶週增 ≥（百分點）", value=None, step=0.1, format="%.2f",
                                             key="scr_big_change_min")
            foreign_change_min = s3.number_input("外資持股 20 日增 ≥（百分點）", value=None, step=0.5, format="%.2f",
                                                 key="scr_foreign_change_min")
        with st.expander("價格、產業與週轉率"):
            p1, p2, p3 = st.columns([1, 1, 1])
            price_min = p1.number_input("股價 ≥（元）", min_value=0.0, value=None, step=10.0, key="scr_price_min")
            price_max = p2.number_input("股價 ≤（元）", min_value=0.0, value=None, step=10.0, key="scr_price_max")
            turnover_min = p3.number_input("週轉率% ≥", min_value=0.0, value=None, step=0.5, key="scr_turnover_min",
                                           help="當天成交股數 ÷ 發行股數；數字越高代表換手越熱絡")
            industry_options = sorted(set(_cached_screen_tables()["industry"]["industry"]))
            industries = st.multiselect("產業（不選＝全部）", industry_options, key="scr_industries")
    ui.remember_widgets(_SCREEN_DEFAULTS)

    result = signals.screen(signal_df, [labels[c] for c in chosen], min_avg_volume_lots=min_lots,
                            mode="all" if mode == "全部符合" else "any")
    tables = _cached_screen_tables()
    result = fundamentals.attach_fundamentals(result, tables["fundamentals"])
    result = fundamentals.apply_filters(result, pe_max=pe_max, yield_min=yield_min, pb_max=pb_max, yoy_min=yoy_min)
    if not result.empty:
        result = result.merge(tables["revenue"], on="code", how="left")
        if revenue_high_only:
            result = result[result["revenue_high_12m"] == True]  # noqa: E712 - 欄位含 None，不能用 truthy 判斷
        if yoy_streak_min:
            result = result[result["yoy_growth_streak"].fillna(0) >= yoy_streak_min]
        result["revenue_high_text"] = result["revenue_high_12m"].map({True: "是", False: ""}).fillna("")
        result = result.merge(tables["shareholding"], on="code", how="left")
        result = result.merge(tables["ownership"], on="code", how="left")
        result = result.merge(tables["financials"], on="code", how="left")
        for column, minimum in (("roe_annualized", roe_min), ("gross_margin", gross_min), ("eps_ttm", eps_ttm_min)):
            if minimum is not None:
                result = result[result[column].notna() & (result[column] >= minimum)]
        result = result.merge(tables["pe_percentile"], on="code", how="left")
        if pe_pct_max is not None:
            result = result[result["pe_percentile"].notna() & (result["pe_percentile"] <= pe_pct_max)]
        if foreign_change_min is not None:
            result = result[result["foreign_change_20"].notna() & (result["foreign_change_20"] >= foreign_change_min)]
        if big_min is not None:
            result = result[result["big1000_pct"].notna() & (result["big1000_pct"] >= big_min)]
        if big_change_min is not None:
            result = result[result["big1000_pct_change"].notna() & (result["big1000_pct_change"] >= big_change_min)]
        result = result.merge(tables["industry"], on="code", how="left").merge(tables["issued"], on="code", how="left")
        result["turnover_rate"] = result["volume"] / result["issued_shares"].where(result["issued_shares"] > 0) * 100
        if price_min is not None:
            result = result[result["close"] >= price_min]
        if price_max is not None:
            result = result[result["close"] <= price_max]
        if turnover_min is not None:
            result = result[result["turnover_rate"].notna() & (result["turnover_rate"] >= turnover_min)]
        if industries:
            result = result[result["industry"].isin(industries)]
        result = result.reset_index(drop=True)

    _render_screen_results(result)


@st.fragment
def _render_screen_results(result: pd.DataFrame):
    """篩選結果表格。用 fragment：勾選或點擊只重跑這一塊，不會整頁重算篩選條件
    （以前每點一下整頁重跑 1～2 秒，期間表格變灰、接著的勾選會被吃掉）"""
    result = result.copy()
    with ui.panel("篩選結果", f"符合 {len(result)} 檔・依相對強弱排序・勾選左邊方框可加入觀察名單・點一下股票開啟個股詳情"):
        notice = st.session_state.pop("screen_notice", None)
        if notice:
            st.success(notice)
        if result.empty:
            st.caption("沒有符合條件的股票")
            return
        actions = st.container()
        result["vol_ma20_lots"] = (result["vol_ma20"] / 1000).round(0)
        series = _trend_series(result["code"])
        result["trend"] = [series.get(code, []) for code in result["code"]]
        view = result[list(_SCREEN_COLUMNS)].rename(columns=_SCREEN_COLUMNS)
        styler = _styled_table(
            view, signed=["漲跌%", "20日報酬%", "外資連買賣", "投信連買賣", "營收年增%", "大戶週增(百分點)", "外資20日增(百分點)"],
            thousands=["20日均量(張)", "外資連買賣", "投信連買賣", "年增連續月"],
            decimals=["收盤", "漲跌%", "20日報酬%", "週轉率%", "本益比", "殖利率%", "淨值比", "營收年增%", "千張大戶%",
                      "大戶週增(百分點)", "外資持股%", "外資20日增(百分點)", "ROE年化%", "毛利率%", "近四季EPS", "本益比百分位"],
        )
        stocks = list(zip(result["code"], result["name"]))
        codes = list(result["code"])
        # 篩選結果換了就換一個表格（勾選依代號還原），避免勾選的「第幾列」對到別檔股票
        table_key = f"screen_table_{st.session_state.get('screen_table_version', 0)}_{hash(tuple(codes)) & 0xFFFFFFFF:x}"
        checked_codes = st.session_state.get("screen_checked_codes", [])
        rows, clicked = _checkable_table(
            styler, table_key, selected_rows=[codes.index(c) for c in checked_codes if c in codes],
            width="stretch", hide_index=True, height=560,
            column_config={
                "相對強弱": st.column_config.ProgressColumn("相對強弱", min_value=0, max_value=100, format="%.0f",
                                                        help="同一天全市場 20 日報酬的百分位排名"),
                "觸發訊號": st.column_config.TextColumn("觸發訊號", width="large"),
                **_trend_config(),
            },
        )
        st.session_state["screen_checked_codes"] = [codes[i] for i in rows if i < len(codes)]
        if clicked is not None and clicked < len(codes):
            _go_to_detail(codes[clicked])
        # 按鈕放在表格上方（actions 容器），不用捲到表格底部才按得到
        selected = result.iloc[[i for i in rows if i < len(codes)]]
        with actions:
            col_info, col_group, col_add, col_detail = st.columns([2.2, 1.3, 1.2, 1.2], vertical_alignment="bottom")
            col_info.caption(f"已勾選 {len(selected)} 檔：" + "、".join(selected["name"].head(8))
                             + ("…" if len(selected) > 8 else "") if len(selected) else "勾選股票後可加入觀察名單")
            with col_group:
                _watch_group_selector("screen_watch_group", "加入到")
            col_add.button("加入觀察名單", type="primary", width="stretch", disabled=selected.empty,
                           key="screen_add_watchlist", on_click=_add_selected_to_watchlist,
                           args=(table_key, stocks))
            if col_detail.button("開啟個股詳情", width="stretch", disabled=len(selected) != 1,
                                 key="screen_open_detail", help="勾選一檔時可用"):
                _go_to_detail(selected.iloc[0]["code"])


def _render_signal_alerts(alerts: list[dict], empty_text: str):
    if not alerts:
        st.caption(empty_text)
        return
    for index, alert in enumerate(alerts):
        if index:
            st.divider()
        change = alert["change_pct"]
        ui.quote_header(alert["code"], alert["name"], alert["close"],
                        None if change is None else alert["close"] - alert["close"] / (1 + change / 100),
                        change, alert["date"])
        tone = lambda k: "down" if k in signals.BEARISH_SIGNALS else "up"  # noqa: E731
        if alert["new"]:
            st.caption("今日新訊號")
            ui.chips([(signals.SIGNALS[k], tone(k)) for k in alert["new"]])
        if alert["continuing"]:
            st.caption("持續中")
            ui.chips([(signals.SIGNALS[k], "") for k in alert["continuing"]])


_WATCH_COLUMNS = {"code": "代號", "name": "名稱", "trend": _TREND_COLUMN, "date": "價格日期", "close": "收盤", "change_pct": "漲跌%",
                  "new": "今日新訊號", "continuing": "持續中訊號"}


def _watch_group_selector(key: str, label: str = "觀察名單") -> str:
    groups = list(config_watchlist.load_groups())
    ui.restore_widgets({key: None})  # 換頁回來仍停在上次選的名單
    # 建立／改名／刪除名單後要切換選取，但 selectbox 畫出來之後不能再改它的值，所以先記在 _pending，下次畫之前套用
    pending = st.session_state.pop(f"{key}_pending", None)
    if pending in groups:
        st.session_state[key] = pending
    if st.session_state.get(key) not in groups:
        st.session_state[key] = groups[0]
    chosen = st.selectbox(label, groups, key=key)
    ui.remember_widgets([key])
    return chosen


def _set_watch_group(name: str | None):
    st.session_state["watch_group_pending"] = name


def _remove_selected_from_group(table_key: str, group: str, codes: list[str]):
    rows = (st.session_state.get(table_key) or {}).get("selection", {}).get("rows", [])
    chosen = [codes[i] for i in rows if i < len(codes)]
    for code in chosen:
        config_watchlist.remove_stock(code, group)
    if chosen:
        st.session_state["watch_notice"] = f"已從「{group}」移除 {len(chosen)} 檔"
        st.session_state["watch_table_version"] = st.session_state.get("watch_table_version", 0) + 1


def _render_watch_group_manager(group: str):
    with st.popover("管理名單", width="stretch"):
        with st.form("watch_new_group", clear_on_submit=True, border=False):
            new_name = st.text_input("新增名單", placeholder="例如：半導體、高殖利率")
            if st.form_submit_button("建立", width="stretch") and new_name.strip():
                try:
                    _set_watch_group(config_watchlist.create_group(new_name))
                    st.rerun()
                except config_watchlist.WatchlistError as exc:
                    st.error(str(exc))
        st.divider()
        with st.form("watch_rename_group", border=False):
            renamed = st.text_input(f"重新命名「{group}」", value=group)
            if st.form_submit_button("改名", width="stretch") and renamed.strip() != group:
                try:
                    _set_watch_group(config_watchlist.rename_group(group, renamed))
                    st.rerun()
                except config_watchlist.WatchlistError as exc:
                    st.error(str(exc))
        st.divider()
        if st.button(f"刪除「{group}」", width="stretch", key="watch_delete_group"):
            try:
                config_watchlist.delete_group(group)
                _set_watch_group(next(iter(config_watchlist.load_groups())))
                st.rerun()
            except config_watchlist.WatchlistError as exc:
                st.error(str(exc))


def _render_watchlist_tab(signal_df: pd.DataFrame):
    col_group, col_manage, col_add, _ = st.columns([1.4, 0.8, 1.6, 1.2], vertical_alignment="bottom")
    with col_group:
        group = _watch_group_selector("watch_group")
    with col_manage:
        _render_watch_group_manager(group)
    with col_add, st.form("watch_add_stock", clear_on_submit=True, border=False):
        c_input, c_btn = st.columns([2, 1], vertical_alignment="bottom")
        new_code = c_input.text_input("加入股票", placeholder="輸入代號，例如 2330")
        if c_btn.form_submit_button("加入", width="stretch") and new_code.strip():
            code = new_code.strip()
            name = db.lookup_stock_name(code)
            if name:
                config_watchlist.add_stock(code, name, group)
                st.session_state["watch_notice"] = f"已加入 {code} {name}"
                st.rerun()
            else:
                st.warning(f"本地資料庫查不到 {code}，請確認代號")

    stocks = config_watchlist.load_groups().get(group, {})
    alerts_by_code = {a["code"]: a for a in signals.watchlist_alerts(signal_df, stocks.keys())}
    with ui.panel(group, f"共 {len(stocks)} 檔・勾選左邊方框可移除・點一下股票開啟個股詳情"):
        notice = st.session_state.pop("watch_notice", None)
        if notice:
            st.success(notice)
        if not stocks:
            st.caption("這個名單還沒有股票。可以在上方輸入代號，或在「篩選器」勾選後加入。")
            return
        rows = []
        series = _trend_series(list(stocks))
        for code, name in stocks.items():
            quote = db.query_latest_close(code) or {}
            close, change = quote.get("close"), quote.get("change")
            alert = alerts_by_code.get(code, {})
            rows.append({
                "code": code, "name": name, "trend": series.get(code, []), "date": quote.get("date"), "close": close,
                "change_pct": change / (close - change) * 100 if close is not None and change is not None and close - change else None,
                "new": "、".join(signals.SIGNALS[k] for k in alert.get("new", [])),
                "continuing": "、".join(signals.SIGNALS[k] for k in alert.get("continuing", [])),
            })
        view = pd.DataFrame(rows)[list(_WATCH_COLUMNS)].rename(columns=_WATCH_COLUMNS)
        actions = st.container()
        table_key = f"watch_table_{group}_{st.session_state.get('watch_table_version', 0)}"
        codes = list(stocks)
        rows_checked, clicked = _checkable_table(
            _styled_table(view, signed=["漲跌%"], decimals=["收盤", "漲跌%"]), table_key,
            width="stretch", hide_index=True,
            column_config={"今日新訊號": st.column_config.TextColumn("今日新訊號", width="medium"),
                           "持續中訊號": st.column_config.TextColumn("持續中訊號", width="large"),
                           **_trend_config()},
        )
        if clicked is not None and clicked < len(codes):
            _go_to_detail(codes[clicked])
        selected = [codes[i] for i in rows_checked if i < len(codes)]
        # AI 分析：有勾選就只分析勾選的，沒勾就分析整個名單
        ai_targets = [{"code": c, "name": stocks[c]} for c in (selected or codes)]
        ai_label = f"AI 分析勾選的 {len(selected)} 檔" if selected else f"AI 分析全部 {len(codes)} 檔"
        with actions:
            col_info, col_remove, col_detail, col_ai = st.columns([2.4, 1.1, 1.1, 1.3], vertical_alignment="center")
            col_info.caption(f"已勾選 {len(selected)} 檔" if selected else "訊號只計算上市股（上櫃資料源無法回補歷史）")
            col_remove.button("從名單移除", width="stretch", disabled=not selected, key="watch_remove",
                              on_click=_remove_selected_from_group, args=(table_key, group, codes))
            if col_detail.button("開啟個股詳情", width="stretch", disabled=len(selected) != 1, key="watch_open_detail",
                                 help="勾選一檔時可用"):
                _go_to_detail(selected[0])
            run_ai = col_ai.button(ai_label, type="primary", width="stretch", key="watch_ai_run",
                                   help="用 Codex 逐檔分析並儲存（每檔各用一次額度），結果收錄每日報告；沒勾選就分析整個名單")
        if run_ai:
            _analyze_stocks_with_codex(ai_targets, "觀察名單")

    today_analysed = [{"code": c, "name": n} for c, n in stocks.items()
                      if db.query_stock_analysis(_date.today().isoformat(), c)]
    if today_analysed:
        with ui.panel("今天的 AI 分析", f"「{group}」今天已分析 {len(today_analysed)} 檔，點開看全文"):
            _render_saved_analyses(today_analysed)

    with ui.panel("名單訊號", "僅上市股・區分今日新出現與持續中的訊號"):
        _render_signal_alerts(list(alerts_by_code.values()), "這個名單今天沒有觸發任何訊號")



def screener_page():
    _render_sidebar()
    signal_df = _cached_signal_history()
    if signal_df.empty:
        ui.page_header("選股工具")
        st.warning("本地資料庫沒有上市歷史資料，請先執行收集或 scripts/backfill_history.py 補歷史")
        return
    trading_days = signal_df["date"].nunique()
    note = "（未滿 60 天，60 日相關訊號暫時不會觸發）" if trading_days < 61 else ""
    ui.page_header("選股工具", f"資料截至 {signal_df['date'].max()}・{trading_days} 個交易日・"
                             f"僅上市股・訊號為程式計算的篩選條件，不構成投資建議{note}")

    tab, body = ui.page_tabs("screener", NAV_TABS["screener"])
    with body:
        if tab == "篩選器":
            _render_screen_tab(signal_df)
        elif tab == "觀察名單":
            _render_watchlist_tab(signal_df)
        elif tab == "訊號回測":
            _render_backtest_tab()


# ─────────────────────────────── 條件提醒 ───────────────────────────────

_ANY_SIGNAL = "任何新訊號"


def _rule_exists(kind: str, code: str | None = None, threshold: float | None = None, signal_key: str | None = None) -> bool:
    return any(r["kind"] == kind and (r["code"] or None) == (code or None) and r["threshold"] == threshold
               and (r["signal_key"] or None) == (signal_key or None) for r in db.query_alert_rules())


def _render_add_alert_rule():
    with ui.panel("新增提醒"):
        labels = {v: k for k, v in alerts.KINDS.items()}
        col_kind, col_target, col_value = st.columns([1.3, 1.2, 1.2], vertical_alignment="bottom")
        kind = labels[col_kind.selectbox("提醒條件", list(labels), key="alert_kind")]
        code, threshold, signal_key = None, None, None
        if kind in alerts.PRICE_KINDS:
            code = col_target.text_input("股票代號", placeholder="例如 2330", key="alert_code").strip() or None
        elif kind in alerts.HOLDING_KINDS:
            code = col_target.text_input("股票代號（留空＝所有持股）", key="alert_holding_code").strip() or None
        if kind in ("price_above", "price_below"):
            threshold = col_value.number_input("價格", min_value=0.0, value=None, step=1.0, format="%.2f", key="alert_price")
        elif kind != "watchlist_signal":
            threshold = col_value.number_input("幅度（%）", min_value=0.1, value=5.0 if kind in alerts.PRICE_KINDS else 8.0,
                                               step=0.5, key="alert_pct")
        else:
            options = [_ANY_SIGNAL] + list(signals.SIGNALS.values())
            chosen = col_target.selectbox("訊號", options, key="alert_signal")
            signal_key = None if chosen == _ANY_SIGNAL else {v: k for k, v in signals.SIGNALS.items()}[chosen]

        if st.button("新增提醒", type="primary", key="alert_add"):
            if kind in alerts.PRICE_KINDS and not code:
                st.warning("請輸入股票代號")
            elif kind != "watchlist_signal" and not threshold:
                st.warning("請輸入門檻")
            elif _rule_exists(kind, code, threshold, signal_key):
                st.info("已經有一樣的提醒了")
            else:
                name = db.lookup_stock_name(code) if code else None
                db.add_alert_rule(kind, code, name, threshold, signal_key)
                st.success("已新增提醒")
                st.rerun()


def _render_quick_alert_setup():
    with ui.panel("快速設定"):
        col1, col2, col3 = st.columns([1, 1.6, 2], vertical_alignment="bottom")
        loss = col1.number_input("停損幅度（%）", min_value=1.0, value=8.0, step=1.0, key="quick_loss")
        if col2.button(f"所有持股虧損超過 {loss:g}% 時提醒", width="stretch", key="quick_loss_btn"):
            if _rule_exists("holding_loss", None, loss):
                st.info("已經有一樣的提醒了")
            else:
                db.add_alert_rule("holding_loss", threshold=loss)
                st.success("已新增")
                st.rerun()
        if col3.button("觀察名單出現任何新訊號時提醒", width="stretch", key="quick_signal_btn"):
            if _rule_exists("watchlist_signal"):
                st.info("已經有一樣的提醒了")
            else:
                db.add_alert_rule("watchlist_signal")
                st.success("已新增")
                st.rerun()


def _render_alert_rules():
    with ui.panel("提醒規則"):
        rules = db.query_alert_rules()
        if not rules:
            st.caption("還沒有提醒規則")
            return
        for rule in rules:
            col_desc, col_toggle, col_delete = st.columns([6, 1, 1], vertical_alignment="center")
            col_desc.markdown(alerts.describe_rule(rule))
            enabled = col_toggle.toggle("啟用", value=bool(rule["enabled"]), key=f"alert_enabled_{rule['id']}")
            if enabled != bool(rule["enabled"]):
                db.set_alert_rule_enabled(rule["id"], enabled)
            if col_delete.button("刪除", key=f"alert_delete_{rule['id']}", type="tertiary"):
                db.delete_alert_rule(rule["id"])
                st.rerun()


def alerts_page():
    _render_sidebar()
    ui.page_header("條件提醒", "每日收集完自動檢查，符合條件時跳出 Windows 通知；同一檔同一天只提醒一次")

    tab, body = ui.page_tabs("alerts", NAV_TABS["alerts"])
    with body:
        if tab == "最近觸發":
            with ui.panel("最近觸發"):
                col_check, col_test, _ = st.columns([1, 1, 3])
                if col_check.button("立即檢查", width="stretch", key="alert_check_now"):
                    with st.spinner("檢查中..."):
                        outcome = alerts.check_alerts()
                    st.info(outcome["message"])
                if col_test.button("送出測試通知", width="stretch", key="alert_test_toast"):
                    ok, message = notify.show_toast("台股分析 測試通知", ["看到這則通知，代表提醒功能可以正常跳出"])
                    (st.success if ok else st.error)(message)
                events = db.query_alert_events()
                if events:
                    view = pd.DataFrame(events)[["date", "code", "name", "message"]].rename(
                        columns={"date": "日期", "code": "代號", "name": "名稱", "message": "內容"})
                    st.dataframe(view, width="stretch", hide_index=True,
                                 column_config={"內容": st.column_config.TextColumn("內容", width="large")})
                else:
                    st.caption("還沒有觸發紀錄")
        elif tab == "提醒規則":
            _render_alert_rules()
        elif tab == "新增提醒":
            _render_add_alert_rule()
            _render_quick_alert_setup()


# ─────────────────────────────── 行事曆 ───────────────────────────────

_EVENT_COLUMNS = {"date": "日期", "weekday": "星期", "title": "事件", "stock": "股票", "detail": "說明", "tag": "相關"}
_WEEKDAYS = "一二三四五六日"


def _event_table(events: pd.DataFrame):
    rows = events.assign(
        weekday=events["date"].map(lambda d: _WEEKDAYS[_date.fromisoformat(d).weekday()]),
        stock=(events["code"] + " " + events["name"]).str.strip(),
        tag=[("持股" if h else "") + ("、" if h and w else "") + ("觀察" if w else "")
             for h, w in zip(events["in_holdings"], events["in_watchlist"])],
    )
    view = rows[list(_EVENT_COLUMNS)].rename(columns=_EVENT_COLUMNS)
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={"說明": st.column_config.TextColumn("說明", width="large")})


def calendar_page():
    _render_sidebar()
    ui.page_header("行事曆", "除權息、月營收公布期限與 AI 預測檢驗日；持股與觀察名單相關的事件排在最前面")

    col_range, _ = st.columns([1, 3])
    days = col_range.segmented_control("期間", [7, 30, 60], default=30, format_func=lambda d: f"{d} 天",
                                       key="calendar_days") or 30
    events = calendar_events.upcoming_events(_date.today(), days)
    if events.empty:
        st.info("這段期間沒有事件。除權息預告在每日收集時更新。")
        return

    mine = events[events["in_holdings"] | events["in_watchlist"]]
    others = events[~(events["in_holdings"] | events["in_watchlist"]) & (events["kind"] != calendar_events.KIND_DIVIDEND)]
    market = events[~(events["in_holdings"] | events["in_watchlist"]) & (events["kind"] == calendar_events.KIND_DIVIDEND)]

    tab, body = ui.page_tabs("calendar", NAV_TABS["calendar"])
    with body:
        if tab == "持股與觀察名單":
            with ui.panel("我的持股與觀察名單", "除權息預估股利未扣二代健保補充保費與匯費"):
                if mine.empty:
                    st.caption("這段期間持股與觀察名單沒有相關事件")
                else:
                    _event_table(mine)
        elif tab == "其他提醒":
            with ui.panel("其他提醒", "月營收公布期限、AI 預測檢驗日"):
                if others.empty:
                    st.caption("沒有其他提醒")
                else:
                    _event_table(others)
        elif tab == "全市場除權息":
            with ui.panel("全市場除權息", f"共 {len(market)} 檔"):
                if market.empty:
                    st.caption("沒有其他除權息")
                else:
                    _event_table(market)


# ─────────────────────────────── 每日報告 ───────────────────────────────


def _format_net(value) -> str:
    return f"{value:+,}" if value is not None else "-"


def _build_report_text(date: str, include_holdings: bool = False) -> str:
    """include_holdings=False 時不放「我的持股」段落，並移除個股分析裡的「持股應對」一項"""
    lines = [f"# 台股每日報告 - {date}", ""]

    lines.append("## 新聞摘要")
    ai_summary = db.query_ai_analysis_summary(date)
    if ai_summary:
        lines.append(_md_linebreaks(ai_summary["summary"]))
        lines.append(f"\n*分析來源: {ai_summary['provider']}｜產生時間: {ai_summary['created_at']}*")
    else:
        lines.append("_（此日期尚無新聞分析摘要，請到「AI 分析」頁產生）_")
    lines.append("")

    lines.append("## 大盤整體籌碼分析")
    market_analysis = db.query_market_analysis(date)
    if market_analysis:
        lines.append(_md_linebreaks(market_analysis["analysis"]))
        lines.append(f"\n*儲存時間: {market_analysis['created_at']}*")
    else:
        lines.append("_（此日期尚無大盤分析，請到「AI 分析」頁產生）_")
    lines.append("")

    lines.append("## 今日新聞焦點個股（含三大法人買賣超）")
    picks = db.query_ai_picks(date)
    if picks:
        lines.append("| 排名 | 代號 | 名稱 | 關注原因 | 外資買賣超(股) | 投信買賣超(股) | 自營商買賣超(股) |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in picks:
            inst = db.query_institutional_for_code(date, p["code"])
            foreign = _format_net(inst["foreign_net"]) if inst else "-"
            trust = _format_net(inst["trust_net"]) if inst else "-"
            dealer = _format_net(inst["dealer_net"]) if inst else "-"
            lines.append(
                f"| {p['rank']} | {p['code']} | {p['name']} | {p['reason']} | {foreign} | {trust} | {dealer} |"
            )
    else:
        lines.append("_（此日期尚無 AI 分析結果，請到「AI 分析」頁產生）_")
    lines.append("")

    lines.append("## 觀察名單技術／籌碼訊號")
    signal_df = _cached_signal_history(as_of=date)
    if signal_df.empty:
        lines.append("_（本地資料庫尚無上市歷史資料）_")
    else:
        alerts = signals.watchlist_alerts(signal_df, load_watchlist().keys())
        lines.append(f"*訊號資料日期: {signal_df['date'].max()}（僅上市股，由程式計算）*\n")
        lines.append(signals.format_alerts_markdown(alerts))
    lines.append("")

    positions = portfolio.load_positions(as_of=date) if include_holdings else []
    if positions:
        totals = portfolio.portfolio_totals(positions)
        lines.append("## 我的持股")
        lines.append(f"*以 {date} 以前最新收盤價計算，未扣手續費與證交稅*\n")
        pct = f"（{totals['pnl_pct']:+.2f}%）" if totals["pnl_pct"] is not None else ""
        lines.append(f"總成本 {totals['cost']:,.0f}｜總市值 {totals['market_value']:,.0f}｜"
                     f"未實現損益 {totals['pnl']:+,.0f}{pct}\n")
        lines.append("| 代號 | 名稱 | 持有 | 平均成本 | 收盤 | 未實現損益 | 報酬率 |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in positions:
            close = "-" if p["close"] is None else f"{p['close']:,.2f}"
            pnl = "-" if p["pnl"] is None else f"{p['pnl']:+,.0f}"
            pnl_pct = "-" if p["pnl_pct"] is None else f"{p['pnl_pct']:+.2f}%"
            lines.append(f"| {p['code']} | {p['name']} | {portfolio.lots_text(p['shares'])} | "
                         f"{p['avg_cost']:,.2f} | {close} | {pnl} | {pnl_pct} |")
        if not signal_df.empty:
            lines.append("\n**持股訊號**\n")
            lines.append(signals.format_alerts_markdown(
                signals.watchlist_alerts(signal_df, [p["code"] for p in positions])))
        lines.append("")

    lines.append("## 未來 7 天事件")
    lines.append(calendar_events.report_markdown(_date.fromisoformat(date) + timedelta(days=1), 7,
                                                 include_holdings=include_holdings))
    lines.append("")

    lines.append("## 個股深度分析")
    stock_analyses = db.query_stock_analysis(date)
    if stock_analyses:
        for sa in stock_analyses:
            lines.append(f"### {sa['code']} {sa['name']}")
            analysis = sa["analysis"] if include_holdings else strip_holding_section(sa["analysis"])
            lines.append(_md_linebreaks(analysis))
            lines.append(f"\n*儲存時間: {sa['created_at']}*")
            lines.append("")
    else:
        lines.append("_（此日期尚無個股深度分析，可到「個股詳情」頁為關注的股票產生分析）_")

    return "\n".join(lines)


def report_page():
    ui.page_header("每日報告", "彙整新聞摘要、大盤分析、焦點個股、觀察名單訊號與個股分析，可下載 Markdown 或 PDF")

    today = _date.today().isoformat()
    available_dates = db.query_available_dates() or [today]
    report_text = None

    report_settings = load_report_settings()
    include_holdings = st.toggle(
        "報告包含我的持股", value=report_settings["include_holdings"],
        help="關閉時，畫面、Markdown 與 PDF 都不會有「我的持股」段落，個股分析裡的「持股應對」也會一併移除",
    )
    if include_holdings != report_settings["include_holdings"]:
        save_report_settings({**report_settings, "include_holdings": include_holdings})
        st.session_state.pop("report_pdf_bytes", None)  # 設定改了，舊的 PDF 內容不再對應

    col_date, col_md, col_pdf, col_pdf_dl = st.columns([1.2, 1, 1, 1], vertical_alignment="bottom")
    selected_date = col_date.selectbox("報告日期", available_dates, key="report_date")
    report_text = _build_report_text(selected_date, include_holdings)
    col_md.download_button("下載 Markdown", report_text, file_name=f"twstock_report_{selected_date}.md",
                           mime="text/markdown", width="stretch")
    if col_pdf.button("產生 PDF", width="stretch"):
        with st.spinner("產生 PDF 中..."):
            st.session_state["report_pdf_bytes"] = markdown_to_pdf(report_text)
            st.session_state["report_pdf_date"] = selected_date
            st.session_state["report_pdf_holdings"] = include_holdings
    if (st.session_state.get("report_pdf_date") == selected_date and st.session_state.get("report_pdf_bytes")
            and st.session_state.get("report_pdf_holdings") == include_holdings):
        col_pdf_dl.download_button("下載 PDF", st.session_state["report_pdf_bytes"],
                                   file_name=f"twstock_report_{selected_date}.pdf", mime="application/pdf", width="stretch")

    # key 會變成 CSS class（st-key-tw_report），ui.py 用它把報告裡的 Markdown 標題壓回統一字級
    with st.container(border=True, key="tw_report"):
        st.markdown(report_text)


# ─────────────────────────────── 歷史查詢 ───────────────────────────────

_HISTORY_NEWS_COLUMNS = {"date": "日期", "source": "來源", "title": "標題", "related_code": "關聯代號"}
_HISTORY_PICK_COLUMNS = {"code": "代號", "name": "名稱", "count": "上榜次數", "best_rank": "最佳排名",
                         "first_date": "第一次", "last_date": "最近一次", "last_reason": "最近原因"}
_HISTORY_ANALYSIS_COLUMNS = {"date": "日期", "code": "代號", "name": "名稱", "created_at": "產生時間"}
_VIEW_STATUS = {"全部": None, **{label: key for key, label in prediction_views.STATUS_LABELS.items()}}


def _row_at(rows: list, index: int | None):
    return rows[index] if index is not None and index < len(rows) else None


@st.dialog("新聞", width="large", on_dismiss=partial(_clear_table_click, "history_news_table"))
def _news_dialog(row: dict):
    ui.section(row["title"], f"{row['date']}・{row['source']}" + (f"・關聯 {row['related_code']}" if row.get("related_code") else ""))
    if row.get("excerpt"):
        ui.section("AI 逐篇摘要")
        st.markdown(_md_linebreaks(row["excerpt"]))
    if row.get("summary"):
        ui.section("原始摘要")
        st.markdown(ui.strip_html(row["summary"]))
    if not row.get("excerpt") and not row.get("summary"):
        st.caption("這則新聞沒有摘要")
    if row.get("url"):
        st.link_button("開啟原文", row["url"], type="primary")


@st.dialog("個股分析", width="large", on_dismiss=partial(_clear_table_click, "history_stock_table"))
def _stock_analysis_dialog(row: dict):
    ui.section(f"{row['code']} {row['name']}", f"{row['date']} 的分析・產生時間 {row['created_at']}")
    st.markdown(_md_linebreaks(row["analysis"]))


@st.dialog("AI 觀點", width="large", on_dismiss=partial(_clear_table_click, "history_pred_table"))
def _view_dialog(row: dict):
    dates = row["analysis_dates"]
    period = f"{row['start_date']} 起・{_view_result_text(row)}"
    ui.section(f"{row['code']} {row['name']}・{row['direction']}", f"{period}・包含 {len(dates)} 次分析")
    chosen = st.selectbox("分析日", list(reversed(dates)), key="history_view_dialog_date") if len(dates) > 1 else dates[0]
    text = history.analysis_text(chosen, row["code"])
    if text:
        st.markdown(_md_linebreaks(text))
    else:
        st.caption("找不到這天的分析原文")


def _limit_note(rows: list[dict]) -> str:
    return f"・只顯示最新 {db.HISTORY_LIMIT} 筆，請縮小期間或加上關鍵字" if len(rows) >= db.HISTORY_LIMIT else ""


def _render_history_news(start: str, end: str, keyword: str):
    col_source, _ = st.columns([1, 3])
    sources = ["全部來源", *db.query_news_sources()]
    source = col_source.selectbox("來源", sources, key="history_news_source")
    rows = db.search_news(start, end, keyword, None if source == "全部來源" else source)
    with ui.panel("新聞", f"共 {len(rows)} 則{_limit_note(rows)}・點一下任一則看摘要與原文連結"):
        if not rows:
            st.caption("這段期間沒有符合的新聞")
            return
        view = pd.DataFrame(rows)[list(_HISTORY_NEWS_COLUMNS)].fillna("").rename(columns=_HISTORY_NEWS_COLUMNS)
        clicked = _clickable_table(view, "history_news_table", width="stretch", hide_index=True, height=420,
                                   column_config={"標題": st.column_config.TextColumn("標題", width="large")})
    row = _row_at(rows, clicked)
    if row:
        _news_dialog(row)


def _render_history_picks(start: str, end: str, keyword: str):
    picks = db.search_ai_picks(start, end, keyword)
    frequency = history.pick_frequency(picks)
    with ui.panel("上榜次數統計", f"期間內 {frequency.shape[0]} 檔・{len({p['date'] for p in picks})} 天{_limit_note(picks)}・點一下任一檔開啟個股詳情"):
        if frequency.empty:
            st.caption("這段期間沒有新聞焦點紀錄")
            return
        view = frequency.rename(columns=_HISTORY_PICK_COLUMNS)
        clicked = _clickable_table(view, "history_pick_freq", width="stretch", hide_index=True, height=360,
                                   column_config={"最近原因": st.column_config.TextColumn("最近原因", width="large")})
        if clicked is not None and clicked < len(frequency):
            _go_to_detail(frequency.iloc[clicked]["code"])

    summaries = {row["date"]: row for row in db.search_ai_summaries(start, end)}
    by_date: dict[str, list[dict]] = {}
    for pick in picks:
        by_date.setdefault(pick["date"], []).append(pick)
    with ui.panel("每日新聞焦點", "每天的新聞總結與焦點個股"):
        # 有關鍵字時只列出有符合個股的日子；沒有關鍵字時，只有總結沒有個股的日子也列出來
        dates = set(by_date) if keyword else set(by_date) | set(summaries)
        for index, date in enumerate(sorted(dates, reverse=True)):
            day_picks = by_date.get(date, [])
            with st.expander(f"{date}・{len(day_picks)} 檔", expanded=index == 0):
                summary = summaries.get(date)
                if summary and not keyword:
                    st.markdown(_md_linebreaks(summary["summary"]))
                if day_picks:
                    st.dataframe(_display_df(day_picks, _PICK_COLUMNS), width="stretch", hide_index=True,
                                 column_config={"原因": st.column_config.TextColumn("原因", width="large")})


def _render_history_stock_analysis(start: str, end: str, keyword: str):
    rows = db.search_stock_analysis(start, end, keyword)
    with ui.panel("個股分析紀錄", f"共 {len(rows)} 篇{_limit_note(rows)}・點一下任一篇看全文；關鍵字也會搜尋分析內文"):
        if not rows:
            st.caption("這段期間沒有符合的個股分析")
            return
        view = pd.DataFrame(rows)[list(_HISTORY_ANALYSIS_COLUMNS)].rename(columns=_HISTORY_ANALYSIS_COLUMNS)
        clicked = _clickable_table(view, "history_stock_table", width="stretch", hide_index=True, height=320)
    row = _row_at(rows, clicked)
    if row:
        _stock_analysis_dialog(row)


def _render_history_market_analysis(start: str, end: str, keyword: str):
    rows = db.search_market_analysis(start, end, keyword)
    with ui.panel("大盤分析紀錄", f"共 {len(rows)} 篇{_limit_note(rows)}"):
        if not rows:
            st.caption("這段期間沒有符合的大盤分析")
            return
        for index, row in enumerate(rows):
            with st.expander(f"{row['date']}・產生時間 {row['created_at']}", expanded=index == 0):
                st.markdown(_md_linebreaks(row["analysis"]))


def _render_history_predictions(start: str, end: str, keyword: str):
    col_direction, col_status, _ = st.columns([1, 1, 2])
    direction = col_direction.selectbox("方向", ["全部", *predictions.DIRECTIONS], key="history_pred_direction")
    status = col_status.selectbox("狀態", list(_VIEW_STATUS), key="history_pred_status")
    views = history.search_views(start, end, keyword, None if direction == "全部" else direction, _VIEW_STATUS[status])
    with ui.panel("AI 觀點紀錄", f"共 {len(views)} 段（依開始日）・{_VIEW_RULE}・點一下任一段看當時的分析"):
        if not views:
            st.caption("這段期間沒有符合的觀點")
            return
        _view_summary_cards(views)
        clicked = _views_table(views, key="history_pred_table", height=380)
    row = _row_at(views, clicked)
    if row:
        _view_dialog(row)


def history_page():
    ui.page_header("歷史查詢", "查詢過去的新聞、新聞焦點、個股與大盤分析，以及 AI 預測的檢驗結果")
    first, last = db.query_history_date_bounds()
    if not first:
        st.info("還沒有任何新聞或 AI 分析紀錄")
        return
    first_date, last_date = _date.fromisoformat(first), max(_date.fromisoformat(last), _date.today())
    default_start = max(first_date, last_date - timedelta(days=30))
    col_range, col_keyword = st.columns([1.2, 2], vertical_alignment="bottom")
    picked = col_range.date_input("期間", value=(default_start, last_date), min_value=first_date, max_value=last_date,
                                  key="history_range", format="YYYY-MM-DD")
    keyword = col_keyword.text_input("關鍵字", placeholder="股票代號、名稱或內文關鍵字，留空＝全部",
                                     key="history_keyword").strip()
    if not isinstance(picked, (tuple, list)) or len(picked) != 2:
        st.caption("請選擇起訖兩個日期")
        return
    start, end = (d.isoformat() for d in picked)

    tab, body = ui.page_tabs("history", NAV_TABS["history"])
    with body:
        if tab == "新聞":
            _render_history_news(start, end, keyword)
        elif tab == "新聞焦點":
            _render_history_picks(start, end, keyword)
        elif tab == "個股分析":
            _render_history_stock_analysis(start, end, keyword)
        elif tab == "大盤分析":
            _render_history_market_analysis(start, end, keyword)
        elif tab == "AI 預測":
            _render_history_predictions(start, end, keyword)


# ─────────────────────────────── 開始使用 ───────────────────────────────

_DISCLAIMER = """本工具整理證交所、櫃買中心與新聞等公開資料，並用 AI 產生分析文字，**僅供資訊整理與研究參考，不構成任何投資建議**。

- 資料可能延遲、缺漏或有誤，AI 分析也可能出錯，請自行查證
- 回測結果是過去的統計，不代表未來績效
- 投資有賺有賠，所有買賣決定與盈虧請自行負責"""

_CODEX_INSTALL_URL = "https://github.com/openai/codex"


def _history_trading_days() -> int:
    since = (_date.today() - timedelta(days=desktop.BACKFILL_DAYS)).isoformat()
    return sum(1 for d in db.query_dates_with_data("stock_price", "TWSE") if d >= since)


def _onboarding_needed() -> bool:
    done = load_app_settings()["onboarding_done"]
    if done is None:
        # 升級上來的既有使用者（資料庫已經有歷史）不強迫再走一次引導
        return _history_trading_days() < 20
    return not done


@st.fragment(run_every=15)
def _render_backfill_progress():
    status = desktop.backfill_status()
    have = _history_trading_days()
    target = desktop.expected_trading_days()
    st.progress(min(have / target, 1.0), text=f"已有 {have} 個交易日的資料（目標約 {target} 天，扣掉國定假日會略少）")
    if status["running"]:
        st.caption("下載中，每 15 秒自動更新進度。可以先去使用其他頁面，關掉瀏覽器也會繼續下載。")
    elif have >= target * 0.9:
        st.caption("歷史資料已足夠。之後每天收集時會自動補上缺漏的日子。")


def _render_codex_setup():
    executable = find_codex_executable(load_codex_settings())
    if not executable:
        st.markdown(
            f"尚未偵測到 Codex。請依照 [Codex 官方說明]({_CODEX_INSTALL_URL}) 安裝 Windows 版，"
            "安裝完成後回到這裡按「重新檢查」。"
        )
        if st.button("重新檢查", key="codex_recheck_install"):
            st.rerun()
        return
    ok, message = check_codex_login()
    if ok:
        st.success("Codex 已登入，可以使用 AI 分析")
        return
    st.warning("已安裝 Codex，但還沒登入")
    col1, col2, _ = st.columns([1, 1, 3])
    if col1.button("登入 Codex", type="primary", width="stretch"):
        ok, message = desktop.open_codex_login(executable)
        (st.info if ok else st.error)(message)
    if col2.button("重新檢查", key="codex_recheck_login", width="stretch"):
        st.rerun()


_SCHEDULE_TIMES = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]


def _render_news_top_n(key: str):
    """新聞焦點要挑出前幾檔（存 codex_settings.json，手動分析與排程共用）"""
    current = news_top_n()
    chosen = st.segmented_control("新聞焦點檔數", NEWS_TOP_N_OPTIONS, default=current, key=key,
                                  format_func=lambda n: f"前 {n} 檔")
    if chosen and chosen != current:
        update_codex_settings({"news_top_n": chosen})


def _render_schedule_setup():
    if "daily_task_status" not in st.session_state:
        st.session_state["daily_task_status"] = desktop.daily_task_status()
    status = st.session_state["daily_task_status"]
    app_settings = load_app_settings()
    current_time = status["time"] or app_settings["daily_task_time"]
    times = _SCHEDULE_TIMES if current_time in _SCHEDULE_TIMES else sorted([*_SCHEDULE_TIMES, current_time])

    col_time, col_toggle = st.columns([1, 2.4], vertical_alignment="bottom")
    chosen_time = col_time.selectbox("執行時間", times, index=times.index(current_time), key="schedule_time",
                                     help="建議傍晚以後：三大法人、融資融券等盤後資料大約下午 4 點後才會公布齊全")
    enabled = col_toggle.toggle(f"每天 {chosen_time} 自動收集資料並執行分析", value=status["exists"], key="schedule_enabled")
    if chosen_time != app_settings["daily_task_time"]:
        save_app_settings({"daily_task_time": chosen_time})
    if enabled and (not status["exists"] or status["time"] != chosen_time):
        ok, message = desktop.register_daily_task(chosen_time)
        (st.success if ok else st.error)(message)
        st.session_state["daily_task_status"] = desktop.daily_task_status()
    elif not enabled and status["exists"]:
        ok, message = desktop.unregister_daily_task()
        (st.success if ok else st.error)(message)
        st.session_state["daily_task_status"] = desktop.daily_task_status()
    st.caption("需要電腦開著並連上網路；如果那個時間電腦沒開，下次開機後會自動補做。")

    st.divider()
    ui.section("收集完之後的 AI 分析", "都會使用 Codex 帳號額度；個股分析每檔各呼叫一次，檔數多時建議只開需要的項目，同一天已分析過的個股不會重複分析")
    settings = load_codex_settings()
    changes = {}
    col_news, col_top = st.columns([1.2, 1], vertical_alignment="bottom")
    news = col_news.checkbox("分析當日新聞並挑出焦點個股", value=settings["auto_analyze_after_collect"], key="schedule_news",
                             help="側邊欄「立即收集今日資料」也會依這個設定決定要不要分析新聞")
    with col_top:
        _render_news_top_n("schedule_news_top_n")
    holdings_count = len(portfolio.load_positions())
    holdings = st.checkbox(f"分析所有持股（目前 {holdings_count} 檔）", value=settings["auto_analyze_holdings"],
                           key="schedule_holdings")
    watch_codes = set(load_watchlist())
    watch = st.checkbox(f"分析所有觀察名單（目前 {len(watch_codes)} 檔，與持股重複的只分析一次）",
                        value=settings["auto_analyze_watchlist"], key="schedule_watchlist")
    for field, value in (("auto_analyze_after_collect", news), ("auto_analyze_holdings", holdings),
                         ("auto_analyze_watchlist", watch)):
        if value != settings[field]:
            changes[field] = value
    if changes:
        settings = update_codex_settings(changes)
    count = len(scheduled_ai.stock_targets(settings))
    if count:
        st.caption(f"每天會做 {count} 檔個股分析（{count} 次 Codex 呼叫）")


def onboarding_page():
    ui.page_header("開始使用", "第一次使用請依序完成以下設定，之後隨時可以回到這一頁調整")
    settings = load_app_settings()

    with ui.panel("1. 使用前請先閱讀"):
        st.markdown(_DISCLAIMER)
        accepted = st.checkbox("我了解本工具僅供資訊整理與研究參考，不構成投資建議", value=settings["disclaimer_accepted"])
        if accepted != settings["disclaimer_accepted"]:
            settings = save_app_settings({"disclaimer_accepted": accepted})

    with ui.panel("2. 下載歷史資料", "選股、回測與籌碼指標需要約半年的上市股歷史，只需下載一次，約 20–30 分鐘"):
        _render_backfill_progress()
        if not desktop.backfill_status()["running"]:
            if st.button("開始下載歷史資料", type="primary"):
                ok, message = desktop.start_backfill()
                (st.success if ok else st.error)(message)
                st.rerun()

    with ui.panel("3. 設定 AI 分析（Codex）", "需要 ChatGPT 帳號並使用該帳號的額度；沒有也能使用資料收集、選股、回測與持股功能"):
        _render_codex_setup()

    with ui.panel("4. 每天自動收集"):
        _render_schedule_setup()

    if st.button("完成，開始使用", type="primary", disabled=not accepted):
        save_app_settings({"onboarding_done": True})
        st.switch_page(HOME_PAGE)
    if not accepted:
        st.caption("請先勾選第 1 項的說明")


def _render_update_notice():
    """安裝版才檢查新版本（一天最多一次，網路不通就不顯示）"""
    if not IS_INSTALLED:
        return
    release = updater.check_for_update()
    if not release:
        return
    st.info(f"有新版本 v{release['version']}")
    if release.get("page_url"):
        st.markdown(f"[看更新內容]({release['page_url']})")
    if st.button("下載並安裝更新", key="install_update", type="primary", width="stretch"):
        bar = st.progress(0.0, text="下載中...")

        def _progress(done, total):
            bar.progress(done / total if total else 0.0, text=f"下載中 {done / 1_048_576:,.0f} MB")

        ok, result = updater.download_installer(release, progress=_progress)
        bar.empty()
        if ok:
            ok, result = updater.run_installer(result)
        (st.success if ok else st.error)(result)


def _render_sidebar_footer():
    """所有頁面共用的側邊欄底部：新版本提示與版本"""
    with st.sidebar:
        st.divider()
        _render_update_notice()
        st.caption(f"台股分析 v{__version__}")


# 側邊欄導覽：大項目＝頁面，子項目＝頁內分頁（目前所在的大項目才展開子項目）
NAV_TABS = {
    "home": ["市場溫度計", "期貨法人", "產業熱力圖", "排行", "股價", "三大法人", "融資融券", "新聞", "收集紀錄"],
    "portfolio": ["持倉明細", "持股訊號", "AI 持股分析", "新增交易", "交易紀錄", "已實現損益"],
    "detail": ["技術面", "籌碼面", "基本面", "新聞", "AI 分析"],
    "screener": ["篩選器", "觀察名單", "訊號回測"],
    "alerts": ["最近觸發", "提醒規則", "新增提醒"],
    "calendar": ["持股與觀察名單", "其他提醒", "全市場除權息"],
    "ai": ["新聞深度分析", "大盤籌碼分析", "預測追蹤", "手動貼上"],
    "history": ["新聞", "新聞焦點", "個股分析", "大盤分析", "AI 預測"],
    "ai_settings": ["Codex CLI", "每日排程", "Firecrawl"],
}

ONBOARDING_NEEDED = _onboarding_needed()
ONBOARDING_PAGE = st.Page(onboarding_page, title="開始使用", url_path="onboarding", default=ONBOARDING_NEEDED)
HOME_PAGE = st.Page(home_page, title="市場總覽", url_path="home", default=not ONBOARDING_NEEDED)
PORTFOLIO_PAGE = st.Page(portfolio_page, title="我的持股", url_path="portfolio")
DETAIL_PAGE = st.Page(detail_page, title="個股詳情", url_path="detail")
SCREENER_PAGE = st.Page(screener_page, title="選股工具", url_path="screener")
ALERTS_PAGE = st.Page(alerts_page, title="條件提醒", url_path="alerts")
CALENDAR_PAGE = st.Page(calendar_page, title="行事曆", url_path="calendar")
AI_ANALYSIS_PAGE = st.Page(ai_analysis_page, title="AI 分析", url_path="ai")
REPORT_PAGE = st.Page(report_page, title="每日報告", url_path="report")
HISTORY_PAGE = st.Page(history_page, title="歷史查詢", url_path="history")
AI_SETTINGS_PAGE = st.Page(ai_settings_page, title="AI 設定", url_path="ai_settings")

NAV_PAGES = {
    "onboarding": ONBOARDING_PAGE, "home": HOME_PAGE, "portfolio": PORTFOLIO_PAGE, "detail": DETAIL_PAGE,
    "screener": SCREENER_PAGE, "alerts": ALERTS_PAGE, "calendar": CALENDAR_PAGE, "ai": AI_ANALYSIS_PAGE,
    "report": REPORT_PAGE, "history": HISTORY_PAGE, "ai_settings": AI_SETTINGS_PAGE,
}


def _toggle_nav_group():
    st.session_state["tw_nav_collapsed"] = not st.session_state.get("tw_nav_collapsed", False)


def _render_nav(current_id: str):
    """自訂側邊欄導覽（取代 Streamlit 內建導覽，才能有可摺疊的子項目）。
    手風琴式：只有目前頁面的大項目會展開；點目前頁面的大項目＝摺疊／展開，點其他大項目＝換頁並展開。
    按鈕 key 帶狀態（on＝目前頁面、open／shut＝子項目展開或摺疊），ui.py 以 key 前綴套樣式與箭頭。"""
    if st.session_state.get("tw_nav_page") != current_id:
        st.session_state["tw_nav_page"] = current_id
        st.session_state["tw_nav_collapsed"] = False
    if current_id != "detail":
        st.session_state.pop("detail_return", None)  # 離開個股詳情後就不需要返回按鈕了
    collapsed = st.session_state.get("tw_nav_collapsed", False)
    with st.sidebar, st.container(key="tw_nav"):
        ui.brand()
        for page_id, page in NAV_PAGES.items():
            active = page_id == current_id
            has_tabs = page_id in NAV_TABS
            fold = ("shut_" if collapsed or not active else "open_") if has_tabs else ""
            key = f"navg_{'on_' if active else ''}{fold}{page_id}"
            if active:
                st.button(page.title, key=key, width="stretch", on_click=_toggle_nav_group if has_tabs else None)
            elif st.button(page.title, key=key, width="stretch"):
                st.switch_page(page)
            if not active or not has_tabs or collapsed:
                continue
            labels = NAV_TABS[page_id]
            selected = ui.current_tab(page_id, labels)
            for index, label in enumerate(labels):
                on = label == selected
                # 用 on_click 在重跑前切換分頁；不要在腳本中途 st.rerun()，那會讓頁面上還沒畫到的輸入框狀態被清掉
                st.button(label, key=f"navs_{'on_' if on else ''}{page_id}_{index}", width="stretch",
                          on_click=ui.remember_tab, args=(page_id, label))
        if st.button("結束程式", key="navg_quit", width="stretch"):
            st.info("程式已結束，可以關閉這個瀏覽器分頁")
            # 稍等一下讓上面的訊息送到瀏覽器，再結束整個伺服器行程
            threading.Timer(1.0, os._exit, args=(0,)).start()
        st.divider()


if __name__ == "__main__":
    nav = st.navigation(list(NAV_PAGES.values()), position="hidden")
    _render_nav(next(pid for pid, page in NAV_PAGES.items() if page.url_path == nav.url_path))
    nav.run()
    _render_sidebar_footer()
