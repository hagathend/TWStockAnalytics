@echo off
REM 雙擊即可啟動台股每日資訊收集 UI（會自動開啟預設瀏覽器）
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
    echo 找不到虛擬環境，請先執行: python -m venv .venv 並 pip install -r requirements.txt
    pause
    exit /b 1
)
.venv\Scripts\streamlit.exe run src\app.py
pause
