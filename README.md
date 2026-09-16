# TWStockAnalytics

每日自動化台股分析系統：收集盤後價量、三大法人買賣超、融資融券與新聞，用本機 AI（Ollama）逐篇分析新聞內文並挑出重點個股，產出報表並推播至 LINE。

> 完整規劃、階段劃分與踩坑筆記見 [PLAN.md](PLAN.md)。

## 功能

- 每日收集台股盤後資訊：
  - **TWSE / TPEx 官方 OpenAPI + rwd 介面**：收盤價量、三大法人買賣超、融資融券
  - **FinMind API**：交叉驗證與補充
  - **鉅亨網 API + Google News RSS**：當日新聞與個股延伸新聞搜尋
- 資料存入本地 SQLite，可依日期 / 股票代碼 / 名稱模糊搜尋查詢
- **AI 新聞深度分析**：先幫每則新聞抓內文（鉅亨網API內建、Google News RSS 優先用 Firecrawl 免費額度擷取、退回本機 Playwright），逐篇摘要後再彙整挑出當日前20檔重點個股。預設用**本機 Ollama**（免費、自動觸發、不需要任何 API Key），也可以改用**雲端 API**（Gemini 免費額度 / Claude·GPT 付費）當替代選項
- 可編輯觀察名單 + AI 新聞焦點 Top20，點擊可跳轉個股詳情頁（K線圖 + 籌碼歷史 + 相關新聞）
- **技術指標與線型**：K 線圖疊上 MA5/20/60 均線與成交量副圖；程式端計算 RSI、MACD、KD、布林通道、量能（純數學計算，非 AI 估算）
- **個股籌碼＋技術面分析（複製貼上流程）**：個股詳情頁可產生包含**算好的技術指標**、籌碼歷史與相關新聞的提示詞，複製貼到網頁版 AI 分析技術面／籌碼面／未來展望，結果會存起來
- **大盤整體籌碼分析（複製貼上流程）**：AI 分析頁可產生含大盤法人買賣超、漲跌家數、新聞重點的提示詞，回覆限制500字內（短期/中期展望、籌碼分析、熱門產業）
- **每日報告**：彙整新聞摘要、大盤籌碼分析、新聞焦點個股（含三大法人買賣超）、個股深度分析，可下載成 Markdown 或 PDF
- **Streamlit 網頁 UI**：手動觸發收集、瀏覽已收集資料、AI 供應商設定（Ollama 為主，Claude / GPT / Gemini API Key 作為進階選項）
- 每日 20:00 排程腳本，可註冊進 Windows 工作排程器自動執行

## 安裝（一般使用者）

到 [Releases](https://github.com/hagathend/TWStockAnalytics/releases/latest) 下載 `TWStockAnalytics-Setup-版本號.exe`，
雙擊安裝即可，不需要自己安裝 Python。出現「Windows 已保護您的電腦」時點「其他資訊 → 仍要執行」。
第一次開啟會進到「開始使用」頁，依序完成免責聲明、下載歷史資料、Codex 登入與每日自動收集設定。

> 本工具僅供資訊整理與研究參考，不構成投資建議。

打包與發布流程見 [packaging/README.md](packaging/README.md)。

## 快速開始（開發）

```bash
git clone git@github.com:hagathend/TWStockAnalytics.git
cd TWStockAnalytics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

日常使用：雙擊專案根目錄的 `start_ui.bat` 即可啟動 UI（自動開啟瀏覽器 http://localhost:8501），不需手動下指令。

也可手動執行：

```bash
# 手動執行一次資料收集（不開 UI）
.venv\Scripts\python.exe scripts\run_daily_collect.py

# 啟動網頁 UI
.venv\Scripts\streamlit.exe run src\app.py
```

## 設定每日自動收集（Windows 工作排程器）

```powershell
schtasks /Create /TN "TWStock_DailyCollect" /TR "D:\workspace\TWStockAnalytics\scripts\run_daily_collect.bat" /SC DAILY /ST 20:00
```

## 技術棧

Python 3.13 + Streamlit + SQLite。詳細架構、資料來源決策與已知問題請見 [PLAN.md](PLAN.md)。

## 目前進度

- [x] 第一階段：資料收集 + Streamlit UI
- [x] 第二階段：AI 新聞深度分析（本機 Ollama 自動觸發）+ 可編輯觀察名單 + 個股K線圖詳情頁 + 個股籌碼分析 + 每日報告
- [ ] LINE Bot 串接推播


## Codex CLI 分析（developCodexCLI）

新聞預設改用 Codex CLI：收集後自動逐篇摘要，再彙整焦點個股。
個股與大盤頁可按「用 Codex 分析…並儲存」，自動產生提示詞、取得回覆並收錄既有 PDF 報告。
原有複製貼上功能仍可使用。

請先安裝 Codex CLI 並以 `codex login` 登入。AI 設定頁可檢查登入、設定執行檔完整路徑、
模型及每次呼叫逾時秒數；不需輸入 API Key，但會使用 Codex 帳號額度。
CLI 使用獨立暫存目錄、唯讀模式及臨時工作階段，不載入使用者的 CLI 工具設定。
新聞內文由既有收集器提供，分析失敗會顯示錯誤，不以錯誤文字覆蓋既有分析。
