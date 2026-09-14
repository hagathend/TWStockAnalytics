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
├── app.py                    (738) Streamlit 入口，五頁導覽
├── ai_analysis.py            (517) 新聞深度分析：抓內文→逐篇摘要→分批挑股
├── stock_analysis.py         (126) 個股籌碼分析提示詞（複製貼上流程）
├── market_analysis.py         (85) 大盤整體籌碼分析提示詞（複製貼上流程）
├── ai_providers.py           (184) Ollama / Claude / GPT / Gemini 呼叫封裝
├── charting.py                (47) 個股 K 線圖（plotly + FinMind）
├── report_pdf.py              (53) 報告 Markdown → PDF（複用 Playwright）
├── collect_all.py             (82) 每日收集流程整合
├── config.py / config_ai.py / config_watchlist.py    設定讀寫
├── collectors/
│   ├── twse_official.py      (276) TWSE rwd 介面 + TPEx OpenAPI
│   ├── finmind.py             (44) FinMind API（K線歷史、交叉驗證）
│   ├── news_crawler.py        (78) 鉅亨網 API（回應本身就含全文）
│   ├── news_rss.py            (48) Google News RSS（個股延伸新聞）
│   ├── firecrawl_fetcher.py   (53) Firecrawl 擷取內文（優先，選用）
│   └── article_fetcher.py     (49) Playwright 擷取內文（備援，免費）
└── storage/db.py             (433) SQLite 全部讀寫
scripts/run_daily_collect.py         給 Windows 工作排程器呼叫
start_ui.bat                         雙擊啟動 UI
```

## 資料流

```
收集：TWSE/TPEx/FinMind → stock_price / institutional / margin
     鉅亨網API(含全文) + Google News RSS → news
        ↓
AI 新聞分析（Ollama 自動觸發）：
     缺內文的用 Firecrawl→Playwright 補 → 逐篇摘要存 news.excerpt
     → 分批找候選 → 去重+代號校正 → 彙整挑 Top20 → ai_picks / ai_analysis_summary
        ↓
個股/大盤分析（複製貼上）：產生提示詞 → 使用者貼到網頁版AI → 貼回存檔
     → stock_analysis / market_analysis
        ↓
每日報告：彙整以上全部 → 頁面顯示 / 下載 .md / 產生 PDF
```

## 資料庫（`data/tw_stock.db`）

| 表 | 主鍵 | 說明 |
|---|---|---|
| `stock_price` | date+market+code | 收盤價量 |
| `institutional` | date+market+code | 三大法人買賣超 |
| `margin` | date+market+code | 融資融券 |
| `news` | id | `content`=全文、`excerpt`=AI逐篇摘要 |
| `ai_picks` | date+rank | AI 挑的當日焦點個股 Top20 |
| `ai_analysis_summary` | date | 當日新聞總結 |
| `stock_analysis` | date+code | 個股籌碼分析（複製貼上存的） |
| `market_analysis` | date | 大盤籌碼分析（複製貼上存的） |
| `collect_log` | id | 每步驟成功/失敗紀錄，debug 收集問題先看這裡 |

Schema 變更走 `db.init_db()` 裡的 `ALTER TABLE ... ADD COLUMN` + `try/except OperationalError`，
既有資料庫才能就地升級。

---

## AI 分析的三條路（重要：使用者實際只用 Ollama）

1. **本機 Ollama（預設、實際在用）** — 免費、無次數限制，收集資料後自動觸發。
   預設模型 `qwen2.5:7b`（實測比同機 36B MoE 快十倍、格式最乾淨）。
   關鍵技巧：用 **structured output**（`/api/generate` 的 `format` 傳 JSON Schema），
   光靠文字提示要求輸出 JSON 會自創格式。
2. **複製貼上** — 個股分析、大盤分析走這條（判斷力需求高，網頁版大模型效果較好）。
3. **雲端 API（Claude/GPT/Gemini）** — 程式碼保留但**使用者明確說「API 這條路目前已經沒有用了」**。
   Gemini 免費額度是**每模型每天 20 次**，深度分析一次就要 25+ 次呼叫，天生不合。
   另注意：`models.list()` 列得出來的型號**不代表你的帳號叫得動**（`gemini-2.5-flash` 會回 404
   "no longer available to new users"），所以固定用 `-latest` 別名。

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

## 分析模組（程式先算、AI 只判讀）

- `src/indicators.py` 技術指標；`src/chip_metrics.py` 籌碼延伸指標（法人連買賣天數、N日累計、
  佔成交量比、融資變化 vs 股價、券資比）。資料不足一律回 `None`，不用部分資料硬算。
- `src/backfill.py` TWSE 歷史補收集：`trading_calendar` 表記住非交易日；**今天/未來不標記**
  （可能只是尚未公布）；例外不標記（下次重試）；請求間隔 3 秒（太快會被 TWSE 封鎖）。
  每日收集最後會呼叫 `fill_recent_gaps()` 自動補近兩週缺漏。
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
- 外部服務（Firecrawl/Ollama/各家 API）呼叫一律回傳 `(ok: bool, 結果或錯誤訊息: str)`，
  把底層例外轉成使用者看得懂的訊息，不要讓例外往上竄
- 新增 API Key 類設定 → 存 `data/*.json` 並**記得加進 `.gitignore`**


## developCodexCLI 分支更新

目前預設分析引擎改為 Codex CLI，不再由 UI 呼叫 Ollama。
`src/codex_cli.py` 封裝非互動呼叫、登入檢查、JSON Schema、逾時與錯誤處理。
新聞沿用擷取內文→逐篇摘要→挑選焦點個股；UI 收集與排程腳本都依 Codex 設定自動觸發。
個股／大盤提供直接分析並儲存按鈕，沿用原本提示詞、資料表與報告。
設定存在 `data/codex_settings.json`（不提交），使用 Codex 已登入帳號及其額度。
