# TWStockAnalytics 專案規劃

## 目標

打造一個每日自動化的台股分析系統：

1. **資料收集**：定時（每日 20:00，盤後）擷取台股各種資訊（收盤價量、三大法人買賣超、融資融券、新聞）
2. **AI 分析**：交給 AI 分析當日新聞重點、挑出需注意個股，並針對重點個股做籌碼分布 / 線型分析
3. **報表輸出**：整理成報表
4. **通知推播**（第二階段）：報表透過 LINE Bot 推播給使用者

## 技術棧

- 語言：Python 3.13
- 第一階段 UI：Streamlit（網頁介面，方便之後擴充 AI 分析頁與報表頁）
- 儲存：SQLite（本地檔案資料庫，依日期/股票代碼查詢）
- 排程：Windows 工作排程器呼叫獨立 script（`scripts/run_daily_collect.py`），UI 上也提供手動觸發按鈕

## 資料來源決策

### 股票資訊：官方 OpenAPI + FinMind 雙軌

- **TWSE OpenAPI**（上市，免費，無需 key）：`https://openapi.twse.com.tw/`
  - 每日收盤價量（STOCK_DAY_ALL）
  - 三大法人買賣超（T86）
  - 融資融券（MI_MARGN）
- **TPEx OpenAPI**（上櫃，免費，無需 key）：`https://www.tpex.org.tw/openapi/`
  - 對應上櫃股票的價量 / 法人 / 融資融券資料
- **FinMind API**（`https://api.finmindtrade.com/api/v4/data`，免費額度 + 可申請 token 提高限額）
  - 作為官方資料的交叉驗證與補充（欄位較乾淨、historical 查詢方便）
  - 之後也可用於個股基本面 / 財報等擴充

> 官方 OpenAPI 為主要來源、即時性最好；FinMind 作為備援與交叉比對，避免官方 API 異動或流量限制時收集中斷。

### 新聞：網站爬蟲 + RSS 雙軌

- **特定財經新聞網站爬蟲**：鉅亨網 (cnyes) 台股新聞列表，用 requests + BeautifulSoup 擷取當日新聞標題/摘要/連結
- **Google News RSS**：`https://news.google.com/rss/search?q=...`，免 API key，用於針對新聞中提到的個股代碼/名稱做延伸搜尋

> 兩者互補：網站爬蟲抓「當天台股大盤新聞總覽」，RSS 用於「特定個股」的新聞延伸查詢。

### AI 分析（第二階段預留）

- 提供登入/設定介面，讓使用者選擇要用的 AI 供應商：Claude / GPT / Gemini
- 使用者自行輸入各家 API Key（存在本地 `.env` 或加密設定檔，不寫入 git）
- 分析內容：
  - 當日新聞摘要 + 重點個股列表
  - 針對重點個股的籌碼分布（三大法人買賣超、融資融券趨勢）+ 線型分析（技術指標判讀）

### LINE 推播（第二階段）

- LINE Bot：將每日報表整理後推播給使用者
- 需要 LINE Developers 申請 Channel / Token（屆時再設定）

## 階段劃分

### 第一階段（本次實作範圍）— 資料收集 + UI

- [x] PLAN.md 建立
- [x] Python 專案骨架（requirements.txt / .env.example / .gitignore / src 目錄）
- [x] TWSE/TPEx OpenAPI 收集器（價量、法人買賣超、融資融券）
- [x] FinMind 收集器（交叉比對／補充）
- [x] 新聞收集器（鉅亨網 API + Google News RSS）
- [x] SQLite 儲存層（依日期/股票代碼查詢）
- [x] Streamlit UI：手動觸發收集、瀏覽當日資料、依股票代碼查詢
- [x] 每日 20:00 排程執行腳本（供 Windows 工作排程器呼叫）
- [x] 安裝依賴、實際執行驗證（已跑通全部來源，資料成功寫入 SQLite）
- [x] 一鍵啟動 `start_ui.bat`（雙擊即開啟 UI，不需手動下指令）

### 第二階段 — 進行中

- [x] AI 供應商登入/設定介面（Streamlit「AI 設定」頁籤：選擇 Claude/GPT/Gemini、輸入並儲存各家 API Key 至 `data/ai_settings.json`、測試連線按鈕）
- [ ] AI 新聞摘要 + 重點個股挑選（尚未接上真正的分析邏輯，目前設定頁只做登入/連線測試）
- [ ] 重點個股籌碼分布 + 線型技術分析（AI 輔助判讀）
- [ ] 報表產出（Markdown / HTML / PDF）
- [ ] LINE Bot 串接，報表推播

#### 實測時發現並修正的問題

- **TPEx OpenAPI SSL 憑證問題**：`www.tpex.org.tw` 憑證鏈缺少 Subject Key Identifier 擴充欄位，Python 3.13 (OpenSSL 3.2+) 預設嚴格模式會拒絕連線。已在 `src/collectors/twse_official.py` 加上專用的 `_TpexSSLAdapter`，僅關閉 `X509_V_FLAG_X509_STRICT` 這一項嚴格檢查，憑證鏈驗證與主機名稱檢查仍正常執行（此變更已徵得使用者同意）。
- **Google News RSS 查詢字串未編碼**：股票代號+名稱組成查詢字串時含空白，未做 URL encode 導致請求失敗，已改用 `urllib.parse.quote`。
- **TWSE 三大法人買賣超 (T86) 資料量看似異常龐大（上萬筆）**：經確認為正常現象——`selectType=ALL` 會回傳當日所有上市「證券」（含權證、ETF 等衍生商品）的法人買賣超，數量遠多於普通股票數量。若之後只想看一般股票，可在查詢時依代碼長度/規則過濾。

## 如何啟動

第一次設定：

```bash
cd TWStockAnalytics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

日常使用：直接雙擊專案根目錄的 `start_ui.bat` 即可啟動 UI（會自動開啟瀏覽器 http://localhost:8501），不需要每次手動打指令。

也可手動執行：

```bash
# 手動執行一次收集（不開UI）
.venv\Scripts\python.exe scripts\run_daily_collect.py

# 啟動網頁 UI
.venv\Scripts\streamlit.exe run src\app.py
```

UI 啟動後開啟瀏覽器 http://localhost:8501，左側可手動點擊「立即收集今日資料」，或直接瀏覽已收集的資料。

### 設定每日 20:00 自動執行（Windows 工作排程器）

`scripts\run_daily_collect.bat` 已寫好可直接註冊。使用者可自行在「工作排程器」建立每日 20:00 觸發、動作指向該 .bat 的工作，或用系統管理員權限執行（此步驟涉及系統設定變更，故不由 AI 自動建立，需使用者自行操作或明確授權後代為執行）：

```powershell
schtasks /Create /TN "TWStock_DailyCollect" /TR "D:\workspace\TWStockAnalytics\scripts\run_daily_collect.bat" /SC DAILY /ST 20:00
```

## 目錄結構（第一階段）

```
TWStockAnalytics/
├── PLAN.md
├── requirements.txt
├── .env.example
├── .gitignore
├── start_ui.bat               # 雙擊即啟動 UI（不用打指令）
├── data/                      # SQLite db / ai_settings.json 存放處
├── src/
│   ├── config.py              # 讀取 .env 設定（TWSE/FinMind token 等）
│   ├── config_ai.py           # AI 供應商設定讀寫 (data/ai_settings.json)
│   ├── ai_providers.py        # Claude/GPT/Gemini 連線測試
│   ├── collect_all.py         # 每日收集流程整合
│   ├── collectors/
│   │   ├── twse_official.py   # TWSE/TPEx 官方 OpenAPI
│   │   ├── finmind.py         # FinMind API
│   │   ├── news_crawler.py    # 鉅亨網 API
│   │   └── news_rss.py        # Google News RSS
│   ├── storage/
│   │   └── db.py              # SQLite 讀寫
│   └── app.py                 # Streamlit 入口（含「AI 設定」頁籤）
└── scripts/
    ├── run_daily_collect.py   # 給排程器呼叫的每日收集流程
    └── run_daily_collect.bat  # 給 Windows 工作排程器呼叫
```

## 待確認事項（先記錄，之後再確認）

- FinMind 是否要申請付費/註冊帳號拿 token（免費額度有限流量限制，暫先用未登入額度開發）
- 鉅亨網等網站的頁面結構若改版，爬蟲需要維護；後續可考慮加上例外容錯與告警
- LINE Bot 的 Channel 申請與 Webhook 部署方式，留待第二階段確認
