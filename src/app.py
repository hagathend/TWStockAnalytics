"""台股每日資訊收集 - Streamlit UI"""

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
    load_scraping_settings,
    save_codex_settings,
    save_scraping_settings,
)
from src.config_watchlist import add_stock, load_watchlist, remove_stock
from src.market_analysis import build_market_analysis_prompt, save_market_analysis
from src.report_pdf import markdown_to_pdf
from src import signals
from src.stock_analysis import build_stock_analysis_prompt, save_stock_analysis
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

# collect_log 的 status 存英文識別字，顯示時轉成中文
_LOG_STATUS_LABELS = {"success": "✅ 成功", "no_data": "⚠ 無資料", "failed": "❌ 失敗"}


def _display_df(rows: list[dict], column_labels: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.rename(columns=column_labels)[
        [column_labels[c] for c in column_labels if c in df.columns]
    ]


def _md_linebreaks(text: str) -> str:
    """AI回覆通常一行一個重點，但 Markdown 規則裡單一換行會被當成空白吃掉、
    不會顯示成新的一行，要轉成 Markdown 的強制換行語法（兩個空白+換行）才會正確顯示。"""
    return (text or "").replace("\n", "  \n")


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
            codex_settings = load_codex_settings()
            if codex_settings.get("auto_analyze_after_collect"):
                progress_bar = st.progress(0.0, text="準備深度分析（先抓內文再逐篇摘要，可能要幾分鐘）...")

                def _update_progress(cur, total, msg):
                    progress_bar.progress(cur / total if total else 0.0, text=f"{msg} ({cur}/{total})")

                ai_result = analyze_with_codex_deep(
                    today,
                    progress_callback=_update_progress,
                )
                progress_bar.empty()
                if ai_result["ok"]:
                    st.success(f"AI 深度分析完成，已產生 {len(ai_result['picks'])} 檔新聞焦點")
                else:
                    st.warning(f"自動 AI 分析失敗（可到「AI 分析」頁改用複製貼上）：{ai_result['message']}")
            else:
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
            logs = [
                {**row, "status": _LOG_STATUS_LABELS.get(row["status"], row["status"])}
                for row in logs
            ]
            st.dataframe(
                _display_df(logs, _LOG_COLUMNS), width="stretch", hide_index=True
            )
        else:
            st.info("尚無收集紀錄")


def _render_chip_metrics(code: str):
    metrics = metrics_for_code(code)
    st.markdown("**籌碼延伸指標**（依本地累積的法人／融資歷史計算）")
    if not metrics:
        st.caption("尚無籌碼歷史資料")
        return

    def _lots(value):
        return "資料不足" if value is None else f"{value / 1000:+,.0f} 張"

    def _streak(value):
        return f"連買 {value} 天" if value > 0 else f"連賣 {-value} 天" if value < 0 else "無連續"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("外資", _streak(metrics["foreign_streak"]), _lots(metrics["foreign_net_5d"]) + "（5日）",
              delta_color="off")
    c2.metric("投信", _streak(metrics["trust_streak"]), _lots(metrics["trust_net_5d"]) + "（5日）",
              delta_color="off")
    c3.metric("三大法人 20 日", _lots(metrics["total_net_20d"]))
    ratio = metrics["inst_volume_ratio_5d"]
    c4.metric("法人佔成交量（5日）", "資料不足" if ratio is None else f"{ratio:+.1f}%")
    with st.expander("完整籌碼指標（給 AI 的同一份文字）"):
        st.text(summarize_chip_metrics(metrics))

    latest = signals.latest_rows(_cached_signal_history())
    row = latest[latest["code"] == code] if not latest.empty else latest
    if not row.empty:
        active = signals.active_signals(row.iloc[0])
        tags = [("🔻" if k in signals.BEARISH_SIGNALS else "🔺") + signals.SIGNALS[k] for k in active]
        st.markdown(f"**今日訊號（{row.iloc[0]['date']}）**：" + ("　".join(tags) if tags else "無"))


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

    _render_chip_metrics(code)

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

    st.divider()
    st.subheader("AI 個股分析（Codex CLI）")
    st.caption("Codex 依籌碼、線型及新聞產生分析，完成後自動儲存並收錄報告。也可展開提示詞手動使用。")
    if st.button("用 Codex 分析個股並儲存", key="codex_stock"):
        with st.spinner("Codex 正在分析個股..."):
            prompt = build_stock_analysis_prompt(code)
            ok, text = generate_codex_text(prompt)
            if ok:
                result = save_stock_analysis(code, text)
                (st.success if result["ok"] else st.error)(result["message"])
            else:
                st.error(text)

    if st.button("產生個股分析提示詞", key="gen_stock_prompt"):
        st.session_state["stock_prompt_code"] = code
        st.session_state["stock_prompt"] = build_stock_analysis_prompt(code)

    if st.session_state.get("stock_prompt_code") == code and st.session_state.get("stock_prompt"):
        st.code(st.session_state["stock_prompt"], language=None)
        st.caption("複製上面的內容，貼到你平常用的網頁版 AI，把回覆貼到下面")

    raw_stock_analysis = st.text_area("貼上 AI 的分析結果", height=200, key="stock_analysis_input")
    if st.button("儲存個股分析", key="save_stock_analysis_btn"):
        result = save_stock_analysis(code, raw_stock_analysis)
        if result["ok"]:
            st.success(result["message"])
        else:
            st.warning(result["message"])

    existing_analysis = db.query_stock_analysis(_date.today().isoformat(), code)
    if existing_analysis:
        st.markdown("**今天已儲存的分析**")
        st.write(_md_linebreaks(existing_analysis[0]["analysis"]))
        st.caption(f"儲存時間: {existing_analysis[0]['created_at']}")


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

    st.subheader(f"逐篇新聞摘要（{source_label}，共 {len(excerpts)} 則）")
    st.caption("這些是深度分析時，AI 針對每則新聞內文各自產生的重點摘要，之後可以直接拿來當報表素材。")
    for item in excerpts:
        with st.container(border=True):
            title_line = f"**[{item['title']}]({item['url']})**" if item.get("url") else f"**{item['title']}**"
            st.markdown(title_line)
            st.caption(f"來源: {item['source']}")
            st.write(_md_linebreaks(item["excerpt"]))


def ai_analysis_page():
    st.title("AI 分析")
    st.caption("使用已登入的 Codex CLI 摘要新聞、彙整焦點個股，結果直接儲存並收錄報告。")

    today = _date.today().isoformat()
    available_dates = db.query_available_dates() or [today]
    selected_date = st.selectbox("要分析哪一天收集到的新聞", available_dates)

    st.subheader("Codex 新聞深度分析")
    st.caption("先取得新聞內文，再逐篇摘要與挑選最多 20 檔有新聞依據的焦點個股。")
    if st.button("用 Codex 分析這天的新聞", type="primary"):
        progress_bar = st.progress(0.0, text="準備中...")

        def _update_progress(cur, total, msg):
            progress_bar.progress(cur / total if total else 0.0, text=f"{msg} ({cur}/{total})")

        result = analyze_with_codex_deep(
            selected_date,
            progress_callback=_update_progress,
        )
        progress_bar.empty()
        st.session_state["last_deep_result_date"] = selected_date
        st.session_state["last_deep_result"] = result
        if result["ok"]:
            st.success(result["message"])
        else:
            st.error(result["message"])

    _render_article_excerpts(selected_date)

    st.divider()
    st.subheader("1. 產生提示詞（複製貼上流程，不想接任何 API 時用）")
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

    st.divider()
    st.subheader("大盤整體籌碼分析（Codex CLI）")
    st.caption("整合籌碼、短中期展望、熱門產業與個股消息，總計 1000 字內，儲存後收錄每日報告。")
    if st.button("用 Codex 分析大盤並儲存", key="codex_market"):
        with st.spinner("Codex 正在分析大盤..."):
            ok, text = build_market_analysis_prompt(selected_date)
            if ok:
                ok, text = generate_codex_text(text)
                if ok:
                    result = save_market_analysis(text, selected_date)
                    (st.success if result["ok"] else st.error)(result["message"])
            if not ok:
                st.error(text)

    if st.button("產生大盤分析提示詞"):
        ok, prompt_or_msg = build_market_analysis_prompt(selected_date)
        if ok:
            st.session_state["market_prompt"] = prompt_or_msg
        else:
            st.warning(prompt_or_msg)

    market_prompt = st.session_state.get("market_prompt", "")
    if market_prompt:
        st.code(market_prompt, language=None)
        st.caption("複製上面的內容，貼到網頁版 AI，把回覆貼到下面")

    raw_market_analysis = st.text_area("貼上 AI 的大盤分析結果", height=200, key="market_analysis_input")
    if st.button("儲存大盤分析", key="save_market_analysis_btn"):
        result = save_market_analysis(raw_market_analysis, selected_date)
        if result["ok"]:
            st.success(result["message"])
        else:
            st.warning(result["message"])

    existing_market = db.query_market_analysis(selected_date)
    if existing_market:
        st.markdown("**已儲存的大盤分析**")
        st.write(_md_linebreaks(existing_market["analysis"]))
        st.caption(f"儲存時間: {existing_market['created_at']}")


def ai_settings_page():
    st.title("AI 設定")

    st.subheader("Codex CLI")
    st.caption("使用這台電腦的 Codex 登入。會使用帳號的 Codex 額度，不需在本程式填 API Key。")
    settings = load_codex_settings()
    executable = st.text_input("Codex 執行檔（通常填 codex 即可）", value=settings["executable"])
    catalog = list_codex_models()
    models = {m["slug"]: m for m in catalog}
    options = [""] + list(models)
    current = settings.get("model", "")
    if current and current not in options:
        options.append(current)
    labels = {"": "使用 CLI 預設模型"}
    labels.update({slug: entry.get("display_name", slug) for slug, entry in models.items()})
    model = st.selectbox("分析模型", options, index=options.index(current),
                         format_func=lambda value: labels.get(value, value))
    if model in models:
        st.caption(models[model].get("description", ""))
    st.caption("清單來自這台電腦的 Codex 模型目錄；可按下方測試確認帳號目前能否使用。")
    if not catalog:
        st.info("尚未取得模型清單，請先登入並開啟 Codex CLI，再重新整理本頁。")
    if st.checkbox("手動指定其他模型"):
        model = st.text_input("模型代號", value=current)

    timeout = st.number_input("每次分析最長等待秒數", min_value=30, max_value=1800,
                              value=int(settings["timeout_seconds"]))
    auto = st.checkbox("收集後自動用 Codex 分析新聞", value=settings["auto_analyze_after_collect"])
    edited = {"executable": executable, "model": model, "timeout_seconds": int(timeout),
              "auto_analyze_after_collect": auto}
    if st.button("測試所選模型"):
        with st.spinner("測試模型中..."):
            ok, message = generate_codex_text("請只回覆：連線成功", settings=edited)
        (st.success if ok else st.error)(message)
    if st.button("檢查 Codex 登入"):
        ok, message = check_codex_login(edited)
        (st.success if ok else st.error)(message)
    if st.button("儲存 Codex 設定", type="primary"):
        save_codex_settings(edited)
        st.success("已儲存")

    st.divider()

    st.subheader("Firecrawl（內文擷取，選用）")
    st.caption(
        "深度分析要抓 Google News RSS 連結的文章內文時，優先用 Firecrawl（免費額度每月1000次，"
        "不用信用卡，通常比本機 Playwright 抓得更乾淨），沒設定 Key 就自動退回 Playwright。"
        "到 https://www.firecrawl.dev/ 申請 API Key。"
    )
    scraping_settings = load_scraping_settings()
    firecrawl_key = st.text_input(
        "Firecrawl API Key",
        value=scraping_settings.get("firecrawl_api_key", ""),
        type="password",
        placeholder="輸入 Firecrawl API Key（留空則不使用，改用 Playwright）",
    )
    col_save_fc, col_test_fc = st.columns([1, 1])
    with col_save_fc:
        if st.button("儲存 Firecrawl 設定"):
            save_scraping_settings({"firecrawl_api_key": firecrawl_key})
            st.success("已儲存")
    with col_test_fc:
        if st.button("測試連線", key="test_firecrawl"):
            ok, message = firecrawl_test_connection(firecrawl_key)
            if ok:
                st.success(message)
            else:
                st.error(message)



@st.cache_data(ttl=600, show_spinner="計算全市場訊號中...")
def _cached_signal_history(as_of: str | None = None) -> pd.DataFrame:
    """全市場訊號計算約需數秒，快取 10 分鐘；收集完新資料後最多 10 分鐘就會反映"""
    return signals.load_signal_history(as_of=as_of)


_SCREEN_COLUMNS = {
    "code": "代號", "name": "名稱", "close": "收盤", "change_pct": "漲跌%",
    "return_20d": "20日報酬%", "rs_rank_pct": "相對強弱(百分位)",
    "foreign_streak": "外資連買賣(天)", "trust_streak": "投信連買賣(天)",
    "vol_ma20_lots": "20日均量(張)", "signals": "觸發訊號",
}


def screener_page():
    st.title("選股工具")
    _render_sidebar()
    st.caption("訊號由程式依本地資料庫的上市（TWSE）價量與籌碼歷史計算，只是篩選條件，不構成投資建議。")

    signal_df = _cached_signal_history()
    if signal_df.empty:
        st.warning("本地資料庫沒有上市歷史資料，請先執行收集或 scripts/backfill_history.py 補歷史")
        return
    trading_days = signal_df["date"].nunique()
    st.caption(f"資料截至 {signal_df['date'].max()}，共 {trading_days} 個交易日"
               + ("（未滿 60 天，60日相關訊號暫時不會觸發）" if trading_days < 61 else ""))

    screen_tab, alert_tab = st.tabs(["篩選器", "觀察名單警示"])
    with screen_tab:
        labels = {v: k for k, v in signals.SIGNALS.items()}
        chosen = st.multiselect("訊號條件", list(labels), default=[signals.SIGNALS["breakout_20d"]])
        col1, col2 = st.columns(2)
        mode = col1.radio("條件組合", ["全部符合", "符合任一"], horizontal=True)
        min_lots = col2.number_input("20日均量至少（張）", min_value=0, value=500, step=100)
        result = signals.screen(signal_df, [labels[c] for c in chosen], min_avg_volume_lots=min_lots,
                                mode="all" if mode == "全部符合" else "any")
        st.markdown(f"**符合 {len(result)} 檔**（依相對強弱排序，點選列可看個股詳情）")
        if not result.empty:
            result["vol_ma20_lots"] = (result["vol_ma20"] / 1000).round(0)
            view = result[list(_SCREEN_COLUMNS)].rename(columns=_SCREEN_COLUMNS).round(2)
            event = st.dataframe(view, width="stretch", hide_index=True,
                                 on_select="rerun", selection_mode="single-row", key="screen_table")
            if event.selection.rows:
                _go_to_detail(result.iloc[event.selection.rows[0]]["code"])

    with alert_tab:
        watchlist = load_watchlist()
        alerts = signals.watchlist_alerts(signal_df, watchlist.keys())
        st.caption("只涵蓋上市股；上櫃（TPEx）資料源無法回補歷史，暫不計算訊號。")
        st.markdown(signals.format_alerts_markdown(alerts))


def _format_net(value) -> str:
    return f"{value:+,}" if value is not None else "-"


def _build_report_text(date: str) -> str:
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
            inst_rows = db.query_institutional(date, p["code"])
            inst = inst_rows[0] if inst_rows else None
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

    lines.append("## 個股深度分析")
    stock_analyses = db.query_stock_analysis(date)
    if stock_analyses:
        for sa in stock_analyses:
            lines.append(f"### {sa['code']} {sa['name']}")
            lines.append(_md_linebreaks(sa["analysis"]))
            lines.append(f"\n*儲存時間: {sa['created_at']}*")
            lines.append("")
    else:
        lines.append("_（此日期尚無個股深度分析，可到「個股詳情」頁為關注的股票產生分析）_")

    return "\n".join(lines)


def report_page():
    st.title("每日報告")
    st.caption("彙整新聞摘要、AI 新聞焦點個股（含當日三大法人買賣超）、個股深度分析，可直接複製或下載。")

    today = _date.today().isoformat()
    available_dates = db.query_available_dates() or [today]
    selected_date = st.selectbox("選擇報告日期", available_dates, key="report_date")

    report_text = _build_report_text(selected_date)
    st.markdown(report_text)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "下載報告 (Markdown)",
            report_text,
            file_name=f"twstock_report_{selected_date}.md",
            mime="text/markdown",
        )
    with col2:
        if st.button("產生 PDF"):
            with st.spinner("產生 PDF 中..."):
                st.session_state["report_pdf_bytes"] = markdown_to_pdf(report_text)
                st.session_state["report_pdf_date"] = selected_date

        if (
            st.session_state.get("report_pdf_date") == selected_date
            and st.session_state.get("report_pdf_bytes")
        ):
            st.download_button(
                "下載報告 (PDF)",
                st.session_state["report_pdf_bytes"],
                file_name=f"twstock_report_{selected_date}.pdf",
                mime="application/pdf",
            )


HOME_PAGE = st.Page(home_page, title="總覽", icon="📊", default=True)
DETAIL_PAGE = st.Page(detail_page, title="個股詳情", icon="📈")
AI_ANALYSIS_PAGE = st.Page(ai_analysis_page, title="AI 分析", icon="🤖")
SCREENER_PAGE = st.Page(screener_page, title="選股工具", icon="🔎")
REPORT_PAGE = st.Page(report_page, title="每日報告", icon="📝")
AI_SETTINGS_PAGE = st.Page(ai_settings_page, title="AI 設定", icon="⚙️")

if __name__ == "__main__":
    nav = st.navigation([HOME_PAGE, DETAIL_PAGE, SCREENER_PAGE, AI_ANALYSIS_PAGE, REPORT_PAGE, AI_SETTINGS_PAGE])
    nav.run()
