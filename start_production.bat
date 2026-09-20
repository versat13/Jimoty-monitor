@echo off
REM Jimoty New Listing Monitor - Production launch script (Windows)
REM
REM Unlike start.bat (dev mode: Vite dev server + uvicorn --reload,
REM two processes), this script builds the frontend once and serves
REM both the UI and the API from a single uvicorn process. Use this
REM when you want to keep the app running continuously (e.g. registered
REM in Windows startup or Task Scheduler).
REM
REM First-time setup:
REM     pip install -r requirements.txt
REM     cd frontend ^&^& npm install ^&^& cd ..
REM
REM How to run: double-click start_production.bat
REM
REM After startup, open http://localhost:8000 from this PC.
REM From another device on the same LAN (e.g. a phone), use the IP
REM address shown below: http://<IP address>:8000
REM (Binds to 0.0.0.0, so it accepts LAN connections. It is NOT
REM exposed to the internet.)
REM
REM If you change the code, close this window and run it again
REM (unlike the dev start.bat, changes are not picked up automatically;
REM production mode favors stability and avoids unexpected restarts).

chcp 65001 > nul
cd /d "%~dp0"

echo Starting Jimoty New Listing Monitor (production mode)...
echo.

echo Building frontend...
cd frontend
if not exist node_modules (
    call npm.cmd install
)
call npm.cmd run build
cd /d "%~dp0"
echo Build complete.
echo.

echo Backend logs are written to logs\jimoty_monitor.log (not shown in this console).
echo.
echo Access this app at:
echo   From this PC:              http://localhost:8000
echo   From another device on LAN: http://(one of the IPv4 addresses below):8000
echo.
echo This PC IPv4 address(es) (from ipconfig, for reference):
ipconfig | findstr /R /C:"IPv4"
echo.
echo To stop: close this window or press Ctrl+C.
echo.

REM --host 0.0.0.0: accept connections from other devices on the LAN
REM   (default is localhost only, accessible only from this PC).
REM --reload is intentionally omitted: in production, auto-restarting on
REM   every code change could interrupt an in-progress scan.
uvicorn api.main:app --host 0.0.0.0 --port 8000
