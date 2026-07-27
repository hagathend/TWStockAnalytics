"""台股每日資訊收集 - Streamlit UI"""

from datetime import date as _date

import pandas as pd
import streamlit as st

from src.ai_analysis import build_prompt, parse_and_save
from src.ai_providers import PROVIDER_LABELS, generate_text, test_connection
from src.charting import build_candlestick
from src.collect_all import run_daily_collect
from src.config_ai import PROVIDERS, load_ai_settings, save_ai_settings
from src.config_watchlist import add_stock, load_watchlist, remove_stock
from src.storage import db

st.set_page_config(page_title="台股每日資訊收集", layout="wide")

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
    "total_net": "三大法人合計買賣超(股)",
}

_MARGIN_COLUMNS = {
    "date": "日期",
    "market": "市場",
    "code": "代號",
    "name": "名稱",
    "margin_balance": "融資餘額(股)",
    "margin_buy": "融資買進(股)",
    "margin_sell": "融資賣出(股)",
    "short_balance": "融券餘額(股)",
    "short_sell": "融券賣出(股)",
    "short_cover": "融券償還(股)",
}

_LOG_COLUMNS = {
    "id": "編號",
    "run_at": "執行時間",
    "step": "項目",
    "status": "狀態",
    "detail": "詳細",
}

_PICK_COLUMNS = {"rank": "排名", "code": "代號", "name": "名稱", "reason": "原因"}


def _display_df(rows: list[dict], column_labels: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.rename(columns=column_labels)[
        [column_labels[c] for c in column_labels if c in df.columns]
    ]


def _go_to_detail(code: str):
    st.session_state["selected_code"] = code
    st.switch_page(DETAIL_PAGE)


def _render_sidebar() -> str:
    """畫出各頁共用的側邊欄（收集按鈕、查詢日期、觀察名單），回傳目前選擇的查詢日期"""
    with st.sidebar:
        st.header("資料收集")
        if st.button("立即收集今日資料", type="primary", width="stretch"):
            with st.spinner("收集中，請稍候（含官方 OpenAPI / FinMind / 新聞來源）..."):
                result = run_daily_collect()
            st.success("收集完成")
            st.json(result)

            today = _date.today().isoformat()
            ok, prompt_or_msg = build_prompt(today)
            if ok:
                st.session_state["pending_ai_prompt"] = prompt_or_msg
                st.info("新聞分析提示詞已產生，請到左側「AI 分析」頁複製使用")

        st.divider()
        st.header("查詢日期")
        available_dates = db.query_available_dates()
        if available_dates:
            selected_date = st.selectbox("選擇日期", available_dates)
        else:
            selected_date = st.text_input(
                "輸入日期 (YYYY-MM-DD)", value=_date.today().isoformat()
            )

        st.divider()
        st.header("我的觀察名單")
        watchlist = load_watchlist()
        if not watchlist:
            st.caption("尚未新增任何股票")
        for code, name in list(watchlist.items()):
            col_btn, col_del = st.columns([4, 1])
            with col_btn:
                if st.button(
                    f"{code} {name}", key=f"watch_{code}", width="stretch"
                ):
                    _go_to_detail(code)
            with col_del:
                if st.button("✕", key=f"del_{code}", help="從觀察名單移除"):
                    remove_stock(code)
                    st.rerun()

        with st.form("add_watch_form", clear_on_submit=True):
            new_code = st.text_input("輸入股票代號新增", key="new_watch_code")
            submitted = st.form_submit_button("新增到觀察名單")
            if submitted and new_code:
                name = db.lookup_stock_name(new_code) or new_code
                add_stock(new_code, name)
                st.rerun()

        st.divider()
        st.header("新聞焦點 Top 20 (AI 分析)")
        ai_picks = db.query_ai_picks(selected_date)
        if ai_picks:
            for pick in ai_picks:
                label = f"{pick['rank']}. {pick['code']} {pick['name']}"
                if st.button(
                    label,
                    key=f"pick_{pick['code']}_{pick['rank']}",
                    width="stretch",
                    help=pick.get("reason"),
                ):
                    _go_to_detail(pick["code"])
        else:
            st.caption("此日期尚無 AI 分析結果，請到「AI 分析」頁產生")

    return selected_date


def home_page():
    st.title("台股每日資訊收集")
    st.caption("每日收集盤後價量 / 三大法人 / 融資融券 / 新聞，可送交 AI 分析當日新聞焦點個股。")

    selected_date = _render_sidebar()

    tab_price, tab_inst, tab_margin, tab_news, tab_log = st.tabs(
        ["股價總覽", "三大法人買賣超", "融資融券", "新聞", "收集紀錄"]
    )

    with tab_price:
        filter_code = st.text_input(
            "依股票代號或名稱搜尋（例如：2330 或 台積，留空顯示全部，僅本頁）", key="price_code"
        )
        rows = db.query_stock_price(selected_date, filter_code or None)
        if rows:
            df = _display_df(rows, _PRICE_COLUMNS)
            st.dataframe(df, width="stretch", hide_index=True, height=500)
            st.caption(f"共 {len(df)} 筆")
        else:
            st.info("此日期尚無股價資料，請先點擊左側「立即收集今日資料」")

    with tab_inst:
        filter_code = st.text_input("依股票代號或名稱搜尋", key="inst_code")
        rows = db.query_institutional(selected_date, filter_code or None)
        if rows:
            df = _display_df(rows, _INSTITUTIONAL_COLUMNS)
            st.dataframe(df, width="stretch", hide_index=True, height=500)
            st.caption(f"共 {len(df)} 筆")
        else:
            st.info("此日期尚無三大法人資料")

    with tab_margin:
        filter_code = st.text_input("依股票代號或名稱搜尋", key="margin_code")
        rows = db.query_margin(selected_date, filter_code or None)
        if rows:
            df = _display_df(rows, _MARGIN_COLUMNS)
            st.dataframe(df, width="stretch", hide_index=True, height=500)
            st.caption(f"共 {len(df)} 筆")
        else:
            st.info("此日期尚無融資融券資料")

    with tab_news:
        filter_code = st.text_input("依股票代號或標題關鍵字搜尋", key="news_code")
        rows = db.query_news(selected_date, filter_code or None)
        if rows:
            for row in rows:
                with st.container(border=True):
                    st.markdown(f"**[{row['title']}]({row['url']})**")
                    meta = f"來源: {row['source']}"
                    if row.get("related_code"):
                        meta += f" | 關聯代號: {row['related_code']}"
                    if row.get("published_at"):
                        meta += f" | 發布時間: {row['published_at']}"
                    st.caption(meta)
                    if row.get("summary"):
                        st.write(row["summary"])
            st.caption(f"共 {len(rows)} 筆")
        else:
            st.info("此日期尚無新聞資料")

    with tab_log:
        logs = db.query_recent_logs()
        if logs:
            st.dataframe(
                _display_df(logs, _LOG_COLUMNS), width="stretch", hide_index=True
            )
        else:
            st.info("尚無收集紀錄")


def detail_page():
    st.title("個股詳情")
    selected_date = _render_sidebar()

    default_code = st.session_state.get("selected_code", "")
    code = st.text_input("股票代號", value=default_code)
    if not code:
        st.info("請輸入股票代號，或從左側觀察名單 / AI 分析 Top 20 點選")
        return

    name = db.lookup_stock_name(code) or code
    st.subheader(f"{code} {name}")

    with st.spinner("讀取 K 線資料中（即時向 FinMind 取得）..."):
        fig = build_candlestick(code, name)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning("查無此股票的歷史價量資料（可能代號輸入錯誤，或 FinMind 目前沒有資料）")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**三大法人買賣超歷史**（本地資料庫累積，每天收集一筆）")
        rows = db.query_code_history("institutional", code)
        if rows:
            st.dataframe(
                _display_df(rows, _INSTITUTIONAL_COLUMNS), width="stretch", hide_index=True
            )
        else:
            st.caption("尚無資料")
    with col2:
        st.markdown("**融資融券歷史**（本地資料庫累積，每天收集一筆）")
        rows = db.query_code_history("margin", code)
        if rows:
            st.dataframe(
                _display_df(rows, _MARGIN_COLUMNS), width="stretch", hide_index=True
            )
        else:
            st.caption("尚無資料")

    st.markdown(f"**{selected_date} 相關新聞**")
    news_rows = db.query_news(selected_date, code)
    if news_rows:
        for row in news_rows:
            with st.container(border=True):
                st.markdown(f"**[{row['title']}]({row['url']})**")
                if row.get("summary"):
                    st.write(row["summary"])
    else:
        st.caption("此日期尚無相關新聞（新聞的關聯代號目前只有標題內含代號時才會標記）")


def ai_analysis_page():
    st.title("AI 分析")
    st.caption(
        "免費做法：產生提示詞 → 複製貼到你平常用的網頁版 Claude / ChatGPT / Gemini → "
        "把回覆貼回來解析，不需要另外申請付費 API Key。"
        "若你已經有付費 API Key，也可以用下方「進階」選項直接呼叫、跳過複製貼上。"
    )

    today = _date.today().isoformat()
    available_dates = db.query_available_dates() or [today]
    selected_date = st.selectbox("要分析哪一天收集到的新聞", available_dates)

    st.subheader("1. 產生提示詞")
    if st.button("產生新聞分析提示詞"):
        ok, prompt_or_msg = build_prompt(selected_date)
        if ok:
            st.session_state["pending_ai_prompt"] = prompt_or_msg
        else:
            st.warning(prompt_or_msg)

    prompt = st.session_state.get("pending_ai_prompt", "")
    if prompt:
        st.code(prompt, language=None)
        st.caption(
            "複製上面的內容（右上角有複製按鈕），貼到 claude.ai / chatgpt.com / "
            "gemini.google.com 網頁版，把它的回覆貼到下面"
        )

    st.subheader("2. 貼上 AI 的回覆")
    raw_response = st.text_area("貼上 AI 回覆的完整內容", height=200, key="ai_raw_response")
    if st.button("解析並儲存", type="primary"):
        result = parse_and_save(selected_date, "manual_paste", raw_response)
        if result["ok"]:
            st.success(result["message"])
        else:
            st.error(result["message"])

    st.divider()
    with st.expander("進階：直接呼叫付費 API（跳過複製貼上，需先在「AI 設定」頁填好 Key）"):
        ai_settings = load_ai_settings()
        provider = ai_settings["active_provider"]
        api_key = ai_settings["keys"].get(provider, "")
        st.caption(f"目前設定使用: {PROVIDER_LABELS[provider]}（此按鈕會實際呼叫付費 API，依供應商計費規則產生費用）")
        if st.button(f"直接呼叫 {PROVIDER_LABELS[provider]} 分析"):
            ok, prompt_or_msg = build_prompt(selected_date)
            if not ok:
                st.warning(prompt_or_msg)
            else:
                with st.spinner("呼叫 AI 中，請稍候..."):
                    gen_ok, text = generate_text(provider, api_key, prompt_or_msg)
                if not gen_ok:
                    st.error(text)
                else:
                    result = parse_and_save(selected_date, provider, text)
                    if result["ok"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])

    st.divider()
    st.subheader(f"{selected_date} 目前的分析結果")
    summary = db.query_ai_analysis_summary(selected_date)
    if summary:
        st.markdown(f"**摘要**：{summary['summary']}")
        st.caption(f"分析來源: {summary['provider']} ｜ 產生時間: {summary['created_at']}")
    picks = db.query_ai_picks(selected_date)
    if picks:
        st.dataframe(
            _display_df(picks, _PICK_COLUMNS), width="stretch", hide_index=True
        )
    else:
        st.caption("尚無分析結果")


def ai_settings_page():
    st.title("AI 設定")
    st.caption(
        "選擇之後新聞分析要用哪家 AI，並填入對應 API Key（供「AI 分析」頁的進階直接呼叫選項使用）。"
        "Key 僅存在本機 data/ai_settings.json，不會上傳、不會加入 git。"
    )

    ai_settings = load_ai_settings()

    active_provider = st.radio(
        "目前使用的 AI 供應商",
        PROVIDERS,
        format_func=lambda p: PROVIDER_LABELS[p],
        index=PROVIDERS.index(ai_settings["active_provider"]),
        horizontal=True,
    )

    st.divider()

    updated_keys = dict(ai_settings["keys"])
    for provider in PROVIDERS:
        st.subheader(PROVIDER_LABELS[provider])
        col_key, col_test = st.columns([4, 1])
        with col_key:
            updated_keys[provider] = st.text_input(
                "API Key",
                value=ai_settings["keys"].get(provider, ""),
                type="password",
                key=f"key_{provider}",
                label_visibility="collapsed",
                placeholder=f"輸入 {PROVIDER_LABELS[provider]} API Key",
            )
        with col_test:
            if st.button("測試連線", key=f"test_{provider}", width="stretch"):
                ok, message = test_connection(provider, updated_keys[provider])
                if ok:
                    st.success(message)
                else:
                    st.error(message)

    st.divider()
    if st.button("儲存設定", type="primary"):
        save_ai_settings({"active_provider": active_provider, "keys": updated_keys})
        st.success(f"已儲存，目前使用的 AI 供應商: {PROVIDER_LABELS[active_provider]}")


HOME_PAGE = st.Page(home_page, title="總覽", icon="📊", default=True)
DETAIL_PAGE = st.Page(detail_page, title="個股詳情", icon="📈")
AI_ANALYSIS_PAGE = st.Page(ai_analysis_page, title="AI 分析", icon="🤖")
AI_SETTINGS_PAGE = st.Page(ai_settings_page, title="AI 設定", icon="⚙️")

if __name__ == "__main__":
    nav = st.navigation([HOME_PAGE, DETAIL_PAGE, AI_ANALYSIS_PAGE, AI_SETTINGS_PAGE])
    nav.run()
