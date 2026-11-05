@echo off
REM 全球市場早報：給 Windows 工作排程器呼叫用
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" daily_market_brief.py
