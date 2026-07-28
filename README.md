# TWStockAnalytics

每日自動化台股分析系統：收集盤後價量、三大法人買賣超、融資融券與新聞，用本機 AI（Ollama）逐篇分析新聞內文並挑出重點個股，產出報表並推播至 LINE。

> 完整規劃、階段劃分與踩坑筆記見 [PLAN.md](PLAN.md)。

## 功能

- 每日收集台股盤後資訊：
  - **TWSE / TPEx 官方 OpenAPI + rwd 介面**：收盤價量、三大法人買賣超、融資融券
  - **FinMind API**：交叉驗證與補充
  - **鉅亨網 API + Google News RSS**：當日新聞與個股延伸新聞搜尋
- 資料存入本地 SQLite，可依日期 / 股票代碼 / 名稱模糊搜尋查詢
- **AI 新聞深度分析（本機 Ollama，免費）**：先幫每則新聞抓內文（鉅亨網API內建、Google News RSS 用 headless 瀏覽器解析 JS 轉址），逐篇摘要後再彙整挑出當日前20檔重點個股，收集資料後自動觸發，不需要付費 API Key
- 可編輯觀察名單 + AI 新聞焦點 Top20，點擊可跳轉個股詳情頁（K線圖 + 籌碼歷史 + 相關新聞）
- **Streamlit 網頁 UI**：手動觸發收集、瀏覽已收集資料、AI 供應商設定（Ollama 為主，Claude / GPT / Gemini API Key 作為進階選項）
- 每日 20:00 排程腳本，可註冊進 Windows 工作排程器自動執行

## 快速開始

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
- [x] 第二階段：AI 新聞深度分析（本機 Ollama 自動觸發）+ 可編輯觀察名單 + 個股K線圖詳情頁
- [ ] 籌碼/線型技術面的 AI 輔助判讀、報表產出、LINE Bot 推播
