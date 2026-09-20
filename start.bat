@echo off
cd /d "%~dp0"

echo Starting Jimoty New Listing Monitor...
echo.
echo Backend logs are written to logs\jimoty_monitor.log (not shown in this console).
echo.

REM Start Backend (FastAPI)
start "jimoty-monitor backend" cmd /k "cd /d "%~dp0" && uvicorn api.main:app --reload --port 8000"

REM Wait 3 seconds
timeout /t 3 /nobreak > nul

REM Start Frontend (Vite) - Auto install if node_modules is missing
start "jimoty-monitor frontend" cmd /k "cd /d "%~dp0frontend" && (if not exist node_modules npm.cmd install) && npm.cmd run dev"

echo.
echo Both servers started.
echo Please open http://localhost:5173
echo.
timeout /t 2 /nobreak > nul
exit
