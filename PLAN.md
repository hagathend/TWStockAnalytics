# TWStockAnalytics 專案規劃

## 目標

打造一個每日自動化的台股分析系統：

1. **資料收集**：定時（每日 20:00，盤後）擷取台股各種資訊（收盤價量、三大法人買賣超、融資融券、新聞）
2. **AI 分析**：交給 AI 分析當日新聞重點、挑出需注意個股，並針對重點個股做籌碼分布 / 線型分析
3. **報表輸出**：整理成報表
4. ~~通知推播：報表透過 LINE Bot 推播~~（2026-09-16 決定不做：改用 Windows 通知＋報告下載，見第三階段「條件提醒」）

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

### ~~LINE 推播~~（已取消）

2026-09-16 使用者決定不做 LINE Bot。主動通知改由第三階段的「條件提醒＋Windows 通知」負責。

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
- [x] 可編輯觀察名單（`data/watchlist.json`，UI 可自行新增/刪除股票，側邊欄點擊可跳轉到個股詳情頁）
- [x] AI 新聞分析產生「新聞焦點 Top 20」：**改用複製貼上工作流程，不需要付費 API Key**（見下方說明），結果存入 `ai_picks` / `ai_analysis_summary` 資料表，側邊欄與「AI 分析」頁都會顯示
- [x] 個股 K 線圖：「個股詳情」頁用 plotly 畫蠟燭圖，即時向 FinMind 抓近 90 天歷史（本地資料庫本身歷史很短，累積中）
- [x] 多頁面導覽：改用 `st.navigation` + `st.Page`（總覽 / 個股詳情 / AI 分析 / AI 設定 四頁），觀察名單與 AI Top20 項目可點擊跳轉個股詳情頁
- [x] **Ollama 本機 AI 自動分析**：使用者提到自己有裝 Ollama，可以免費本機跑模型解決付費 API 的問題，因此串接上去並設為預設自動觸發（見下方說明）
- [x] **AI 深度分析（逐篇抓內文摘要）**：使用者發現 qwen2.5:7b 沒辦法自己爬網頁，只能就給定的文字做摘要，因此改成「先抓每則新聞的內文 → 逐篇AI摘要 → 彙整摘要再送一次AI選前20檔」的兩階段流程，取代原本只看標題+短摘要的做法（見下方說明）
- [x] 逐篇摘要結果存入 `news.excerpt` 欄位並顯示在「AI 分析」頁，結構化資料可作為之後報表產出的素材
- [x] **個股籌碼/未來展望分析（複製貼上流程）+ 每日報告產出**：見下方說明
- [x] **大盤整體籌碼分析（複製貼上流程）**：見下方說明
- [x] **技術指標計算 + 線型分析**：見下方說明
- [x] **上市歷史補收集 + 籌碼延伸指標 / 事件訊號選股 / 基本面 / 訊號回測**：見下方說明
- [x] ~~LINE Bot 串接，報表推播~~（取消，見上方說明）
- [ ] **第三階段：分析功能擴充**：見文件最後「第三階段規劃」

#### 歷史補收集 → 籌碼指標 → 訊號選股 → 基本面 → 回測（2026-09-14）

依序完成四個階段，每階段都先寫 unittest（`tests/`，暫存 SQLite）再用真實資料交叉驗證：

1. **歷史補收集 + 籌碼延伸指標**：本地原本只有 9 天上市資料，選股／回測都算不了。
   `src/backfill.py` 用 rwd 介面逐日回補（可續跑、`trading_calendar` 記住非交易日、間隔 3 秒），
   每日收集最後自動補近兩週缺漏。`src/chip_metrics.py` 算法人連買賣天數、5/20日累計、佔成交量比、
   融資變化 vs 股價、券資比，放進個股詳情頁與個股分析提示詞。
   驗證：2330 的 5/20 日外資累計與手寫 SQL 加總一致。
2. **事件訊號 + 選股工具頁 + 觀察名單警示**：`src/signals.py` 對整段歷史逐列計算訊號（回測共用同一套定義）。
   均線糾結門檻原訂 2%，實測全市場一半以上股票都符合、沒有篩選意義，改為 1%（約 28%）。
   每日報告自動列出觀察名單「今日新訊號／持續中訊號」。
3. **本益比／殖利率／淨值比 + 月營收**：TWSE BWIBBU_d、TPEx peratio、上市櫃月營收彙總 OpenAPI
   （已含年增／月增）。月營收來源只有最新月份，每天覆寫、歷史靠累積。
4. **訊號回測**：隔天開盤進場、第 N 日收盤出場、只計新出現訊號、附同期全市場平均當基準。
   驗證：抽一筆 2330 事件，回測報酬與手算 (第5日收盤/隔日開盤-1) 一致。
   首次結果（補完 180 天後，訊號日 2026-03-18～08-17，20 日持有）：投信認養平均超額 +2.0%、
   均線空頭排列 +1.7%；突破60日新高 −4.0%、均線多頭排列 −1.8%。只補完部分樣本時（05～09）結論還不一樣，
   可見樣本期間短時結論很不穩定，只能當參考、不能當通則。

#### 技術指標計算 + 線型分析（2026-09-06）

原本 PLAN 的目標就有「線型分析」，但先前只做了畫 K 線圖，**沒有任何技術指標**，
而且個股分析提示詞餵給 AI 的是「最近15天的原始 OHLCV 數字」，等於要 AI 瞪著原始價格用眼睛看
——LLM 這樣判讀技術面本來就不準。做法跟「先抓內文再摘要」同樣邏輯：**先用程式把指標算好，再餵給 AI 判讀**。

- `src/indicators.py`（新增）：用 pandas 計算 MA5/20/60、RSI(14, Wilder平滑)、
  MACD(12,26,9，台股慣稱 DIF/MACD/柱狀體OSC)、KD(9,3,3，K/D 初始值50逐筆遞推)、
  布林通道(20,2，母體標準差)、量能均量。純數學、無 AI，結果確定可重現。
  `summarize_for_prompt()` 把最新一筆整理成文字（只陳述數值與客觀狀態，多空結論留給 AI 判斷）
- **驗證方式**：MA5/20/60 與手算 rolling mean 逐一比對相符、RSI 與獨立寫的 Wilder 迴圈實作
  比對到小數點後6位相符、OSC == DIF-DEA、RSI/K/D 皆落在 0-100、布林上軌>中軌>下軌且中軌==MA20
- `src/charting.py`：K線圖疊上 MA5/20/60 三條均線 + 成交量副圖（紅漲綠跌）。
  **注意**：均線要算得準，抓取範圍必須比顯示範圍更長——一開始只多抓150天，
  結果顯示區間左側 18 根 K 棒的 MA60 是空的（要顯示 N 個交易日的 MA60 需要 N+59 個交易日資料），
  改成抓 `顯示天數 + 150 天` 後才完整
- `src/stock_analysis.py`：提示詞新增【技術指標】區塊，並多要求一項「技術面分析」
  （明確要求「直接引用這些數值，不要自己重新估算」），變成技術面/籌碼面/未來展望/總結四項。
  價格資料改成抓一次共用給價格表與指標計算，不重複打 FinMind
- 順手修掉一個雜訊問題：Google News RSS 的 `summary` 欄位是 HTML（含 `<a href=...>` 標籤），
  沒做過 AI 摘要的新聞會把整串 HTML 塞進提示詞，改用 BeautifulSoup 去標籤只留純文字

#### 大盤整體籌碼分析（2026-07-28）

使用者要求也要有大盤層級（不是單一個股）的籌碼分析，一樣走複製貼上流程：
- `src/market_analysis.py`：`build_market_analysis_prompt(date)` 組出提示詞，內容包含
  全市場三大法人買賣超加總（`db.query_market_institutional_summary()`）、當日漲跌家數
  （`db.query_market_breadth()`，只算 TWSE 上市，因為 TPEx 股價表混雜大量債券ETF會讓
  統計失真）、當日新聞摘要與焦點個股 Top20；要求AI回答四項（短期展望/中期展望/籌碼分析/
  目前熱門產業和股票消息），總字數原本限制500字內，使用者後來反應太少，**改為1000字內**
- `save_market_analysis()` 存進新增的 `market_analysis` 表（date, analysis, created_at）
- 放在「AI 分析」頁（不是個股層級的頁面，因為這是「當天」層級的分析，跟新聞分析同一頁比較合理）
- 「每日報告」的 `_build_report_text()` 在新聞摘要之後、個股列表之前插入這個區塊

#### 複製貼上結果換行被吃掉的問題（2026-07-28）

使用者反應個股分析/大盤分析貼回來的結果顯示時「換行都被吃掉，變成黏在一起」。根因是 Markdown 規則本身：
單一換行 `\n` 在標準 Markdown（CommonMark）裡會被當成空白字元，不會顯示成新的一行，只有連續兩個以上的
換行（分段）或是「兩個空白+換行」（強制換行）才會顯示出換行效果。AI 回覆通常是一行一個重點
（籌碼面分析/未來展望/總結各自一行），這些單一換行被 `st.write()`/`st.markdown()` 用 Markdown 規則解讀後
就全部黏在一起變成一段文字。

修法：新增 `_md_linebreaks(text)` 把文字裡的 `\n` 全部換成 `"  \n"`（兩個空白+換行，Markdown的強制換行
語法），在所有顯示 AI 回覆內容的地方套用：個股分析、大盤分析、逐篇新聞摘要的顯示，以及「每日報告」
`_build_report_text()` 組裝報告文字時（這樣網頁顯示、Markdown 下載檔、PDF 轉換都會正確換行，因為
PDF 也是先轉成 HTML 再用 Chromium 列印，同樣走 Markdown 解析規則）。

#### Firecrawl 作為 Playwright 的優先內文擷取選項（2026-09-02）

使用者問到 [Firecrawl](https://www.firecrawl.dev/)（專門的網頁擷取API服務）能不能用在這個專案。
免費額度每月1,000次、不用信用卡，跟目前每天大概只需要抓 `_MAX_RSS_FOR_DEEP`（15）篇 Google News RSS
文章的用量（鉅亨網已經有全文，不用額外抓）比起來綽綽有餘。且實測發現我們自己寫的 Playwright
「找 `<article>` 標籤、找不到就抓整個 body」heuristic 在某些網站（例如某篇 Yahoo香港財經）會抓到整個
導覽選單等雜訊，Firecrawl 作為專門服務品質通常更穩定。

- `src/collectors/firecrawl_fetcher.py`：`fetch(url, api_key)` 呼叫 `POST https://api.firecrawl.dev/v2/scrape`
  （注意是 v2 不是 v1，串接前有先查過官方文件確認目前版本），回傳 `data.markdown` 欄位；
  `test_connection(api_key)` 驗證用（會消耗1個額度，Firecrawl 沒有免費的純驗證端點）
- `src/config_ai.py` 新增 `load_scraping_settings()`/`save_scraping_settings()`，存進
  `data/scraping_settings.json`（已加進 .gitignore）
- `src/ai_analysis.py` 新增 `_fetch_missing_content()`：**優先用 Firecrawl（如果有設定Key），
  抓不到或沒設定Key的部分才退回 Playwright**，取代原本 `_gather_and_summarize()` 裡直接呼叫
  Playwright 的邏輯。兩者都失敗時優雅降級用標題代替，不會中斷整批分析
- 「AI 設定」頁新增「Firecrawl（內文擷取，選用）」區塊，可填 Key + 測試連線，留空就完全不影響
  現有行為（自動退回 Playwright）
- Playwright（`src/collectors/article_fetcher.py`）**沒有移除**，`report_pdf.py` 產生PDF還需要它，
  而且是 Firecrawl 沒設定/失敗時的免費備援

#### 個股籌碼分析 + 每日報告（2026-07-28）

個股層級的分析（籌碼面判斷、未來展望）需要比較強的推理能力，使用者認為這種任務不像新聞摘要那樣適合丟給本機小模型，因此比照新聞分析的「複製貼上」模式，而不是再接一套 Ollama/API 自動呼叫：

1. `src/stock_analysis.py`：`build_stock_analysis_prompt(code)` 組出一份提示詞，內容包含：
   - 近期股價（FinMind 即時抓，最近30天，顯示最後15筆）
   - 近期三大法人買賣超歷史（本地資料庫累積，`db.query_code_history("institutional", code)`）
   - 近期融資融券歷史（本地資料庫累積）
   - 相關新聞（新增 `db.query_news_by_keyword(keyword, days=7)`，跨最近7天用代號/名稱搜尋標題、關聯代號、逐篇摘要欄位，去重合併）
   - 要求 AI 回答三項結果：**籌碼面分析**（多空判斷）、**未來1-2週展望**、**總結**。使用者第一版反應回覆太長太分散（原本問了籌碼分析/短中長期展望共4項、每項2-3句話），改成只留3項且各自限制100字，後來又反應100字太少，**改為每項800字以內**
2. `save_stock_analysis(code, analysis_text)` 存進新增的 `stock_analysis` 資料表（date, code, name, analysis, created_at）
3. 「個股詳情」頁新增「AI 個股分析」區塊：按鈕產生提示詞（`st.code` 顯示，可複製）→ 使用者自行貼到網頁版 AI → 貼回結果 → 存檔；也會顯示當天已存的分析
4. 新增「每日報告」頁（`report_page()`，`_build_report_text()`）彙整：
   - 新聞摘要（`ai_analysis_summary` 表）
   - 今日新聞焦點個股 Top20（`ai_picks` 表），**每檔都併上當天的三大法人買賣超**（`db.query_institutional(date, code)`，這樣不用把全市場上萬筆法人資料整個塞進報告，只顯示跟報告相關的重點個股）
   - 個股深度分析（`stock_analysis` 表，只顯示當天已經產生過分析的股票）
   - 輸出成 Markdown，頁面直接渲染，也提供「下載報告」按鈕匯出 `.md` 檔
5. **PDF 匯出**：使用者不想要 Markdown 格式，希望有 PDF。做法是重複利用已經為了解析 Google News RSS
   而裝的 Playwright/Chromium（見上方「AI 深度分析」段落），不需要另外裝 wkhtmltopdf 之類的外部工具：
   `src/report_pdf.py` 的 `markdown_to_pdf()` 用 `markdown` 套件把報告文字轉成 HTML（套用簡單 CSS，
   中文字型指定 Microsoft JhengHei/PMingLiU），再用 Chromium 的「列印成PDF」功能（`page.pdf()`）輸出。
   「每日報告」頁按「產生 PDF」後才顯示下載按鈕（PDF 產生需要幾秒鐘，不在每次頁面渲染時都跑）。
   實測繁體中文、表格、分頁都正常。

#### AI 深度分析：逐篇抓內文摘要（目前預設方式，取代單次呼叫版）

使用者發現 qwen2.5:7b 速度雖快，但它沒辦法自己把網頁內容爬出來分析——只能就「已經準備好的文字」做摘要或判斷。原本 `analyze_with_ollama()` 只把新聞標題+API自帶的短摘要餵給AI，資訊量不夠。改成兩階段流程：

1. **取得每則新聞的內文**：
   - 鉅亨網 (cnyes)：API 回應本身就含全文（`content` 欄位，HTML實體跳脫過的HTML），不用額外爬，`src/collectors/news_crawler.py` 解析存進 `news.content` 欄位即可
   - Google News RSS：RSS 提供的連結是 `news.google.com` 的中介頁面，要靠 JavaScript 才會轉址到真正的新聞網站，單純用 `requests` 抓不到轉址後內容（實測直接拿到 Google 的空殼 HTML）。改用 Playwright headless 瀏覽器（`src/collectors/article_fetcher.py`）實際開啟連結讓 JS 執行、轉址完成後抓取內文，用「先找 `<article>` 標籤、找不到就退回抓整個 body」的 best-effort 方式應付不同新聞網站的頁面結構
2. **逐篇摘要**：`src/ai_analysis.py` 的 `_summarize_article()` 對每則新聞的內文呼叫一次 qwen2.5:7b（純文字輸出，非JSON schema），產出不超過100字的重點摘要
3. **彙整挑股**：把所有逐篇摘要彙整成一份新提示詞，再呼叫一次 qwen2.5:7b（用 `_PICKS_SCHEMA` 強制JSON格式）挑出前20檔重點個股

實測（2026-07-28，25篇新聞：15篇鉅亨網+10篇RSS）耗時約 90-100 秒，比原本單次呼叫（~15秒）慢很多，但分析品質好很多（有真正的新聞內文可以判斷，而不是只看標題臆測）。

- `_MAX_CNYES_FOR_DEEP`、`_MAX_RSS_FOR_DEEP`：限制篇數控制總耗時，且刻意分開限制兩種來源、各自保底，避免鉅亨網數量較多把 RSS（個股觀察名單專屬新聞）全部排擠掉
- 主函式 `analyze_with_ollama_deep(date, host, model, progress_callback)`，`progress_callback(current, total, message)` 用於 Streamlit 顯示進度條
- **收集資料按鈕**與「AI 分析」頁都改用這個深度版本（直接取代原本的快速版，非另外加一個按鈕，這是使用者的明確選擇——即使會讓收集按鈕卡上幾分鐘）
- 原本的 `analyze_with_ollama()`（只看標題快速版）保留在程式碼裡未刪除，但 UI 已經不會呼叫到它

#### 篇數增加後只挑出2~6檔的問題（2026-07-28，三處根因逐一修正）

使用者反應：把候選文章池加大（想涵蓋更多不同公司）之後，qwen2.5:7b 從53篇摘要一次彙整，反而只挑出2檔、還漂移成簡體字輸出。查證後發現「一次塞太多內容進同一個提示詞」是根本問題，且牽涉三個各自獨立的坑：

1. **單次彙整prompt太長導致模型退化**：55篇摘要塞進同一個`_DEEP_PROMPT_TEMPLATE`，qwen2.5:7b（7B參數）表現明顯變差（篇數少、語言漂移）。修法是**分批處理**：`_select_top_picks()` 篇數超過 `_BATCH_SIZE`（15）就改成先分批（每批15篇）呼叫`_BATCH_PICKS_SCHEMA`找候選個股、去重後、再用`_FINAL_RANK_PROMPT`彙整候選清單挑最終20檔——分批後每次進模型的內容都比較短，輸出品質明顯回穩（無簡體字漂移問題）。
2. **代號後綴regex只吃`.TW`不吃`-TW`**：`_normalize_picks()`的正則 `\.(TW|TWO|TPEX)$` 只處理句點分隔的後綴，AI偶爾會用`2330-TW`（連字號）格式，沒被清乾淨。改成 `[.\-](TW|TWO|TPEX)$` 同時吃兩種分隔符。
3. **兩層prompt都「先入為主篩掉太多」**：這是實測抓到最關鍵的坑——分批找候選的prompt（`_BATCH_PICKS_PROMPT`）原本要求模型自己判斷「值得投資人關注」，結果15篇摘要裡明明有5-6家公司提到具體財報數字，模型卻只挑1-3檔；即使把batch prompt改成「列出所有提到具體公司的，不要自己篩重要性」讓候選數從8→17（去重後10~12檔正確配對的候選），**最終彙整的`_FINAL_RANK_PROMPT`一樣有這個毛病**——丟給它12檔已經篩選過的乾淨候選，還是砍到只剩4~5檔。修法是把最終彙整prompt也改成「候選清單裡的每一檔原則上都要保留、只有確定同公司重複才合併，不要自己覺得不夠重要就刪」，這樣12檔候選最後能留住10檔（2317鴻海、2330台積電、2337旺宏、6827巨生醫、3017奇鋐、3324雙鴻、6184大豐電、6272驊陞、7901大大寬頻、2049上銀，代號名稱皆正確）。

**教訓**：LLM在「要求它自己判斷重要性、篩選候選」這類任務上，會系統性地過度保守（不管是7B小模型還是prompt本身寫法問題），且這個毛病可能同時出現在pipeline的多個階段，不能只改一個地方就假設整條路都通了——每個「AI 自己決定要不要保留/篩選」的環節都要個別驗證輸出數量是否合理。之後如果還想再優化，可以考慮把「候選清單」的篩選責任進一步下放（例如乾脆不篩選，讓最終清單自然依重要程度排序、由使用者自己決定要看前幾檔），減少AI主動「刪除」的環節。

**逐篇摘要結果會存起來、顯示在「AI 分析」頁**：使用者提出想看每則新聞被 AI 摘要出的重點，也希望之後能拿來當報表素材。`news` 表新增 `excerpt` 欄位（`db.save_news_excerpt()` 寫入），`analyze_with_ollama_deep()` 回傳值也帶上 `article_excerpts` 清單（title/url/source/excerpt）。「AI 分析」頁的 `_render_article_excerpts()` 優先顯示這次剛跑完、還在 `st.session_state` 裡的結果，沒有的話就用 `db.query_news_excerpts(date)` 撈上次分析留下的紀錄——這樣即使重新整理頁面或換過日期，先前分析過的逐篇摘要仍然看得到，也已經是結構化資料（date/source/title/url/excerpt），可以直接餵給之後的報表產出功能。

#### 雲端 API 深度分析（Gemini 免費額度 / Claude·GPT 付費，作為 Ollama 的替代選項）

使用者發現 Gemini 有提供真正免費的 API 額度（不用綁信用卡，去 Google AI Studio 申請即可），問能不能把「自己爬網頁文字 + 交給 Gemini 分析」這種用法接進來。因為我們已經有「抓內文→逐篇摘要→彙整挑股」這一整套（原本是 Ollama 專用），所以把共用邏輯抽出來，讓 Gemini/Claude/GPT 都能重用同一套流程：

- `src/ai_analysis.py` 新增 `_gather_and_summarize(date, summarize_fn, progress_callback, inter_call_delay)`：原本 `analyze_with_ollama_deep()` 裡「抓內文＋逐篇摘要＋存excerpt」的邏輯抽出來共用，只有 `summarize_fn`（實際呼叫哪家AI）跟供應商相關
- 新增 `analyze_deep_with_provider(date, provider, api_key, progress_callback)`：跟 Ollama 版走同一套流程，差別是呼叫 `src/ai_providers.py` 的 `generate_text()`（Gemini/Claude/GPT 共用的付費/免費API呼叫函式），且沒有 Ollama 的 structured output，最終JSON用既有的 `_extract_json()` 容錯解析
- 雲端 API 沒有速率限制的保護機制，逐篇呼叫之間加了 2 秒間隔（`_PAID_API_INTER_CALL_DELAY`）降低碰到免費額度請求頻率限制的機會
- Gemini 模型最後定案用 `gemini-flash-latest`（別名，永遠指向目前可用的最新flash模型）。中間繞了一圈：一開始照使用者提供的範例改成 `gemini-2.5-flash`，`test_connection()`（呼叫 `models.list()`）也確實列得出這個型號，但實際呼叫 `generate_content()` 卻回 404「This model models/gemini-2.5-flash is no longer available to new users」——**models.list() 列得出來，不代表這個帳號真的能呼叫它**，這是個容易誤判的陷阱。改用 `-latest` 別名（而非寫死特定日期快照）解決，這樣以後 Google 汰換掉某個快照版本也不會突然壞掉
- 「AI 分析」頁新增「0b. 用雲端 API 深度分析」區塊，可選 Claude/GPT/Gemini（用 radio 切換），沒填 Key 會提示去「AI 設定」頁填；原本底部「進階：直接呼叫付費API」的舊版淺層 quick-call 已移除，被這個更準確的深度版取代
- 這是使用者自己的真實 Gemini Key 實測過的（`test_connection` confirmed 連線成功，看得到 gemini-2.5-flash/2.5-pro/2.0-flash 等可用模型）

Ollama 仍是預設自動觸發的選項（免費、本機、不需要任何帳號），雲端 API 版是使用者自己選用的替代方案，不影響預設行為。

#### Ollama 本機自動分析（目前預設方式）

使用者提出自己電腦有裝 Ollama，可以解決 AI 分析要付費的問題。實測比較了使用者已安裝的幾個模型（用真實新聞資料跑同一個任務）：

| 模型 | 耗時 | 結果 |
|---|---|---|
| **qwen2.5:7b** | ~15秒 | 格式正確、代號/名稱最乾淨、繁中推理清楚 |
| qwen3.6 (36B MoE) | ~140秒 | 可用但代號常帶 `.TW` 尾巴，且慢約10倍 |
| gemma4-12b-it-oym | ~25秒 | 代號和名稱常會對不起來、混用英文推理 |
| 其他 RPG/Uncensored 微調版本 | - | 不建議，這類角色扮演微調對結構化任務不可靠 |

因此預設模型選 `qwen2.5:7b`，並改用 Ollama 的 **structured output**（`format` 參數傳入 JSON Schema 強制格式，而非單純提示詞要求輸出JSON）大幅提高格式可靠度——同一個模型光靠文字提示會自創格式，加上 schema 後就完全正確。

實作：
- `src/ai_providers.py`：`list_ollama_models()` 列出本機已安裝模型、`generate_ollama_json()` 用 schema 強制格式呼叫
- `src/ai_analysis.py`：`analyze_with_ollama()` 產生提示詞 → 呼叫 Ollama → 解析存入資料庫
- `src/config_ai.py`：`load_ollama_settings()`/`save_ollama_settings()` 讀寫 `data/ollama_settings.json`（host、model、是否收集後自動分析，預設開啟）
- 「AI 設定」頁新增 Ollama 區塊（連線測試+列出模型下拉選單），「AI 分析」頁把 Ollama 選項放在最上面（推薦選項）
- 收集資料按鈕：若 Ollama 自動分析設定開啟（預設開），收集完會自動呼叫 Ollama 分析，不需要手動複製貼上

**已知限制與修正**：AI（不只 Ollama，各家LLM都可能）偶爾會記錯「代號」和「名稱」的對應（實測发现例如把 2454 聯發科講成 2357，把台達電講成不存在的 6700），這是模型自己記憶推測代號造成的幻覺。修法是在 `src/ai_analysis.py` 的 `_verify_pick()` 用本地資料庫（官方 TWSE/TPEx 收集來的正確代號/名稱對照表）校正：新聞文字通常用公司名稱而非代號，相對可信，所以代號和名稱對不上時，改用名稱回頭查詢正確代號。

複製貼上流程（`build_prompt` + `parse_and_save`）與付費 API 直接呼叫（`generate_text`）仍保留作為沒有裝 Ollama 時的備援選項。

#### 複製貼上流程說明（Ollama 之外的備援選項）

一開始設計是收集完資料後自動呼叫使用者在「AI 設定」頁存的 Claude/GPT/Gemini API Key 做分析。
但使用者提出：Claude Pro / ChatGPT Plus / Gemini 訂閱的網頁版聊天**不能**當 API Key 用，
API 是另外的用量計費、需要在 Anthropic Console / OpenAI Platform / Google AI Studio 個別申請並綁定帳單，
使用者一開始並不知道要另外付費，因此改成預設走「複製貼上」流程，不強制產生費用：

1. 「AI 分析」頁按「產生新聞分析提示詞」，把當天新聞整理成一份提示詞（`st.code` 顯示，右上角有複製按鈕）
2. 使用者自行複製貼到平常在用的網頁版 Claude / ChatGPT / Gemini
3. 把 AI 的回覆貼回「AI 分析」頁的文字框，按「解析並儲存」，程式會解析裡面的 JSON 存入資料庫

`src/ai_providers.py` 仍保留真正呼叫付費 API 的 `generate_text()`，在「AI 分析」頁的「進階：直接呼叫付費 API」摺疊區塊可用（需先在「AI 設定」頁填好 Key），給願意付費、想要全自動的人使用。
收集資料按鈕本身**不會**自動觸發任何 AI 呼叫（不論免費或付費），只會自動產生好提示詞放著讓使用者去複製。

#### 實測時發現並修正的問題

- **TWSE/TPEx 資料被存成不同日期，導致「股價總覽」看起來少了一大半股票（第一次修法，事後證實是錯的）**：一開始發現 TWSE/TPEx 各自信任 API 內嵌的交易日期時會不同步，於是把收集器改成統一用「收集當下的日期」覆蓋掉 API 回傳的日期。**這個做法後來被證實是錯的**：使用者拿奇亨網股價比對京元電子(2449)發現對不起來，查證後發現 `openapi.twse.com.tw` 的 `STOCK_DAY_ALL`／`MI_MARGN` 端點本身會延遲公布當天資料（同一時間點，TWSE 舊版 `rwd` 查詢介面已經是當天收盤價，`openapi` 卻還停留在前一個交易日），我們卻把這筆「其實是三天前」的資料強制蓋上「今天」的日期標籤，等於是造假日期、把舊資料偽裝成當天最新收盤價。**正確修法**：改用 TWSE 舊版 `rwd` 介面（可指定 `date` 參數、回應內會確認實際日期）取代 `openapi.twse.com.tw`：
  - 股價改用「每日收盤行情」`https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`（`type=ALLBUT0999` 排除權證/牛熊證）
  - 融資融券改用 `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN`（原本 openapi 版本完全沒有日期欄位，無從得知資料屬於哪一天）
  - TPEx 各收集器則改回信任 API 回傳的實際交易日期，不再覆蓋成收集當下日期
  - 教訓：政府開放資料 API 沒有明確標示的「最新一筆」不能假設一定是「今天」，寧可用資料本身標示的日期（可能因此跟其他市場的日期不同步），也不要為了畫面好看而覆蓋成錯誤的日期
- **TPEx OpenAPI SSL 憑證問題**：`www.tpex.org.tw` 憑證鏈缺少 Subject Key Identifier 擴充欄位，Python 3.13 (OpenSSL 3.2+) 預設嚴格模式會拒絕連線。已在 `src/collectors/twse_official.py` 加上專用的 `_TpexSSLAdapter`，僅關閉 `X509_V_FLAG_X509_STRICT` 這一項嚴格檢查，憑證鏈驗證與主機名稱檢查仍正常執行（此變更已徵得使用者同意）。
- **Google News RSS 查詢字串未編碼**：股票代號+名稱組成查詢字串時含空白，未做 URL encode 導致請求失敗，已改用 `urllib.parse.quote`。
- **TWSE 三大法人買賣超 (T86) 資料量看似異常龐大（上萬筆）**：經確認為正常現象——`selectType=ALL` 會回傳當日所有上市「證券」（含權證、ETF 等衍生商品）的法人買賣超，數量遠多於普通股票數量。若之後只想看一般股票，可在查詢時依代碼長度/規則過濾。
- **Streamlit `use_container_width` 參數已過期**：改用新版 `width="stretch"`。

## 如何啟動

第一次設定：

```bash
cd TWStockAnalytics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

（`playwright install chromium` 是額外的一次性步驟，會下載一個 headless 瀏覽器核心，供 AI 深度分析解析 Google News RSS 的連結用，`pip install` 本身不會自動下載瀏覽器）

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

## 目錄結構

```
TWStockAnalytics/
├── PLAN.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── start_ui.bat               # 雙擊即啟動 UI（不用打指令）
├── data/                      # SQLite db / ai_settings.json / watchlist.json 存放處
├── src/
│   ├── config.py              # 讀取 .env 設定（TWSE/FinMind token、預設觀察名單種子等）
│   ├── config_ai.py           # AI 供應商設定讀寫 (data/ai_settings.json)
│   ├── config_watchlist.py    # 使用者自訂觀察名單讀寫 (data/watchlist.json)
│   ├── ai_providers.py        # Ollama/Claude/GPT/Gemini 呼叫（連線測試+文字生成+structured output）
│   ├── ai_analysis.py         # AI新聞分析：深度版(逐篇摘要)/快速版/複製貼上解析，皆共用
│   ├── stock_analysis.py      # 個股籌碼分析提示詞產生 + 複製貼上結果儲存
│   ├── market_analysis.py     # 大盤整體籌碼分析提示詞產生 + 複製貼上結果儲存
│   ├── report_pdf.py          # 報告Markdown轉PDF (複用Playwright/Chromium)
│   ├── indicators.py          # 技術指標計算 (MA/RSI/MACD/KD/布林/量能，純pandas)
│   ├── charting.py            # 個股K線圖+均線+成交量副圖 (plotly + FinMind 即時歷史)
│   ├── collect_all.py         # 每日收集流程整合
│   ├── collectors/
│   │   ├── twse_official.py   # TWSE/TPEx 官方 OpenAPI + rwd介面
│   │   ├── finmind.py         # FinMind API
│   │   ├── news_crawler.py    # 鉅亨網 API（含全文content欄位）
│   │   ├── news_rss.py        # Google News RSS（個股延伸新聞）
│   │   ├── article_fetcher.py # Playwright headless瀏覽器，解析RSS連結的JS轉址取得全文(備援)
│   │   └── firecrawl_fetcher.py # Firecrawl API擷取文章全文(優先選項，免費額度1000次/月)
│   ├── storage/
│   │   └── db.py              # SQLite 讀寫
│   └── app.py                 # Streamlit 入口（總覽/個股詳情/AI分析/每日報告/AI設定 五頁）
└── scripts/
    ├── run_daily_collect.py   # 給排程器呼叫的每日收集流程
    └── run_daily_collect.bat  # 給 Windows 工作排程器呼叫
```

## 待確認事項（先記錄，之後再確認）

- FinMind 是否要申請付費/註冊帳號拿 token（免費額度有限流量限制，暫先用未登入額度開發）
- 鉅亨網等網站的頁面結構若改版，爬蟲需要維護；後續可考慮加上例外容錯與告警

---

## 第三階段規劃：分析功能擴充（2026-09-16）

參考 CMoney 籌碼 K 線、XQ 全球贏家、財報狗、Goodinfo、TradingView、Finviz 等軟體，挑出「資料免費可得、適合盤後分析、
不懂電腦的使用者也看得懂」的功能。使用者要求：**依序全部實作，每做完一個就測試並提交，中間不詢問**。

### 共同原則

- **程式先算、AI 只判讀**：新指標都由程式計算，需要時再放進個股／大盤提示詞（寫明字數上限）
- **收集步驟獨立失敗**：新資料來源一律走 `collect_all._run_step()`；能指定日期的來源加入可續跑的歷史回補
- **不硬算**：資料不足回 None 並在畫面標示；只有「最新一期」的來源（集保、季報、期貨）靠每期累積，畫面寫明累積起點
- **介面規則**：`ui.panel` 分區、字級統一、不放圖示、紅漲綠跌（見 CLAUDE.md）
- **測試**：每個功能都要有單元測試（暫存 SQLite），UI 用 AppTest；有外部資料的先用真實資料驗證格式與數字；
  不寫入使用者真實的持股／觀察名單，測試用的工作排程用臨時名稱並清除

### 資料來源實測結果（2026-09-16）

| 資料 | 來源 | 可指定日期／回補 | 備註 |
|---|---|---|---|
| 集保股權分散表 | `opendata.tdcc.com.tw/getOD.ashx?id=1-5`（CSV） | 否，只有最新一週 | 約 6.9 萬列；分級 1–15＋差異調整＋合計 |
| 外資持股比例 | TWSE `rwd/zh/fund/MI_QFIIS?date=&selectType=ALLBUT0999` | 可 | 含發行股數、外資持股比率 |
| 借券賣出餘額 | TWSE `rwd/zh/marginTrading/TWT93U?date=` | 可 | 後半欄位為借券賣出（前日餘額／賣出／還券／調整／當日餘額） |
| 除權息預告 | TWSE `rwd/zh/exRight/TWT48U` | 否（未來排程） | 除權息日、現金股利、配股率 |
| 加權指數 | TWSE `rwd/zh/afterTrading/FMTQIK?date=YYYYMM01` | 可，一個月一次請求 | 每日成交值與加權指數 |
| 季報損益／營益分析／資產負債 | TWSE OpenAPI `t187ap06_L_ci`／`t187ap17_L`／`t187ap07_L_ci`（上櫃有對應 `mopsfin_*`） | 否，只有最新一季（115Q2） | 毛利率、營益率已算好；ROE 由稅後淨利／權益計算 |
| 期貨三大法人 | TAIFEX OpenAPI `MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate` | 否，只有最新一天 | 台指期多空未平倉口數與金額 |
| 歷史本益比 | TWSE `BWIBBU_d?date=`（已在收集） | 可 | 河流圖用 |

### 實作順序與設計

**A. 使用者指定順序**

1. ✅ **AI 預測追蹤**
   - 個股分析最後輸出固定格式「預測摘要」→ `predictions` 表；即時計算第 5／10 交易日報酬、同期上市個股平均、支撐壓力、命中率
   - AI 分析頁「AI 預測追蹤」面板（命中率、各方向平均報酬與超額報酬、預測清單）；個股詳情顯示這檔的歷史預測
   - 上櫃股中間缺資料時仍依第 10 日收盤判定方向，但不判斷支撐壓力（避免漏看高低點而誤判）
   - 既有的舊分析沒有預測摘要，追蹤從之後的新分析開始累積
2. ✅ **產業熱力圖**
   - 月營收的「產業別」＋當日股價；方塊大小＝成交值、顏色＝漲跌幅（紅漲綠跌，±7% 飽和）；上市／上櫃／全部切換
   - 產業彙總表：平均漲跌、上漲家數比例、成交值占比；放在市場總覽
   - 上櫃「金融業」併入上市「金融保險業」；方塊文字固定白色（plotly 自動配色在紅底會選淡粉紅看不清）
3. ✅ **條件提醒＋Windows 通知**
   - `alert_rules`：到價（高於／低於）、單日漲跌幅、持股報酬率（跌破停損／達到停利）、觀察名單出現指定訊號
   - 每日收集完自動檢查 → `alert_events` 紀錄 → Windows 通知（PowerShell 呼叫 WinRT Toast，不需額外套件）
   - 新頁面「條件提醒」：新增／停用／刪除規則、「為所有持股加上停損提醒」快速設定、最近觸發紀錄、立即檢查
   - 通知借用 Windows PowerShell 的 AUMID 顯示，腳本以 -EncodedCommand 傳入避免中文與引號被轉義；單日漲跌類規則在個股價格日期落後時不觸發
4. ✅ **千張大戶持股**
   - 每日收集時抓集保最新一週（同週重複抓會覆蓋）→ `shareholding` 表
   - 指標：千張以上大戶比例、400 張以上比例、50 張以下散戶比例、總股東人數與週變化
   - 個股詳情卡片＋週趨勢圖、選股條件（大戶比例週增）、個股提示詞
   - 只存個股（約 1,900 檔 × 16 列／週）；歷史從 2026-09-11 那週開始累積，第二週起才有週變化與趨勢圖
5. ✅ **賣出紀錄＋交易日誌＋AI 覆盤**
   - `trades` 表（買／賣、股數、價格、手續費、證交稅、進出場理由）；既有 `holdings` 自動轉成買進紀錄
   - 持倉改由交易紀錄推算（平均成本法）；已實現損益（本年／累計）；手續費依折扣自動試算，可手動修改
   - AI 覆盤：賣出時的買賣理由、持有期間價格與籌碼變化 → Codex 產出檢討（800 字內，不給買賣建議）
   - 手續費成本併入持倉成本；賣到 0 股後再買視為新的一段持有；實測舊 holdings 5 檔轉換後股數與成本完全一致

**B. 追加項目**（先做不需要新資料的，再做共用資料基礎，最後做需要大量回補的）

6. ✅ **市場溫度計**：創 20／60 日新高與新低家數、漲跌家數比、成交值變化；市場總覽卡片＋近期趨勢；放進大盤提示詞
7. ✅ **營收創新高訊號＋月營收趨勢圖**：營收創 12 個月新高、年增率連續成長月數 → 選股條件；個股詳情月營收圖。歷史改由公開資訊觀測站舊站（mopsov）月營收彙總靜態頁回補 24 個月（上市櫃×國內／KY，約 3 分鐘），併入 `backfill_history.py` 與「開始使用」的歷史資料下載
8. ✅ **加權指數歷史＋相對強弱線**：FMTQIK 回補與每日收集 → `market_index` 表；個股詳情「個股／加權指數」相對強弱線；溫度計顯示指數
9. **外資持股比例趨勢**：MI_QFIIS 每日收集＋回補 → 個股詳情趨勢、選股條件（外資持股比例 N 日增加）、提示詞
10. **借券賣出餘額**：TWT93U 每日收集＋回補 → 個股詳情趨勢、籌碼指標與提示詞（借券賣出增加是潛在賣壓）
11. **除權息與事件行事曆**：TWT48U 除權息預告＋月營收公布期限（每月 10 日）＋持股相關事件；新頁面「行事曆」，持股與觀察名單優先顯示；報告列出近期事件
12. **K 線支撐壓力＋成交量密集區**：近期轉折高低點聚類成支撐壓力、價量分布（Volume Profile）；畫在 K 線圖上並放進個股提示詞
13. **季度 EPS／毛利率／ROE**：OpenAPI 最新一季每日檢查、換季時累積 → `financials` 表；個股詳情季度趨勢；提示詞基本面段落
14. **本益比河流圖**：回補歷史 BWIBBU_d；以「股價／本益比」推算 EPS，畫出歷史本益比分位數（10／25／50／75／90%）對應的價格帶
15. **期貨三大法人未平倉**：每日收集台指期三大法人多空未平倉 → `futures_institutional` 表；市場總覽外資期貨淨部位與趨勢；大盤提示詞

每完成一項更新本節的勾選狀態與實作筆記。
