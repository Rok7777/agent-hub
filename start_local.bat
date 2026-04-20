@echo off
echo ================================================
echo  Agent Hub — Lokalni zagon (Loti + Blagajna)
echo ================================================
echo.

REM Preveri ali je playwright nameščen
python -c "import playwright" 2>nul
if errorlevel 1 (
    echo [SETUP] Nameščam playwright...
    pip install playwright
    playwright install chromium
    echo.
)

echo [INFO] Zagon Streamlit na http://localhost:8501
echo [INFO] Chrome mora biti odprt z:
echo         chrome.exe --remote-debugging-port=9222
echo.
streamlit run app.py --server.port 8501
pause
