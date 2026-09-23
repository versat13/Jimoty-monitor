@echo off
REM Production launcher (Windows). See docs/ for details.
REM Comments here are kept ASCII-only: past versions had long
REM Japanese REM blocks that cmd.exe intermittently mis-parsed
REM as commands (garbled mid-line, regardless of chcp/BOM state).
chcp 65001 >nul

cd /d "%~dp0"

echo ジモティー監視ツール (本番運用モード) を起動します...
echo.

echo フロントエンドをビルドしています...
cd frontend
if not exist node_modules (
    call npm.cmd install
)
call npm.cmd run build
cd /d "%~dp0"
echo ビルドが完了しました。
echo.

echo バックエンドのログは logs\jimoty_monitor.log に出力されます（このコンソールには表示されません）。
echo.
echo 起動後のアクセス先:
echo   このPCから:            http://localhost:8000
echo   同じLAN内の他端末から: http://（下記IPアドレスのいずれか）:8000
echo.
echo このPCのIPアドレス一覧（ipconfigの結果、参考用）:
ipconfig | findstr /R /C:"IPv4"
echo.
echo 終了するには、この画面を閉じるか Ctrl+C を押してください。
echo.

REM --host 0.0.0.0 allows access from other devices on the LAN.
REM --reload is intentionally omitted for production stability.
uvicorn api.main:app --host 0.0.0.0 --port 8000
