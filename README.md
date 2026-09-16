# TWStockAnalytics

台股每日分析工具：自動收集盤後價量、三大法人、融資融券、基本面與新聞，用 **Codex CLI** 逐篇分析新聞並挑出焦點個股，
搭配程式計算的技術／籌碼指標、選股與回測，整理成每日報告。

> 本工具僅供資訊整理與研究參考，不構成投資建議。
> 完整規劃與踩坑筆記見 [PLAN.md](PLAN.md)。

## 安裝（一般使用者）

到 [Releases](https://github.com/hagathend/TWStockAnalytics/releases/latest) 下載 `TWStockAnalytics-Setup-版本號.exe`，
雙擊安裝即可，不需要自己安裝 Python。出現「Windows 已保護您的電腦」時點「其他資訊 → 仍要執行」。

第一次開啟會進到「開始使用」頁，依序完成：

1. 閱讀免責聲明
2. 下載約半年的上市股歷史資料（背景執行，約 20–30 分鐘）
3. 安裝並登入 Codex（AI 分析用，需要自己的 ChatGPT 帳號；沒有也能使用其他功能）
4. 打開每日自動收集

有新版本時側邊欄會提示，一鍵下載並安裝，資料與持股紀錄都會保留。打包與發布流程見 [packaging/README.md](packaging/README.md)。

## 功能

### 資料收集
- **TWSE / TPEx 官方資料**：收盤價量、三大法人買賣超、融資融券、本益比／殖利率／淨值比、月營收
- **FinMind API**：K 線歷史與交叉驗證
- **鉅亨網 API + Google News RSS**：當日新聞與觀察名單個股的延伸新聞
- 資料存在本機 SQLite；上市股歷史可一次補收集，每日收集時也會自動補上近兩週漏掉的交易日
- 每日 20:00 自動收集（Windows 工作排程器），錯過時間會在下次開機後補做

### AI 分析（Codex CLI）
- 使用這台電腦已登入的 Codex CLI 與帳號額度，**不需要填 API Key**
- **新聞深度分析**：先擷取新聞內文（鉅亨網 API 內建全文；其他來源優先用 Firecrawl、退回本機 Playwright），
  逐篇摘要後彙整挑出當日最多 20 檔焦點個股；收集完可自動觸發
- **個股分析**：依程式算好的技術指標、籌碼延伸指標、基本面、新聞分析技術面／籌碼面／1～2 週展望（每項 800 字內）；
  持有的股票會附上成本與損益，列出續抱／減碼／停損的條件式觀察點，不直接下買賣指令
- **大盤籌碼分析**：上市櫃個股法人加總、漲跌家數、新聞重點，總計 1000 字內
- Codex 以唯讀、臨時工作階段執行；也保留「產生提示詞 → 貼到網頁版 AI → 貼回儲存」的手動流程

### 指標、選股與回測（程式計算，非 AI 估算）
- **技術指標**：MA、RSI、MACD、KD、布林通道、量能；K 線圖疊上均線與成交量
- **籌碼延伸指標**：法人連買／連賣天數、5／20 日累計、佔成交量比重、融資變化對照股價、券資比
- **選股工具**：均線排列、突破新高、跳空、爆量長紅黑、相對強弱、投信認養等訊號，可加上本益比、殖利率、
  營收年增等基本面條件；結果可複選並一次加入觀察名單
- **觀察名單警示**：區分「今日新出現」與「持續中」的訊號
- **訊號回測**：訊號出現後 5／20 個交易日的報酬分布、勝率與相對大盤的超額報酬

### 持股與報告
- **我的持股**：記錄每筆買進的股數與成本，計算加權平均成本、未實現損益與持股訊號，可逐檔用 Codex 分析
- **每日報告**：新聞摘要、大盤分析、焦點個股（含法人買賣超）、觀察名單訊號、個股分析，可下載 Markdown 或 PDF；
  可選擇是否包含持股（預設不含，避免分享 PDF 時外流）

## 開發

```bash
git clone git@github.com:hagathend/TWStockAnalytics.git
cd TWStockAnalytics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

另外需要安裝 [Codex CLI](https://github.com/openai/codex) 並執行 `codex login`。

```bash
# 啟動 UI（也可以雙擊 start_ui.bat）
.venv\Scripts\streamlit.exe run src\app.py

# 手動執行一次每日收集（不開 UI）
.venv\Scripts\python.exe scripts\run_daily_collect.py

# 補收集上市歷史（可中斷續跑）
.venv\Scripts\python.exe scripts\backfill_history.py --days 180

# 單元測試
.venv\Scripts\python.exe -m unittest discover -s tests

# 把開發資料夾的資料搬到安裝版
.venv\Scripts\python.exe scripts\migrate_to_installed.py
```

每日自動收集請在 UI 的「開始使用」頁開啟（會建立 Windows 工作排程）。

開發資料夾的資料放在專案內的 `data/`；安裝版放在 `%LOCALAPPDATA%\TWStockAnalytics\data`，兩者互不相通。

## 技術棧

Python 3.13 + Streamlit + SQLite + pandas + plotly，AI 分析使用 Codex CLI，Windows 安裝程式使用 Inno Setup。

## 目前進度

- [x] 資料收集 + Streamlit UI
- [x] AI 新聞深度分析、個股／大盤分析、每日報告（Codex CLI）
- [x] 技術／籌碼指標、選股工具、訊號回測、基本面
- [x] 我的持股
- [x] Windows 安裝程式與自動更新
- [ ] 第三階段：預測追蹤、產業熱力圖、條件提醒、大戶持股、交易日誌等（見 PLAN.md）
