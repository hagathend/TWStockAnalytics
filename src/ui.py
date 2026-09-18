"""介面共用樣式與元件：統一字級、卡片、標籤、漲跌配色。

設計原則：
- 整個 app 只有四種字級：頁面標題、區塊標題、內文、輔助說明。頁面不要再直接用
  st.title / st.subheader / st.header / 「**粗體**當標題」，一律走 page_header() / section()，
  字級才不會大大小小（側邊欄原本用 st.header，比導覽列大一倍就是這樣來的）。
- 品牌區使用藍銀上升葉片標誌；導覽列與按鈕維持純文字，不放宣傳標語。
- 台股慣例紅漲綠跌：UP_COLOR／DOWN_COLOR 是唯一的漲跌色來源，圖表、表格、卡片都用這兩個。
"""

from html import escape
from pathlib import Path
import base64

from bs4 import BeautifulSoup

import pandas as pd
import streamlit as st

UP_COLOR = "#D83C48"
DOWN_COLOR = "#16845B"
ACCENT_COLOR = "#2864C5"
MUTED_COLOR = "#64758B"
CARD_BG = "#FFFFFF"
BORDER_COLOR = "#DCE5EF"
CHART_BG = "#FFFFFF"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');

/* 版面寬度與留白 */
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }}

/* 數字等寬，表格與卡片的數字才會對齊 */
[data-testid="stMetricValue"], .tw-card-value, .tw-quote-price {{ font-variant-numeric: tabular-nums; }}

/* 頁首 */
.tw-page-header {{ margin: 0 0 1.25rem 0; padding-bottom: 0.9rem; border-bottom: 1px solid {BORDER_COLOR}; }}
.tw-page-title {{ font-size: 1.85rem; font-weight: 700; line-height: 1.3; margin: 0; color: #172E4D; }}
.tw-page-subtitle {{ font-size: 0.9rem; color: {MUTED_COLOR}; margin-top: 0.3rem; }}

/* 區塊標題：左側細色條 */
.tw-section {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: 0.3rem 0.6rem; margin: 0.1rem 0 0.7rem 0; }}
.tw-section-title {{ font-size: 1.05rem; font-weight: 600; color: #172E4D;
                     border-left: 3px solid {ACCENT_COLOR}; padding-left: 0.55rem; line-height: 1.2; }}
.tw-section-caption {{ font-size: 0.8rem; color: {MUTED_COLOR}; }}

/* 側邊欄層級：導覽大項（主要功能）> 導覽子項（頁內分頁）> 區塊標籤（資料收集、觀察名單…）> 清單項目。不放圖示 */
section[data-testid="stSidebar"] [class*="st-key-navg_"] button {{
    justify-content: flex-start; width: 100%; padding: 0.45rem 0.75rem; min-height: 0; margin: 0.05rem 0;
    border-radius: 0.5rem; border: none; background: transparent; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"] button p {{ font-size: 1.02rem; font-weight: 500; color: #334F70; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"] button:hover {{ background: #E2ECF8; }}
/* 可摺疊的大項目：右側細箭頭（CSS 畫的線，不是圖示字型）；展開朝下、摺疊朝右 */
section[data-testid="stSidebar"] [class*="st-key-navg_"] button {{ position: relative; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"][class*="open_"] button::after,
section[data-testid="stSidebar"] [class*="st-key-navg_"][class*="shut_"] button::after {{
    content: ""; position: absolute; right: 0.95rem; top: 50%; width: 0.4rem; height: 0.4rem;
    border-right: 1.5px solid {MUTED_COLOR}; border-bottom: 1.5px solid {MUTED_COLOR}; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"][class*="open_"] button::after {{ transform: translateY(-70%) rotate(45deg); }}
section[data-testid="stSidebar"] [class*="st-key-navg_"][class*="shut_"] button::after {{ transform: translateY(-50%) rotate(-45deg); }}
section[data-testid="stSidebar"] [class*="st-key-navg_on_"] button {{ background: #D6E5F8; }}
section[data-testid="stSidebar"] [class*="st-key-navg_on_"] button p {{ color: #173D6C; font-weight: 600; }}
section[data-testid="stSidebar"] [class*="st-key-navs_"] button {{
    justify-content: flex-start; width: 100%; min-height: 0; padding: 0.28rem 0.75rem 0.28rem 0.85rem;
    margin: 0 0 0 1.1rem; width: calc(100% - 1.1rem); border-radius: 0 0.4rem 0.4rem 0; border: none;
    border-left: 2px solid {BORDER_COLOR}; background: transparent; }}
section[data-testid="stSidebar"] [class*="st-key-nav"] button > div,
section[data-testid="stSidebar"] [class*="st-key-nav"] button [data-testid="stMarkdownContainer"] {{
    justify-content: flex-start; text-align: left; width: 100%; }}
section[data-testid="stSidebar"] [class*="st-key-navs_"] button p {{ font-size: 0.88rem; color: {MUTED_COLOR}; }}
section[data-testid="stSidebar"] [class*="st-key-navs_"] button:hover p {{ color: #173D6C; }}
section[data-testid="stSidebar"] [class*="st-key-navs_on_"] button {{ border-left-color: {ACCENT_COLOR}; background: #EDF3FA; }}
section[data-testid="stSidebar"] [class*="st-key-navs_on_"] button p {{ color: #173D6C; font-weight: 500; }}
.st-key-tw_nav [data-testid="stVerticalBlock"] {{ gap: 0; }}
.st-key-tw_nav {{ gap: 0; padding-top: 0.4rem; }}
.tw-sidebar-label {{ font-size: 0.75rem; font-weight: 600; letter-spacing: 0.06em; color: {MUTED_COLOR};
                     margin: 0.9rem 0 0.35rem 0.1rem; }}
section[data-testid="stSidebar"] hr {{ margin: 0.9rem 0; }}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"] {{
    justify-content: flex-start; width: 100%; padding: 0.3rem 0.5rem; min-height: 0;
    font-size: 0.875rem; color: #334F70; border-radius: 0.4rem; }}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"] > div,
section[data-testid="stSidebar"] .stButton button[kind="tertiary"] [data-testid="stMarkdownContainer"] {{
    justify-content: flex-start; text-align: left; width: 100%; }}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover {{ background: #E2ECF8; color: #FFFFFF; }}

/* 卡片 */
.tw-card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr)); gap: 0.75rem;
                 margin: 0.2rem 0 0.4rem 0; }}
.tw-card {{ background: {CARD_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 0.6rem; padding: 0.8rem 1rem; }}
.tw-card-label {{ font-size: 0.85rem; color: {MUTED_COLOR}; margin-bottom: 0.25rem; }}
.tw-card-value {{ white-space: nowrap; font-size: 1.55rem; font-weight: 600; color: #172E4D; line-height: 1.3; }}
.tw-card-sub {{ font-size: 0.85rem; color: {MUTED_COLOR}; margin-top: 0.2rem; }}
.tw-up {{ color: {UP_COLOR} !important; }}
.tw-down {{ color: {DOWN_COLOR} !important; }}

/* 個股報價列 */
.tw-quote {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: 0.35rem 1rem; margin: 0.1rem 0 1rem 0; }}
.tw-quote-name {{ font-size: 1.35rem; font-weight: 700; color: #172E4D; }}
.tw-quote-code {{ font-size: 0.95rem; color: {MUTED_COLOR}; }}
.tw-quote-price {{ font-size: 1.35rem; font-weight: 600; }}
.tw-quote-meta {{ font-size: 0.8rem; color: {MUTED_COLOR}; }}

/* 標籤 */
.tw-chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.3rem 0 0.6rem 0; }}
.tw-chip {{ display: inline-block; font-size: 0.85rem; padding: 0.18rem 0.6rem; border-radius: 999px;
            border: 1px solid {BORDER_COLOR}; background: #EDF3FA; color: #334F70; white-space: nowrap; }}
.tw-chip.up {{ color: {UP_COLOR}; background: rgba(240, 82, 79, 0.12); border-color: rgba(240, 82, 79, 0.35); }}
.tw-chip.down {{ color: {DOWN_COLOR}; background: rgba(34, 181, 115, 0.12); border-color: rgba(34, 181, 115, 0.35); }}
.tw-chip.accent {{ color: #285FAC; background: rgba(76, 141, 246, 0.12); border-color: rgba(76, 141, 246, 0.35); }}
.tw-chip.warn {{ color: #966215; background: rgba(245, 185, 66, 0.12); border-color: rgba(245, 185, 66, 0.35); }}

/* 新聞卡片 */
.tw-news {{ padding: 0.75rem 0; border-bottom: 1px solid {BORDER_COLOR}; }}
.tw-news a {{ font-size: 0.95rem; font-weight: 500; color: #243F60; text-decoration: none; }}
.tw-news a:hover {{ color: #2459A6; }}
.tw-news-meta {{ font-size: 0.76rem; color: {MUTED_COLOR}; margin: 0.2rem 0; }}
.tw-news-body {{ font-size: 0.85rem; color: #52657C; line-height: 1.6; white-space: pre-line; }}

/* 面板（有邊框的區塊）：區塊之間拉開距離，內距一致 */
[data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD_BG}; }}
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"] {{ margin-bottom: 0.4rem; }}

/* 面板裡的卡片使用淡藍底色區分層次 */
[data-testid="stVerticalBlockBorderWrapper"] .tw-card {{ background: #F5F8FC; }}

/* 分頁籤 */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.4rem; border-bottom: 1px solid {BORDER_COLOR}; }}
.stTabs [data-baseweb="tab"] {{ padding: 0.5rem 0.1rem; font-size: 0.9rem; }}

/* 報告內文的 Markdown 標題也壓回統一字級 */
.st-key-tw_report h1 {{ font-size: 1.35rem; }}
.st-key-tw_report h2 {{ font-size: 1.05rem; border-left: 3px solid {ACCENT_COLOR}; padding-left: 0.55rem; margin-top: 1.6rem; }}
.st-key-tw_report h3 {{ font-size: 0.95rem; }}

/* 霧藍銀主題：品牌、淺色內容區與藍色導覽 */
.stApp {{ background: #F1F5FA; color: #172E4D; }}
/* 頂列不再覆蓋內容，保留窄視窗的側欄展開按鈕。 */
[data-testid="stHeader"] {{ background: transparent; height: 0; pointer-events: none; }}
[data-testid="stHeader"] button {{ pointer-events: auto; }}
[data-testid="stSidebarHeader"] {{ height: 2rem; min-height: 2rem; padding: 0.25rem 1rem; }}
[data-testid="stSidebarUserContent"] {{ padding-top: 0 !important; }}
.st-key-tw_nav {{ padding-top: 0; }}
@media (max-width: 768px) {{
    .block-container {{ padding-top: 3.25rem; }}
}}
section[data-testid="stSidebar"] {{ background: #365575; border-right: 1px solid #CAD8E8; }}
section[data-testid="stSidebar"] .tw-sidebar-label {{ color: #D2DFF0; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"] button p {{ color: #F2F6FC; }}
section[data-testid="stSidebar"] [class*="st-key-navs_"] button p {{ color: #D6E3F3; }}
section[data-testid="stSidebar"] [class*="st-key-nav"] button:hover {{ background: #46698F; }}
section[data-testid="stSidebar"] [class*="st-key-navg_on_"] button {{ background: #496F9B; box-shadow: inset 3px 0 #BCD5F8; }}
section[data-testid="stSidebar"] [class*="st-key-navs_on_"] button {{ background: #3E628A; border-left-color: #C1D9FA; }}
section[data-testid="stSidebar"] [class*="st-key-navs_on_"] button p {{ color: #FFFFFF; }}
.tw-brand {{ display:flex; align-items:center; gap:12px; padding:0 0 22px; margin-bottom:14px; border-bottom:1px solid #64809D; }}
.tw-brand img {{ width:48px; height:48px; flex-shrink:0; }}
.tw-brand-name {{ color:#FFFFFF; font-size:1.08rem; font-weight:700; letter-spacing:-0.3px; line-height:1.35; }}
.tw-brand-name span {{ display:block; color:#D1DEED; font-size:0.82rem; font-weight:400; letter-spacing:1.5px; }}
.tw-card {{ padding:1.1rem 1.15rem; border-radius:12px; box-shadow:0 3px 12px rgba(28,60,100,.035); }}
.tw-card-grid {{ gap:1rem; margin-bottom:1rem; }}
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlock"][style*="border:"] {{ border-radius:14px; background:#FFFFFF; }}
.stMain button[kind="secondary"] {{ background:#FFFFFF; border-color:#CAD8E8; color:#23476F; }}
.stMain button[kind="secondary"]:hover {{ border-color:#2864C5; background:#F0F5FC; }}
[data-testid="stDataFrame"] {{ border-radius:10px; overflow:hidden; }}
.tw-news {{ padding:1rem 0; }}
.tw-news-body {{ line-height:1.85; }}
.stTabs [data-baseweb="tab-list"] {{ gap:1.15rem; }}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"] {{ color:#E5EEF9; }}
section[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover {{ background:#46698F; }}
section[data-testid="stSidebar"] [class*="st-key-navg_"] button::after {{ border-color:#B7CCE5; }}
/* 側欄白底日期選單：不繼承側欄的白色文字。 */
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] input,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] {{
    color: #17202A !important; -webkit-text-fill-color: #17202A !important;
}}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {{ color: #17202A !important; fill: #17202A !important; }}
/* 滑鼠停留的提示框是白底，但側邊欄的按鈕提示會沿用側邊欄的淺色字，看不到；一律改深色字 */
[data-testid="stTooltipContent"], [data-testid="stTooltipContent"] * {{ color: #243F60 !important; }}
</style>

"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def _html(markup: str):
    st.markdown(markup, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None):
    sub = f'<div class="tw-page-subtitle">{escape(subtitle)}</div>' if subtitle else ""
    _html(f'<div class="tw-page-header"><div class="tw-page-title">{escape(title)}</div>{sub}</div>')


def section(title: str, caption: str | None = None):
    cap = f'<span class="tw-section-caption">{escape(caption)}</span>' if caption else ""
    _html(f'<div class="tw-section"><span class="tw-section-title">{escape(title)}</span>{cap}</div>')


def panel(title: str, caption: str | None = None):
    """有邊框的區塊，標題在框內左上。用法：with ui.panel("籌碼"): ...
    頁面上每個獨立主題（線圖、籌碼、新聞、AI 分析…）各用一個 panel，視覺上才有明確區隔。"""
    box = st.container(border=True)
    with box:
        section(title, caption)
    return box


_NAV_TABS_STORE = "tw_nav_tabs"


def remember_tab(page_id: str, label: str):
    """記住某頁要顯示的分頁（側邊欄子項目點選時呼叫）；下次進入該頁會停在這個分頁"""
    st.session_state.setdefault(_NAV_TABS_STORE, {})[page_id] = label
    st.session_state[f"tw_tabs_{page_id}"] = label


def current_tab(page_id: str, labels: list[str]) -> str:
    label = st.session_state.get(f"tw_tabs_{page_id}") or st.session_state.get(_NAV_TABS_STORE, {}).get(page_id)
    return label if label in labels else labels[0]


def page_tabs(page_id: str, labels: list[str]):
    """頁內分頁（對應側邊欄的子項目）：回傳 (目前分頁名稱, 分頁容器)。
    只執行目前分頁的內容（on_change 追蹤狀態），切換分頁不必重算其他分頁；
    widget 狀態在離開頁面時會被 Streamlit 清掉，所以另外記在 session_state 的字典裡，回到頁面時還原。"""
    key = f"tw_tabs_{page_id}"
    store = st.session_state.setdefault(_NAV_TABS_STORE, {})
    if st.session_state.get(key) not in labels:
        st.session_state[key] = store.get(page_id) if store.get(page_id) in labels else labels[0]

    def _changed():
        store[page_id] = st.session_state[key]

    containers = st.tabs(labels, key=key, on_change=_changed)
    active = st.session_state[key]
    store[page_id] = active
    return active, containers[labels.index(active)]


_KEPT_WIDGETS = "tw_kept_widgets"


def restore_widgets(defaults: dict):
    """在畫 widget 之前呼叫。Streamlit 換頁時會清掉沒畫出來的 widget 狀態，這裡把上次保存的值（沒有就用預設值）放回去；
    widget 本身不要再傳 value／default（預設值已經放進 session_state），值為 None 的 number_input 維持 value=None"""
    store = st.session_state.setdefault(_KEPT_WIDGETS, {})
    for key, default in defaults.items():
        if key not in st.session_state:
            value = store.get(key, default)
            if value is not None:
                st.session_state[key] = value


def remember_widgets(keys):
    """畫完 widget 之後呼叫：保存目前的值，下次回到這一頁時由 restore_widgets 還原"""
    store = st.session_state.setdefault(_KEPT_WIDGETS, {})
    for key in keys:
        if key in st.session_state:
            store[key] = st.session_state[key]


def sidebar_label(text: str):
    _html(f'<div class="tw-sidebar-label">{escape(text)}</div>')


def tone_of(value) -> str:
    """數值 → 漲跌語意（台股紅漲綠跌）"""
    if value is None or pd.isna(value) or value == 0:
        return ""
    return "up" if value > 0 else "down"


def cards(items: list[dict]):
    """items: [{"label", "value", "sub"(選填), "tone"(選填: up/down), "sub_tone"(選填)}]"""
    blocks = []
    for item in items:
        tone = f' tw-{item["tone"]}' if item.get("tone") else ""
        sub = ""
        if item.get("sub"):
            sub_tone = f' tw-{item["sub_tone"]}' if item.get("sub_tone") else ""
            sub = f'<div class="tw-card-sub{sub_tone}">{escape(str(item["sub"]))}</div>'
        blocks.append(
            f'<div class="tw-card"><div class="tw-card-label">{escape(item["label"])}</div>'
            f'<div class="tw-card-value{tone}">{escape(str(item["value"]))}</div>{sub}</div>'
        )
    _html(f'<div class="tw-card-grid">{"".join(blocks)}</div>')


def chips(items: list[tuple[str, str]], empty_text: str = "無"):
    """items: [(文字, tone)]，tone 為 up / down / accent / warn / ""（中性）"""
    if not items:
        _html(f'<div class="tw-chips"><span class="tw-chip">{escape(empty_text)}</span></div>')
        return
    spans = "".join(f'<span class="tw-chip {tone}">{escape(text)}</span>' for text, tone in items)
    _html(f'<div class="tw-chips">{spans}</div>')


def quote_header(code: str, name: str, close=None, change=None, change_pct=None, date: str | None = None):
    parts = [f'<span class="tw-quote-name">{escape(name)}</span>', f'<span class="tw-quote-code">{escape(code)}</span>']
    if close is not None:
        tone = tone_of(change)
        cls = f" tw-{tone}" if tone else ""
        change_text = ""
        if change is not None and change_pct is not None:
            change_text = f"　{change:+,.2f}（{change_pct:+.2f}%）"
        parts.append(f'<span class="tw-quote-price{cls}">{close:,.2f}{change_text}</span>')
    if date:
        parts.append(f'<span class="tw-quote-meta">收盤日 {escape(date)}</span>')
    _html(f'<div class="tw-quote">{"".join(parts)}</div>')


def strip_html(text: str) -> str:
    """RSS 摘要常夾帶 HTML 標籤，顯示前轉純文字"""
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True) if text else ""


def news_item(title: str, url: str | None, meta: str = "", body: str = ""):
    link = f'<a href="{escape(url)}" target="_blank">{escape(title)}</a>' if url else f"<b>{escape(title)}</b>"
    meta_html = f'<div class="tw-news-meta">{escape(meta)}</div>' if meta else ""
    body_html = f'<div class="tw-news-body">{escape(body)}</div>' if body else ""
    _html(f'<div class="tw-news">{link}{meta_html}{body_html}</div>')


def color_signed(styler_or_df, columns: list[str]):
    """表格裡的正負數欄位上紅漲綠跌色。回傳 pandas Styler，可直接丟給 st.dataframe。"""
    styler = styler_or_df.style if isinstance(styler_or_df, pd.DataFrame) else styler_or_df
    present = [c for c in columns if c in styler.data.columns]

    def _color(value):
        tone = tone_of(value) if isinstance(value, (int, float)) else ""
        return f"color: {UP_COLOR}" if tone == "up" else f"color: {DOWN_COLOR}" if tone == "down" else ""

    return styler.map(_color, subset=present) if present else styler


def style_chart(fig, height: int | None = None):
    """plotly 圖表套用跟頁面一致的淺色底、格線與字型"""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=CHART_BG,
        plot_bgcolor=CHART_BG,
        font={"family": "Noto Sans TC, Microsoft JhengHei, sans-serif", "size": 12, "color": "#334F70"},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": BORDER_COLOR},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0, "bgcolor": "rgba(0,0,0,0)"},
    )
    fig.update_xaxes(gridcolor="#E7EDF5", zeroline=False, linecolor=BORDER_COLOR)
    fig.update_yaxes(gridcolor="#E7EDF5", zeroline=False, linecolor=BORDER_COLOR)
    if height:
        fig.update_layout(height=height)
    return fig


def brand():
    """只顯示品牌識別，不放口號。"""
    logo = Path(__file__).resolve().parent / "assets" / "brand.svg"
    encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
    _html(f'<div class="tw-brand"><img src="data:image/svg+xml;base64,{encoded}" alt="TWStockAnalytics 標誌">'
          '<div class="tw-brand-name">TWStock<span>Analytics</span></div></div>')
