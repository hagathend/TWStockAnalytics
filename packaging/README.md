# 打包與發布（Windows 安裝程式）

給不懂電腦的使用者：下載一個 `.exe`，雙擊安裝，不需要自己裝 Python。

## 發布新版（平常只需要這樣）

1. 改 `src/version.py` 的 `__version__`（例如 `0.0.4`）並提交
2. 合併到 `main` 後打 annotated tag，**tag 訊息會變成 Release 說明**：
   ```bash
   git tag -a v0.0.4 -m "ver 0.0.4 ..."
   git push origin v0.0.4
   ```
3. GitHub Actions（`.github/workflows/release.yml`）自動：單元測試 → 檢查版本號與 tag 一致 →
   打包 → 安裝／解除安裝測試 → 建立 Release 並附上安裝程式
4. 已安裝的使用者，程式側邊欄會在 24 小時內出現「有新版本」

版本號和 tag 不一致時 CI 會直接失敗，不會發出去。

## 安裝版的結構

| 位置 | 內容 |
|---|---|
| `%LOCALAPPDATA%\Programs\TWStockAnalytics` | 程式：`python\`（獨立版 Python + 套件）、`ms-playwright\`（Chromium）、`src\`、`launcher.pyw`、`.installed` |
| `%LOCALAPPDATA%\TWStockAnalytics\data` | 資料：資料庫、持股、設定、`logs\`。更新與解除安裝（預設）都不會動到 |
| 工作排程器「TWStockAnalytics 每日收集」 | 使用者在「開始使用」頁打開才會建立；解除安裝時移除 |

程式根目錄有 `.installed` 才會把資料放到 `%LOCALAPPDATA%`（見 `src/config.py`）。
**不要把 `.installed` 放進 git**，否則開發資料夾的資料位置會跑掉（`tests/test_desktop.py` 會擋）。

## 把開發資料夾的資料搬到安裝版

開發資料夾（`<專案>\data`）和安裝版（`%LOCALAPPDATA%\TWStockAnalytics\data`）的資料互不相通。
先在安裝版側邊欄按「結束程式」，再執行：

```powershell
.venv\Scripts\python.exe scripts\migrate_to_installed.py
```

會先備份安裝版原本的資料到 `data_backup_<時間>`，用 SQLite 備份 API 複製資料庫（開發版開著也沒關係），
搬完檢查完整性並逐表比對筆數。只搬資料庫、觀察名單、Codex／報告／Firecrawl 設定。

## 本機打包

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_app.ps1        # 組 build\app 並跑冒煙測試
powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1  # 需要先安裝 Inno Setup
```

- 打包的是 **git HEAD** 的內容，未提交的修改不會被包進去
- `packaging\test_installer.ps1` 會真的安裝／解除安裝「台股分析」，只在 CI 的乾淨環境跑

## 更新套件版本

`requirements.txt` 是寬鬆的直接依賴，`requirements.lock` 是實際打包的精確版本。
升級套件後在**短路徑**的乾淨環境重新產生 lock（路徑太長時 Streamlit 會裝不完整）：

```powershell
python -m venv C:\tmp\lockvenv
C:\tmp\lockvenv\Scripts\python -m pip install -r requirements.txt
C:\tmp\lockvenv\Scripts\python -m pip freeze   # 內容貼回 requirements.lock（保留開頭註解）
```

Streamlit 鎖在固定次版本：`src/ui.py` 的自訂 CSS 依賴 Streamlit 內部 DOM，升版前要先看過畫面。

## 已知限制

- 安裝程式沒有數位簽章，Windows 會跳「Windows 已保護您的電腦」，要點「其他資訊 → 仍要執行」
- AI 分析需要使用者自己安裝 Codex 並用 ChatGPT 帳號登入（「開始使用」頁有引導）
