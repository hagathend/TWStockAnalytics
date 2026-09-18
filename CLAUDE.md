# CLAUDE.md — TWStockAnalytics 專案指南

Python 3.13 + Streamlit 的台股每日分析系統：收集盤後資料與新聞 → AI 分析 → 產出報告。
完整規劃與踩坑歷史見 `PLAN.md`（主文件），使用說明見 `README.md`。

---

## ⚠ 六個必知陷阱

這些都是實際踩過、修過的坑，**不要重蹈覆轍**。

### 1. 驗證 Streamlit 有沒有正常跑，`curl` 拿到 200 是假陽性

`curl http://localhost:8501` 只會拿到外層 HTML 空殼，Streamlit 的 Python 腳本要等
**websocket 連線**才會執行——`ModuleNotFoundError` 這種錯誤根本不會出現在 curl 結果裡。

**正確驗證方式**（擇一）：
- 用 Browser 工具實際載入頁面：`navigate` → `get_page_text`，看內容有沒有真的渲染出來
- 用 `streamlit.testing.v1.AppTest` 跑（可以模擬點按鈕、抓 `at.exception`）

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("src/app.py"); at.run(timeout=30)
print(list(at.exception))   # 必須是空的
```

### 2. 政府開放資料的「最新一筆」不等於「今天」，不可覆蓋成今天的日期

`openapi.twse.com.tw` 的 `STOCK_DAY_ALL` / `MI_MARGN` 會**延遲公布**（同一時間點舊版 `rwd`
介面已經是當天收盤價，openapi 還停留在前一交易日）。曾經為了讓兩個市場日期對齊，把資料
強制蓋上 `date.today()`，等於**把舊資料偽裝成當天收盤價**（使用者拿 Yahoo 比對才抓到）。

現在 TWSE 一律走可指定日期、回應會確認實際日期的 rwd 介面：
- 股價：`https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999`
- 法人：`https://www.twse.com.tw/rwd/zh/fund/T86`
- 融資券：`https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN`

TPEx 則信任 API 回傳的 ROC 日期，**不要覆蓋**。寧可兩市場日期偶爾不同步，也不要造假日期。

### 3. LLM 會把股票「代號」和「名稱」配錯，一定要用本地資料校正

實測 qwen2.5:7b 把 2454 聯發科講成 2357、把台達電講成不存在的 6700。
`src/ai_analysis.py` 的 `_verify_pick()` 用本地官方資料對照校正：**新聞文字通常寫公司名稱，
名稱比代號可信**，對不上時以名稱回查代號為準。任何新的「AI 產生股票代號」情境都要套這個。

### 4. LLM 在「自己判斷要不要保留」時會系統性過度保守，而且每個階段都會

深度分析原本 53 篇摘要只挑出 2 檔。修的時候發現**不只最終彙整那一步會亂砍，連前面
「分批找候選」那一步也會**（15 篇裡明明有 5-6 家公司提到具體財報，只挑 1-3 檔）。
兩層 prompt 都要明確寫「不要自己判斷重要性、有實質內容就列出/保留，篩選交給下一步」。

**通用教訓**：多階段 pipeline 裡每個「AI 自己決定篩選」的環節都要**個別驗證輸出數量**，
不能只看最終結果、也不能改好一個地方就假設整條路都通了。

### 5. Markdown 單一換行會被吃掉

AI 回覆通常一行一個重點，但 CommonMark 規則裡單一 `\n` 會被當空白，顯示時全部黏成一段。
所有要顯示 AI 回覆的地方都要過 `app.py` 的 `_md_linebreaks()`（把 `\n` 換成 `"  \n"`）。

### 6. 混合多來源做排序截斷時，量大的來源會把量少但重要的來源整個排擠掉

曾經依時間排序取前 25 篇，結果鉅亨網把 Google News RSS（觀察名單個股專屬新聞）全部擠掉，
導致 Playwright 抓取那條路徑實際上從沒被執行過。現在改成
`_MAX_CNYES_FOR_DEEP` / `_MAX_RSS_FOR_DEEP` **分開設定各自保底名額**。

---

## 專案結構

```
src/
├── app.py                 Streamlit 入口（開始使用／市場總覽／我的持股／個股詳情／選股工具／條件提醒／行事曆／AI 分析／每日報告／歷史查詢／AI 設定）
├── ui.py                  共用樣式元件（頁首、面板、卡片、標籤、紅漲綠跌）
├── codex_cli.py           Codex CLI 非互動呼叫、登入檢查、JSON Schema
├── ai_analysis.py         新聞深度分析：抓內文→逐篇摘要→分批挑股（Codex；Ollama 函式保留未使用）
├── news_relevance.py      摘要前用本地公司名稱／代號過濾與個股無關的新聞（省 Codex 額度）
├── stock_analysis.py      個股分析提示詞（技術＋籌碼＋基本面＋持股）
├── market_analysis.py     大盤籌碼分析提示詞
├── indicators.py / chip_metrics.py / signals.py / backtest.py / fundamentals.py   程式計算的指標、訊號、回測
├── portfolio.py           交易紀錄重播：平均成本、稅費、未實現／已實現損益、覆盤提示詞
├── predictions.py         AI 預測摘要解析與儲存（每次個股分析一筆）
├── prediction_views.py    預測改以「觀點」計分：同方向連續預測合併，方向改變或滿 10 個交易日結算；中性另計、翻轉次數
├── history.py             歷史查詢：新聞焦點上榜次數統計、依期間／方向／狀態篩選 AI 預測（查詢 SQL 在 db.search_*）
├── alerts.py / notify.py  條件提醒與 Windows 通知；calendar_events.py 行事曆
├── market_breadth.py / market_index.py / heatmap.py / futures.py   市場溫度計、加權指數與相對強弱、產業熱力圖、期貨法人
├── revenue.py / financials.py / pe_river.py   月營收趨勢、季度財報、本益比河流圖
├── shareholding.py / ownership.py / price_levels.py   千張大戶、外資持股與借券、支撐壓力與成交量密集區
├── charting.py            個股 K 線圖（plotly + FinMind）
├── report_pdf.py          報告 Markdown → PDF（Playwright）
├── collect_all.py         每日收集流程；backfill.py 歷史補收集
├── scheduled_ai.py        收集後的 AI 分析（新聞／持股／觀察名單，各自在 codex_settings.json 開關，預設只分析新聞）
├── desktop.py             安裝版：背景工作、工作排程、Codex 登入
├── updater.py             安裝版：檢查 GitHub Releases 並更新
├── config.py / config_ai.py / config_app.py / config_watchlist.py   設定讀寫；version.py 版本號
├── ai_providers.py        舊的 Ollama／雲端 API 封裝（已停用，保留程式碼）
├── collectors/            twse_official（TWSE rwd + TPEx）、fundamentals、finmind、news_crawler、news_rss、
│                          firecrawl_fetcher、article_fetcher、twse_market（加權指數）、twse_ownership（外資持股／借券）、
│                          dividends、tdcc（集保股權分散）、mops_revenue／mops_financials（公開資訊觀測站舊站）、taifex
├── config_watchlist.py    觀察名單（可多個名單組合，存 data/watchlist.json；收集、提醒、報告用所有名單的聯集）
└── storage/db.py          SQLite 全部讀寫
scripts/                   run_daily_collect.py（排程呼叫）、backfill_history.py、migrate_to_installed.py
launcher.pyw               安裝版啟動器；packaging/ 安裝程式打包；start_ui.bat 開發用啟動
```

## 資料流

```
收集：TWSE/TPEx/FinMind → stock_price / institutional / margin / valuation / month_revenue
     鉅亨網API(含全文，逐頁抓完一天約 125 則) + Google News RSS → news
        ↓
AI 新聞分析（Codex CLI，收集後自動觸發）：
     缺內文的用 Firecrawl→Playwright 補 → 逐篇摘要存 news.excerpt
     → 分批找候選 → 去重+代號校正 → 彙整挑 Top N → ai_picks / ai_analysis_summary
        ↓
個股/大盤分析（Codex CLI 按鈕，或產生提示詞手動貼到網頁版 AI 再貼回）→ stock_analysis / market_analysis
        ↓
每日報告：彙整以上全部＋觀察名單訊號（＋持股，可選）→ 頁面顯示 / 下載 .md / 產生 PDF
```

## 資料庫（`data/tw_stock.db`）

| 表 | 主鍵 | 說明 |
|---|---|---|
| `stock_price` | date+market+code | 收盤價量 |
| `institutional` | date+market+code | 三大法人買賣超 |
| `margin` | date+market+code | 融資融券 |
| `news` | id | `content`=全文、`excerpt`=AI逐篇摘要 |
| `ai_picks` | date+rank | AI 挑的當日焦點個股（檔數 `news_top_n` 可選 10／20／30／50） |
| `ai_analysis_summary` | date | 當日新聞總結 |
| `stock_analysis` | date+code | 個股分析（Codex 或手動貼回） |
| `market_analysis` | date | 大盤籌碼分析（Codex 或手動貼回） |
| `valuation` / `month_revenue` | date or year_month+market+code | 本益比等估值／月營收 |
| `trades` / `trade_reviews` | id / trade_id | 交易紀錄與 AI 覆盤（`holdings` 為舊表，已轉入 trades） |
| `app_meta` | key | 一次性遷移旗標 |
| `predictions` | id | AI 個股分析的方向與支撐壓力，事後檢驗結果 |
| `alert_rules` / `alert_events` | id | 條件提醒規則／觸發紀錄（同規則同股同日只記一次） |
| `market_index` | date | 加權指數 |
| `shareholding` | date+code+level | 集保股權分散（每週） |
| `foreign_holding` / `sbl_short` | date+code | 外資持股比例／借券賣出餘額（上市） |
| `dividend_events` | ex_date+market+code | 除權息預告 |
| `financials` | year+quarter+market+code | 季報（年初累計值，單季值由 `financials.py` 相減） |
| `futures_institutional` | date+commodity+identity | 台指期三大法人交易與未平倉口數 |
| `trading_calendar` | date+market | 補收集時記住的非交易日 |
| `collect_log` | id | 每步驟成功/失敗紀錄，debug 收集問題先看這裡 |

Schema 變更走 `db.init_db()` 裡的 `ALTER TABLE ... ADD COLUMN` + `try/except OperationalError`，
既有資料庫才能就地升級。

---

## AI 分析：Codex CLI

目前所有 AI 分析都走 **Codex CLI**（`src/codex_cli.py`），使用這台電腦已登入的帳號與額度，不需要 API Key：
- 新聞深度分析：收集後依 `data/codex_settings.json` 的 `auto_analyze_after_collect` 自動觸發（UI 與排程腳本都是）；
  排程另可開 `auto_analyze_holdings`／`auto_analyze_watchlist` 逐檔分析個股（**每檔一次 Codex 呼叫，預設關閉**，
  使用者在意額度）。設定 UI 在「AI 設定 › 每日排程」與「開始使用」第 4 步，排程時間存 `app_settings.json` 的 `daily_task_time`
- 個股／大盤：頁面上「用 Codex 分析並儲存」；也保留「產生提示詞 → 貼到網頁版 AI → 貼回儲存」的手動流程
- 以 `exec --ignore-user-config --ephemeral --sandbox read-only` 在暫存目錄執行，新聞內文中的指令一律視為資料
- 需要結構化輸出時傳 `--output-schema`（JSON Schema），光靠文字要求 JSON 會自創格式

**已停用的舊路線**（程式碼保留，UI 不再提供，不要重新接回來）：
- 本機 Ollama（`qwen2.5:7b`）：舊的預設引擎，已由 Codex 取代
- 雲端 API（Claude/GPT/Gemini）：使用者明確說「API 這條路目前已經沒有用了」；SDK 已從 requirements 移除，
  `ai_providers.py` 內延遲匯入

**提示詞字數限制**：使用者對 AI 回覆長度敏感，但不是愈短愈好——要的是「條列精簡、不要開場白廢話」。
目前實際值：個股每項 800 字內、大盤總計 1000 字內。新增分析類 prompt 時**預設就要寫明字數上限**。

---

## 開發指令

```bash
# 啟動 UI（雙擊 start_ui.bat 也可以）
.venv\Scripts\streamlit.exe run src\app.py

# 手動跑一次收集（不開 UI）
.venv\Scripts\python.exe scripts\run_daily_collect.py

# 語法檢查
.venv\Scripts\python.exe -m py_compile src\app.py

# 單元測試（stdlib unittest，每個測試用暫存 SQLite，不碰真實資料庫）
.venv\Scripts\python.exe -m unittest discover -s tests

# 補收集上市歷史（可中斷續跑；已完整日期與非交易日會跳過）
.venv\Scripts\python.exe scripts\backfill_history.py --days 180
```

## 介面規則（`src/ui.py` + `.streamlit/config.toml`）

使用者對介面美感很在意，明確提過的問題不要再犯：
- **字級要統一**：頁面標題一律 `ui.page_header()`、區塊標題一律 `ui.panel()`／`ui.section()`，
  不要直接用 `st.title` / `st.header` / `st.subheader` 或「**粗體**」當標題。側邊欄層級是
  導覽列（主要功能，字最大）> `ui.sidebar_label()` 小灰字 > 清單項目。
- **區塊要有區隔**：K 線、籌碼、基本面、新聞、AI 分析這類獨立主題，各自用 `with ui.panel(...)` 包成有邊框的面板。
- **不要放圖示**：emoji 和 Material 圖示使用者都覺得醜，導覽列與按鈕一律純文字。
- **紅漲綠跌**：顏色只從 `ui.UP_COLOR` / `ui.DOWN_COLOR` 取；表格用 `_styled_table()`、圖表用 `ui.style_chart()`。
- plotly 圖不要放圖內標題（會跟圖例黏在一起），標題交給外面的 panel。
- 表格一律過 `_styled_table()`：st.dataframe 前端對空值固定顯示「None」、不理會 Styler 的 na_rep，
  所以有缺值的數值欄位會整欄轉成格式化文字（缺值「-」），紅綠色依原始數值判斷。
- **導覽＝可摺疊的大項目＋子項目**：`app.py` 的 `_render_nav()` 自訂側邊欄（內建導覽 `position="hidden"`），
  子項目對應頁內分頁，清單在 `NAV_TABS`。頁面用 `ui.page_tabs(page_id, NAV_TABS[page_id])` 取得目前分頁，
  **只執行目前分頁的內容**（不要一頁從頭畫到尾一直往下拉）。新增區塊時放進適當分頁，或在 `NAV_TABS` 加子項目。
  側邊欄子項目用 `on_click` 切換，不要在腳本中途 `st.rerun()`（會清掉頁面上還沒畫到的輸入框狀態）。

## 安裝版（給不懂電腦的朋友，詳見 `packaging/README.md`）

- 發布：改 `src/version.py` → 合併 main → 打 `v版本號` annotated tag（訊息即 Release 說明）→ CI 自動打包測試發布
- 程式根目錄有 `.installed` 才是安裝版：資料放 `%LOCALAPPDATA%\TWStockAnalytics\data`；**`.installed` 不可進 git**
- 套件以 `requirements.lock` 為準；Streamlit 鎖次版本（自訂 CSS 依賴內部 DOM）。重產 lock 要用短路徑的 venv，
  長路徑下 Streamlit 會因 Windows 260 字元限制裝不完整且不報錯
- `launcher.pyw`（pythonw，不跳視窗）啟動伺服器；`src/desktop.py` 管背景補資料、工作排程、Codex 登入；
  `src/updater.py` 查 GitHub Releases 並驗證 SHA-256 後執行新版安裝程式
- 對使用者電腦有副作用的操作（工作排程、安裝程式測試）不要在開發機上直接跑正式名稱；測試用暫時名稱並清掉

## 分析模組（程式先算、AI 只判讀）

- `src/indicators.py` 技術指標；`src/chip_metrics.py` 籌碼延伸指標（法人連買賣天數、N日累計、
  佔成交量比、融資變化 vs 股價、券資比）。資料不足一律回 `None`，不用部分資料硬算。
- `src/backfill.py` TWSE 歷史補收集：`trading_calendar` 表記住非交易日；**今天/未來不標記**
  （可能只是尚未公布）；例外不標記（下次重試）；請求間隔 3 秒（太快會被 TWSE 封鎖）。
  每日收集最後會呼叫 `fill_recent_gaps()` 自動補近兩週缺漏。
- `src/signals.py` 事件訊號（均線排列、突破、缺口、爆量長紅黑、相對強弱、投信認養…）。
  **對整段歷史每一列算布林欄位**，選股器取最新一天、回測取過去每天，共用同一套定義。
  相對強弱是全市場排名，不要只讀部分股票來算。「選股工具」頁與每日報告的觀察名單警示都用它。
- `src/backtest.py` 訊號回測：**隔天開盤進場**（收盤後才知道訊號，當天收盤價買不到）、第 N 日收盤出場；
  只計「新出現」的訊號（持續型訊號每天算會重複計數）；附同期全市場平均當基準算超額報酬。
- `src/collectors/fundamentals.py` + `src/fundamentals.py` 本益比／殖利率／淨值比（`valuation` 表）與
  月營收（`month_revenue` 表，千元）。月營收來源只給「最新公布月份」，每天覆寫、歷史靠累積；
  虧損公司本益比存 NULL 不是 0（0 會被「本益比 ≤ N」篩選誤判成超便宜）。
- `src/portfolio.py` 我的持股：由 `trades` 交易紀錄（買／賣、稅費、進出場理由）以**平均成本法依日期重播**推算持倉與已實現損益；賣超過當時持有視為錯誤（`validate()`，UI 儲存前必擋）。舊 `holdings` 表已停用，`init_db()` 以 `app_meta` 標記只轉換一次。
  持有的股票在個股分析提示詞會多【我的持股】與「持股應對」一項——**只給續抱／減碼／停損的條件式觀察點，
  不直接下買賣指令**，決策留給使用者。持股是個人財務資料，只存本機資料庫，測試 UI 時用資料庫副本，不要寫進真實資料庫。
  每日報告預設**不含**持股（`data/report_settings.json` 的 `include_holdings`，報告頁有開關）：關閉時連個股分析裡的
  「持股應對」一項也要用 `strip_holding_section()` 移除，提示詞因此規定成本損益只能寫在「持股應對」裡。
- **法人資料混有權證與 ETF**：T86 與上櫃法人表各有上萬筆權證（自營商避險量極大）與 ETF（造市申贖）。
  全市場加總一律加 `db.STOCK_CODE_SQL`（Python 端 `db.is_stock_code()`）只算個股；查單一股票用
  `db.query_institutional_for_code()` 精確比對，`query_institutional(date, keyword)` 是模糊搜尋（查 2330 會帶出 062330 權證）。
- TPEx 法人欄位名稱要**完全比對**（`_find_value`）：子字串比對曾把外資欄位當成自營商。舊資料由 `init_db()` 以
  「自營商 = 合計 − 外資 − 投信」自動修復。
- TPEx OpenAPI 只有「最新一天」無法回補，上櫃股的歷史指標天數會比較少。

第一次設定要多跑 `playwright install chromium`（`pip install` 不會自動下載瀏覽器核心）。

**重啟 Streamlit 要用 PID 砍乾淨**：`taskkill //IM streamlit.exe` 砍不掉實際的 python 程序，
會變成多個程序同時佔用 8501，改動不生效卻又看起來「有回應」（實際是舊程序在服務）：

```bash
for pid in $(netstat -ano | grep ":8501.*LISTENING" | awk '{print $NF}' | sort -u); do
  taskkill //F //PID $pid
done
```

---

## 寫作慣例

- 註解與 UI 文字用**繁體中文**；識別字用英文 snake_case
- 私有函式前綴 `_`
- 收集器的每個步驟都要能**獨立失敗**：`collect_all.py` 的 `_run_step()` 包 try/except 寫進
  `collect_log`，單一來源掛掉不能中斷整批
- 外部服務（Codex CLI／Firecrawl／資料來源 API）呼叫一律回傳 `(ok: bool, 結果或錯誤訊息: str)`，
  把底層例外轉成使用者看得懂的訊息，不要讓例外往上竄
- 新增 API Key 類設定 → 存 `data/*.json` 並**記得加進 `.gitignore`**
