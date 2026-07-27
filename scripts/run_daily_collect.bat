@echo off
REM 供 Windows 工作排程器呼叫：每日 20:00 執行台股資料收集
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python scripts\run_daily_collect.py >> data\collect.log 2>&1
