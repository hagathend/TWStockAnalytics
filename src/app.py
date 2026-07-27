"""台股每日資訊收集 - Streamlit UI（第一階段：資料收集與瀏覽）"""

from datetime import date as _date

import pandas as pd
import streamlit as st

from src.ai_providers import PROVIDER_LABELS, test_connection
from src.collect_all import run_daily_collect
from src.config import WATCHLIST
from src.config_ai import PROVIDERS, load_ai_settings, save_ai_settings
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


def _display_df(rows: list[dict], column_labels: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.rename(columns=column_labels)[
        [column_labels[c] for c in column_labels if c in df.columns]
    ]

st.title("台股每日資訊收集")
st.caption("第一階段：定時收集盤後價量 / 三大法人 / 融資融券 / 新聞。AI 籌碼與線型分析邏輯為第二階段規劃中，目前先提供供應商設定介面。")

with st.sidebar:
    st.header("資料收集")
    if st.button("立即收集今日資料", type="primary", use_container_width=True):
        with st.spinner("收集中，請稍候（含官方 OpenAPI / FinMind / 新聞來源）..."):
            result = run_daily_collect()
        st.success("收集完成")
        st.json(result)

    st.divider()
    st.header("查詢日期")
    available_dates = db.query_available_dates()
    if available_dates:
        selected_date = st.selectbox("選擇日期", available_dates)
    else:
        selected_date = st.text_input("輸入日期 (YYYY-MM-DD)", value=_date.today().isoformat())

    st.divider()
    st.header("觀察名單")
    for code, name in WATCHLIST.items():
        st.write(f"{code} {name}")

tab_price, tab_inst, tab_margin, tab_news, tab_log, tab_ai = st.tabs(
    ["股價總覽", "三大法人買賣超", "融資融券", "新聞", "收集紀錄", "AI 設定"]
)

with tab_price:
    filter_code = st.text_input("依股票代號篩選（留空顯示全部，僅本頁）", key="price_code")
    rows = db.query_stock_price(selected_date, filter_code or None)
    if rows:
        df = _display_df(rows, _PRICE_COLUMNS)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"共 {len(df)} 筆")
    else:
        st.info("此日期尚無股價資料，請先點擊左側「立即收集今日資料」")

with tab_inst:
    filter_code = st.text_input("依股票代號篩選", key="inst_code")
    rows = db.query_institutional(selected_date, filter_code or None)
    if rows:
        df = _display_df(rows, _INSTITUTIONAL_COLUMNS)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"共 {len(df)} 筆")
    else:
        st.info("此日期尚無三大法人資料")

with tab_margin:
    filter_code = st.text_input("依股票代號篩選", key="margin_code")
    rows = db.query_margin(selected_date, filter_code or None)
    if rows:
        df = _display_df(rows, _MARGIN_COLUMNS)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"共 {len(df)} 筆")
    else:
        st.info("此日期尚無融資融券資料")

with tab_news:
    filter_code = st.text_input("依股票代號篩選（新聞標題含代號時可用）", key="news_code")
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
        st.dataframe(_display_df(logs, _LOG_COLUMNS), use_container_width=True, hide_index=True)
    else:
        st.info("尚無收集紀錄")

with tab_ai:
    st.caption(
        "選擇之後新聞摘要 / 籌碼與線型分析要用哪家 AI，並填入對應 API Key。"
        "Key 僅存在本機 data/ai_settings.json，不會上傳、不會加入 git。"
        "本頁只驗證登入與連線，實際分析功能將於第二階段後續開發。"
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
            if st.button("測試連線", key=f"test_{provider}", use_container_width=True):
                ok, message = test_connection(provider, updated_keys[provider])
                if ok:
                    st.success(message)
                else:
                    st.error(message)

    st.divider()
    if st.button("儲存設定", type="primary"):
        save_ai_settings({"active_provider": active_provider, "keys": updated_keys})
        st.success(f"已儲存，目前使用的 AI 供應商: {PROVIDER_LABELS[active_provider]}")
