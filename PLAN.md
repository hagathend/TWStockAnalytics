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
- [x] 可編輯觀察名單（`data/watchlist.json`，UI 可自行新增/刪除股票，側邊欄點擊可跳轉到個股詳情頁）
- [x] AI 新聞分析產生「新聞焦點 Top 20」：**改用複製貼上工作流程，不需要付費 API Key**（見下方說明），結果存入 `ai_picks` / `ai_analysis_summary` 資料表，側邊欄與「AI 分析」頁都會顯示
- [x] 個股 K 線圖：「個股詳情」頁用 plotly 畫蠟燭圖，即時向 FinMind 抓近 90 天歷史（本地資料庫本身歷史很短，累積中）
- [x] 多頁面導覽：改用 `st.navigation` + `st.Page`（總覽 / 個股詳情 / AI 分析 / AI 設定 四頁），觀察名單與 AI Top20 項目可點擊跳轉個股詳情頁
- [x] **Ollama 本機 AI 自動分析**：使用者提到自己有裝 Ollama，可以免費本機跑模型解決付費 API 的問題，因此串接上去並設為預設自動觸發（見下方說明）
- [x] **AI 深度分析（逐篇抓內文摘要）**：使用者發現 qwen2.5:7b 沒辦法自己爬網頁，只能就給定的文字做摘要，因此改成「先抓每則新聞的內文 → 逐篇AI摘要 → 彙整摘要再送一次AI選前20檔」的兩階段流程，取代原本只看標題+短摘要的做法（見下方說明）
- [x] 逐篇摘要結果存入 `news.excerpt` 欄位並顯示在「AI 分析」頁，結構化資料可作為之後報表產出的素材
- [x] **個股籌碼/未來展望分析（複製貼上流程）+ 每日報告產出**：見下方說明
- [ ] LINE Bot 串接，報表推播

#### 個股籌碼分析 + 每日報告（2026-07-28）

個股層級的分析（籌碼面判斷、未來展望）需要比較強的推理能力，使用者認為這種任務不像新聞摘要那樣適合丟給本機小模型，因此比照新聞分析的「複製貼上」模式，而不是再接一套 Ollama/API 自動呼叫：

1. `src/stock_analysis.py`：`build_stock_analysis_prompt(code)` 組出一份提示詞，內容包含：
   - 近期股價（FinMind 即時抓，最近30天，顯示最後15筆）
   - 近期三大法人買賣超歷史（本地資料庫累積，`db.query_code_history("institutional", code)`）
   - 近期融資融券歷史（本地資料庫累積）
   - 相關新聞（新增 `db.query_news_by_keyword(keyword, days=7)`，跨最近7天用代號/名稱搜尋標題、關聯代號、逐篇摘要欄位，去重合併）
   - 要求 AI 回答兩件事：**籌碼面分析**（法人買賣超趨勢、融資融券訊號、多空判斷）+ **個股未來預期**（短期1-2週展望、機會與風險）
2. `save_stock_analysis(code, analysis_text)` 存進新增的 `stock_analysis` 資料表（date, code, name, analysis, created_at）
3. 「個股詳情」頁新增「AI 個股分析」區塊：按鈕產生提示詞（`st.code` 顯示，可複製）→ 使用者自行貼到網頁版 AI → 貼回結果 → 存檔；也會顯示當天已存的分析
4. 新增「每日報告」頁（`report_page()`，`_build_report_text()`）彙整：
   - 新聞摘要（`ai_analysis_summary` 表）
   - 今日新聞焦點個股 Top20（`ai_picks` 表），**每檔都併上當天的三大法人買賣超**（`db.query_institutional(date, code)`，這樣不用把全市場上萬筆法人資料整個塞進報告，只顯示跟報告相關的重點個股）
   - 個股深度分析（`stock_analysis` 表，只顯示當天已經產生過分析的股票）
   - 輸出成 Markdown，頁面直接渲染，也提供「下載報告」按鈕匯出 `.md` 檔

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
│   ├── charting.py            # 個股K線圖 (plotly + FinMind 即時歷史)
│   ├── collect_all.py         # 每日收集流程整合
│   ├── collectors/
│   │   ├── twse_official.py   # TWSE/TPEx 官方 OpenAPI + rwd介面
│   │   ├── finmind.py         # FinMind API
│   │   ├── news_crawler.py    # 鉅亨網 API（含全文content欄位）
│   │   ├── news_rss.py        # Google News RSS（個股延伸新聞）
│   │   └── article_fetcher.py # Playwright headless瀏覽器，解析RSS連結的JS轉址取得全文
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
- LINE Bot 的 Channel 申請與 Webhook 部署方式，留待第二階段確認
