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

from datetime import date as _date  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from src.ai_analysis import analyze_with_codex_deep, build_prompt, parse_and_save  # noqa: E402
from src.codex_cli import generate_codex_text, check_codex_login, list_codex_models
from src.charting import build_candlestick
from src.chip_metrics import metrics_for_code
from src.chip_metrics import summarize_for_prompt as summarize_chip_metrics
from src.collect_all import run_daily_collect
from src.collectors.firecrawl_fetcher import test_connection as firecrawl_test_connection
from src.config_ai import (
    load_codex_settings,
    load_report_settings,
    load_scraping_settings,
    save_codex_settings,
    save_report_settings,
    save_scraping_settings,
)
from src.config_watchlist import add_stock, load_watchlist, remove_stock
from src.market_analysis import build_market_analysis_prompt, save_market_analysis
from src.report_pdf import markdown_to_pdf
from src import backtest, fundamentals, portfolio, signals, ui
from src.stock_analysis import build_stock_analysis_prompt, save_stock_analysis, strip_holding_section
from src.storage import db

st.set_page_config(page_title="台股每日資訊收集", layout="wide")
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
    """表格共用樣式：正負數紅漲綠跌、千分位、小數兩位、缺值顯示「-」"""
    present = set(df.columns)
    int_cols = [c for c in thousands if c in present]
    float_cols = [c for c in decimals if c in present]
    # 合併基本面後缺值可能是 None（object 欄位），格式化會略過而直接顯示「None」，先轉成數值 NaN
    df = df.copy()
    for column in {*int_cols, *float_cols, *(c for c in signed if c in present)}:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    styler = ui.color_signed(df, list(signed))
    if int_cols:
        styler = styler.format("{:,.0f}", subset=int_cols, na_rep="-")
    if float_cols:
        styler = styler.format("{:,.2f}", subset=float_cols, na_rep="-")
    return styler


def _md_linebreaks(text: str) -> str:
    """AI回覆通常一行一個重點，但 Markdown 規則裡單一換行會被當成空白吃掉、
    不會顯示成新的一行，要轉成 Markdown 的強制換行語法（兩個空白+換行）才會正確顯示。"""
    return (text or "").replace("\n", "  \n")


def _go_to_detail(code: str):
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
    """畫出各頁共用的側邊欄（收集按鈕、查詢日期、觀察名單），回傳目前選擇的查詢日期。
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

        ui.sidebar_label("觀察名單")
        watchlist = load_watchlist()
        if not watchlist:
            st.caption("尚未新增任何股票")
        for code, name in list(watchlist.items()):
            col_btn, col_del = st.columns([5, 1], vertical_alignment="center")
            with col_btn:
                if st.button(f"{code}　{name}", key=f"watch_{code}", type="tertiary", width="stretch"):
                    _go_to_detail(code)
            with col_del:
                if st.button("×", key=f"del_{code}", type="tertiary", help="從觀察名單移除"):
                    remove_stock(code)
                    st.rerun()

        with st.form("add_watch_form", clear_on_submit=True, border=False):
            col_input, col_add = st.columns([5, 2], vertical_alignment="bottom")
            new_code = col_input.text_input("新增股票", placeholder="輸入代號", label_visibility="collapsed",
                                            key="new_watch_code")
            submitted = col_add.form_submit_button("新增", width="stretch")
            if submitted and new_code:
                name = db.lookup_stock_name(new_code) or new_code
                add_stock(new_code, name)
                st.rerun()

        ui.sidebar_label("新聞焦點 Top 20")
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


def home_page():
    selected_date = _render_sidebar()
    ui.page_header("市場總覽", f"{selected_date} 盤後價量、三大法人、融資融券與新聞")

    _market_summary_cards(selected_date)

    with st.container(border=True):
        tab_price, tab_inst, tab_margin, tab_news, tab_log = st.tabs(
            ["股價", "三大法人買賣超", "融資融券", "新聞", "收集紀錄"]
        )

        with tab_price:
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

        with tab_inst:
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

        with tab_margin:
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

        with tab_news:
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

        with tab_log:
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

        existing_analysis = db.query_stock_analysis(_date.today().isoformat(), code)
        if existing_analysis:
            st.divider()
            st.caption(f"今天已儲存的分析・{existing_analysis[0]['created_at']}")
            st.markdown(_md_linebreaks(existing_analysis[0]["analysis"]))


def detail_page():
    selected_date = _render_sidebar()
    ui.page_header("個股詳情", "K 線、籌碼、基本面、新聞與 AI 分析")

    col_input, _ = st.columns([1, 3])
    code = col_input.text_input("股票代號", value=st.session_state.get("selected_code", ""),
                                placeholder="輸入股票代號，例如 2330", label_visibility="collapsed")
    if not code:
        st.info("請輸入股票代號，或從左側觀察名單／新聞焦點點選")
        return

    name = db.lookup_stock_name(code) or code
    _render_quote(code, name)
    _render_position_panel(code)

    with ui.panel("K 線走勢", "近 90 天・均線 MA5／MA20／MA60・資料來源 FinMind"):
        with st.spinner("讀取 K 線資料中..."):
            fig = build_candlestick(code, name)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.warning("查無此股票的歷史價量資料（可能代號輸入錯誤，或 FinMind 目前沒有資料）")

    col_chip, col_fund = st.columns([3, 2])
    with col_chip:
        _render_chip_panel(code)
    with col_fund:
        _render_fundamentals_panel(code)

    _render_history_panel(code)

    with ui.panel("相關新聞", selected_date):
        news_rows = db.query_news(selected_date, code)
        if news_rows:
            for row in news_rows:
                ui.news_item(row["title"], row.get("url"), row.get("source") or "",
                             ui.strip_html(row.get("summary") or ""))
        else:
            st.caption("此日期尚無相關新聞（目前只有標題含代號的新聞會被標記關聯）")

    _render_stock_ai_panel(code)


# ─────────────────────────────── 我的持股 ───────────────────────────────

_POSITION_COLUMNS = {
    "code": "代號", "name": "名稱", "holding": "持有", "avg_cost": "平均成本", "close": "收盤",
    "price_date": "價格日期", "market_value": "市值", "pnl": "未實現損益", "pnl_pct": "報酬率%",
    "weight": "佔比%", "holding_days": "持有天數", "signals": "今日訊號",
}


def _render_position_panel(code: str):
    """個股詳情頁：有持有這檔才顯示"""
    records = db.query_holdings(code)
    if not records:
        return
    p = portfolio.summarize_position(records, db.query_latest_close(code))
    with ui.panel("我的持股", "損益以本地最新收盤價計算，未扣手續費與證交稅"):
        items = [
            {"label": "持有", "value": portfolio.lots_text(p["shares"]), "sub": f"{p['records']} 筆買進"},
            {"label": "平均成本", "value": f"{p['avg_cost']:,.2f}",
             "sub": f"最早買進 {p['first_buy_date']}" if p["first_buy_date"] else None},
        ]
        if p["pnl"] is not None:
            items += [
                {"label": "未實現損益", "value": f"{p['pnl']:+,.0f}", "tone": ui.tone_of(p["pnl"]),
                 "sub": f"市值 {p['market_value']:,.0f}"},
                {"label": "報酬率", "value": f"{p['pnl_pct']:+.2f}%", "tone": ui.tone_of(p["pnl_pct"]),
                 "sub": f"持有 {p['holding_days']} 天" if p["holding_days"] is not None else None},
            ]
        ui.cards(items)


def _render_add_holding_form():
    with st.form("add_holding_form", clear_on_submit=True, border=False):
        c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1.2, 1.4])
        code = c1.text_input("股票代號", placeholder="例如 2330")
        lots = c2.number_input("張數", min_value=0, value=1, step=1)
        odd = c3.number_input("零股（股）", min_value=0, max_value=999, value=0, step=100)
        price = c4.number_input("成交均價", min_value=0.0, value=None, step=0.5, format="%.2f")
        buy_date = c5.date_input("買進日期", value=_date.today(), max_value=_date.today())
        note = st.text_input("備註（選填）", placeholder="例如：拉回月線分批買進")
        if st.form_submit_button("新增紀錄", type="primary"):
            shares = int(lots) * portfolio.SHARES_PER_LOT + int(odd)
            code = code.strip()
            if not code or not shares or not price:
                st.warning("請填入股票代號、股數與成交均價")
            else:
                name = db.lookup_stock_name(code) or code
                db.add_holding(code, name, shares, float(price), buy_date.isoformat(), note)
                st.rerun()


def _render_holding_records():
    records = db.query_holdings()
    if not records:
        st.caption("尚無買進紀錄")
        return
    df = pd.DataFrame(records)
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce").dt.date
    df["delete"] = False
    edited = st.data_editor(
        df[["id", "code", "name", "shares", "cost_price", "buy_date", "note", "delete"]],
        hide_index=True, width="stretch", key="holding_editor",
        disabled=["id", "code", "name"],
        column_config={
            "id": None,
            "code": st.column_config.TextColumn("代號"),
            "name": st.column_config.TextColumn("名稱"),
            "shares": st.column_config.NumberColumn("股數", min_value=1, step=1, format="%d",
                                                    help="1 張 = 1000 股；賣出部分時直接改股數"),
            "cost_price": st.column_config.NumberColumn("成交均價", min_value=0.0, format="%.2f"),
            "buy_date": st.column_config.DateColumn("買進日期", format="YYYY-MM-DD"),
            "note": st.column_config.TextColumn("備註"),
            "delete": st.column_config.CheckboxColumn("刪除", help="勾選後按「儲存變更」刪除這筆（例如已全部賣出）"),
        },
    )
    if st.button("儲存變更", key="save_holdings"):
        original = df.set_index("id")
        changed = 0
        for row in edited.to_dict("records"):
            if row["delete"]:
                db.delete_holding(int(row["id"]))
                changed += 1
                continue
            before = original.loc[row["id"]]
            buy_date = row["buy_date"].isoformat() if pd.notna(row["buy_date"]) else None
            before_date = before["buy_date"].isoformat() if pd.notna(before["buy_date"]) else None
            if (int(row["shares"]) != int(before["shares"]) or float(row["cost_price"]) != float(before["cost_price"])
                    or buy_date != before_date or (row["note"] or "") != (before["note"] or "")):
                db.update_holding(int(row["id"]), int(row["shares"]), float(row["cost_price"]), buy_date,
                                  row["note"] or "")
                changed += 1
        if changed:
            st.rerun()
        st.info("沒有變更")


def _analyze_all_positions(positions: list[dict]):
    progress = st.progress(0.0, text="準備中...")
    failures = []
    for index, p in enumerate(positions, start=1):
        progress.progress((index - 1) / len(positions),
                          text=f"分析 {p['code']} {p['name']}（{index}/{len(positions)}）")
        ok, text = generate_codex_text(build_stock_analysis_prompt(p["code"]))
        if ok:
            save_stock_analysis(p["code"], text)
        else:
            failures.append(f"{p['code']}：{text}")
    progress.empty()
    if failures:
        st.error("部分分析失敗：\n" + "\n".join(failures))
    else:
        st.success(f"已完成 {len(positions)} 檔持股分析，並收錄到每日報告")


def portfolio_page():
    _render_sidebar()
    ui.page_header("我的持股", "持倉成本與損益以本地最新收盤價計算，未扣手續費與證交稅；資料只存在本機資料庫")

    positions = portfolio.load_positions()
    if positions:
        totals = portfolio.portfolio_totals(positions)
        ui.cards([
            {"label": "持股檔數", "value": f"{totals['positions']}"},
            {"label": "總成本", "value": f"{totals['cost']:,.0f}"},
            {"label": "總市值", "value": f"{totals['market_value']:,.0f}",
             "sub": f"{totals['unpriced']} 檔查無收盤價未計入" if totals["unpriced"] else None},
            {"label": "未實現損益", "value": f"{totals['pnl']:+,.0f}", "tone": ui.tone_of(totals["pnl"])},
            {"label": "報酬率", "value": "-" if totals["pnl_pct"] is None else f"{totals['pnl_pct']:+.2f}%",
             "tone": ui.tone_of(totals["pnl_pct"])},
        ])

        signal_df = _cached_signal_history()
        latest = signals.latest_rows(signal_df)
        codes = [p["code"] for p in positions]
        active_by_code = {}
        if not latest.empty:
            held = latest[latest["code"].isin(codes)]
            active_by_code = {r["code"]: "、".join(signals.SIGNALS[k] for k in signals.active_signals(r))
                              for _, r in held.iterrows()}

        with ui.panel("持倉明細", "點選任一列開啟個股詳情"):
            rows = [{
                **p,
                "holding": portfolio.lots_text(p["shares"]),
                "weight": p["market_value"] / totals["market_value"] * 100
                if p["market_value"] is not None and totals["market_value"] else None,
                "signals": active_by_code.get(p["code"], ""),
            } for p in positions]
            view = pd.DataFrame(rows)[list(_POSITION_COLUMNS)].rename(columns=_POSITION_COLUMNS)
            event = st.dataframe(
                _styled_table(view, signed=["未實現損益", "報酬率%"], thousands=["市值", "未實現損益", "持有天數"],
                              decimals=["平均成本", "收盤", "報酬率%", "佔比%"]),
                width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
                key="position_table",
                column_config={"今日訊號": st.column_config.TextColumn("今日訊號", width="large")},
            )
            if event.selection.rows:
                _go_to_detail(positions[event.selection.rows[0]]["code"])

        with ui.panel("持股訊號", "僅上市股・區分今日新出現與持續中的訊號"):
            _render_signal_alerts(signals.watchlist_alerts(signal_df, codes), "持股今天沒有觸發任何訊號")

        with ui.panel("AI 持股分析", "逐檔用 Codex 分析，提示詞附上你的成本與損益，列出續抱／減碼／停損的觀察條件"):
            if st.button("用 Codex 逐檔分析持股並儲存", type="primary"):
                _analyze_all_positions(positions)
            today = _date.today().isoformat()
            for p in positions:
                saved = db.query_stock_analysis(today, p["code"])
                if saved:
                    with st.expander(f"{p['code']} {p['name']}・今天的分析（{saved[0]['created_at']}）"):
                        st.markdown(_md_linebreaks(saved[0]["analysis"]))
    else:
        st.info("還沒有持股紀錄，請在下方新增第一筆買進紀錄")

    with ui.panel("新增買進紀錄", "同一檔分批買進請分開記錄，會自動計算加權平均成本"):
        _render_add_holding_form()

    with ui.panel("買進紀錄", "可直接修改股數、成交均價、日期與備註；部分賣出請改股數，全部賣出請勾選刪除"):
        _render_holding_records()


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

    with ui.panel("新聞深度分析", "先取得新聞內文，逐篇摘要後挑出最多 20 檔有新聞依據的焦點個股"):
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

        col3, col4 = st.columns(2)
        timeout = col3.number_input("每次分析最長等待秒數", min_value=30, max_value=1800,
                                    value=int(settings["timeout_seconds"]))
        auto = col4.checkbox("收集後自動用 Codex 分析新聞", value=settings["auto_analyze_after_collect"])
        edited = {"executable": executable, "model": model, "timeout_seconds": int(timeout),
                  "auto_analyze_after_collect": auto}

        b1, b2, b3, _ = st.columns([1, 1, 1, 2])
        if b1.button("儲存設定", type="primary", width="stretch"):
            save_codex_settings(edited)
            st.success("已儲存")
        if b2.button("測試所選模型", width="stretch"):
            with st.spinner("測試模型中..."):
                ok, message = generate_codex_text("請只回覆：連線成功", settings=edited)
            (st.success if ok else st.error)(message)
        if b3.button("檢查登入", width="stretch"):
            ok, message = check_codex_login(edited)
            (st.success if ok else st.error)(message)

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


_SCREEN_COLUMNS = {
    "code": "代號", "name": "名稱", "close": "收盤", "change_pct": "漲跌%",
    "return_20d": "20日報酬%", "rs_rank_pct": "相對強弱",
    "foreign_streak": "外資連買賣", "trust_streak": "投信連買賣",
    "vol_ma20_lots": "20日均量(張)", "pe_ratio": "本益比", "dividend_yield": "殖利率%",
    "pb_ratio": "淨值比", "yoy_pct": "營收年增%", "signals": "觸發訊號",
}


def _render_screen_tab(signal_df: pd.DataFrame):
    with ui.panel("篩選條件"):
        labels = {v: k for k, v in signals.SIGNALS.items()}
        chosen = st.multiselect("訊號條件", list(labels), default=[signals.SIGNALS["breakout_20d"]])
        col1, col2, _ = st.columns([1, 1, 2])
        mode = col1.segmented_control("條件組合", ["全部符合", "符合任一"], default="全部符合") or "全部符合"
        min_lots = col2.number_input("20日均量至少（張）", min_value=0, value=500, step=100)
        with st.expander("基本面條件（留空＝不限制；設了條件時缺資料的股票會被排除）"):
            f1, f2, f3, f4 = st.columns(4)
            pe_max = f1.number_input("本益比 ≤", min_value=0.0, value=None, step=1.0)
            yield_min = f2.number_input("殖利率% ≥", min_value=0.0, value=None, step=0.5)
            pb_max = f3.number_input("淨值比 ≤", min_value=0.0, value=None, step=0.5)
            yoy_min = f4.number_input("營收年增% ≥", value=None, step=5.0)

    result = signals.screen(signal_df, [labels[c] for c in chosen], min_avg_volume_lots=min_lots,
                            mode="all" if mode == "全部符合" else "any")
    result = fundamentals.attach_fundamentals(result, fundamentals.latest_fundamentals())
    result = fundamentals.apply_filters(result, pe_max=pe_max, yield_min=yield_min, pb_max=pb_max, yoy_min=yoy_min)

    with ui.panel("篩選結果", f"符合 {len(result)} 檔・依相對強弱排序・點選任一列開啟個股詳情"):
        if result.empty:
            st.caption("沒有符合條件的股票")
            return
        result["vol_ma20_lots"] = (result["vol_ma20"] / 1000).round(0)
        view = result[list(_SCREEN_COLUMNS)].rename(columns=_SCREEN_COLUMNS)
        styler = _styled_table(
            view, signed=["漲跌%", "20日報酬%", "外資連買賣", "投信連買賣", "營收年增%"],
            thousands=["20日均量(張)", "外資連買賣", "投信連買賣"],
            decimals=["收盤", "漲跌%", "20日報酬%", "本益比", "殖利率%", "淨值比", "營收年增%"],
        )
        event = st.dataframe(
            styler, width="stretch", hide_index=True, height=560, on_select="rerun",
            selection_mode="single-row", key="screen_table",
            column_config={
                "相對強弱": st.column_config.ProgressColumn("相對強弱", min_value=0, max_value=100, format="%.0f",
                                                        help="同一天全市場 20 日報酬的百分位排名"),
                "觸發訊號": st.column_config.TextColumn("觸發訊號", width="large"),
            },
        )
        if event.selection.rows:
            _go_to_detail(result.iloc[event.selection.rows[0]]["code"])


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


def _render_alert_tab(signal_df: pd.DataFrame):
    alerts = signals.watchlist_alerts(signal_df, load_watchlist().keys())
    with ui.panel("觀察名單訊號", "僅上市股（上櫃資料源無法回補歷史，暫不計算）"):
        _render_signal_alerts(alerts, "觀察名單今天沒有觸發任何訊號")


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

    screen_tab, alert_tab, backtest_tab = st.tabs(["篩選器", "觀察名單警示", "訊號回測"])
    with screen_tab:
        _render_screen_tab(signal_df)
    with alert_tab:
        _render_alert_tab(signal_df)
    with backtest_tab:
        _render_backtest_tab()


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


HOME_PAGE = st.Page(home_page, title="市場總覽", default=True)
PORTFOLIO_PAGE = st.Page(portfolio_page, title="我的持股")
DETAIL_PAGE = st.Page(detail_page, title="個股詳情")
SCREENER_PAGE = st.Page(screener_page, title="選股工具")
AI_ANALYSIS_PAGE = st.Page(ai_analysis_page, title="AI 分析")
REPORT_PAGE = st.Page(report_page, title="每日報告")
AI_SETTINGS_PAGE = st.Page(ai_settings_page, title="AI 設定")

if __name__ == "__main__":
    nav = st.navigation([HOME_PAGE, PORTFOLIO_PAGE, DETAIL_PAGE, SCREENER_PAGE, AI_ANALYSIS_PAGE, REPORT_PAGE, AI_SETTINGS_PAGE])
    nav.run()
