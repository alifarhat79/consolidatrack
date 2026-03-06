@echo off
title ConsolidaTrack Server
echo ========================================
echo    ConsolidaTrack - Maritime Logistics
echo ========================================
echo.
echo Starting server on port 5050...
echo Press Ctrl+C to stop
echo.
start "" /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:5050"
py wsgi.py
pause
