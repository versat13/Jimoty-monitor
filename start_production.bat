@echo off
REM 2026-09-21追加: このファイルはUTF-8 (BOM付き) で保存している。
REM cmd.exeは既定でシステムのANSIコードページ (日本語Windowsだと
REM 通常Shift_JIS/CP932) でバッチファイルを解釈するため、UTF-8のまま
REM だとREMコメントやechoの日本語が文字化けする・エディタで保存し
REM 直すたびに壊れる、という不具合が起きやすかった。
REM ここで明示的にUTF-8 (コードページ65001) に切り替えることで、
REM 実行環境やファイルの保存し直しに左右されず安定して表示できる
REM ようにする (>nul で切り替え時の案内メッセージは非表示にする)。
chcp 65001 >nul

REM ジモティー監視ツール 本番運用起動スクリプト (Windows用、2026-09-15新設)
REM
REM start.bat (開発用、Vite開発サーバー + uvicorn --reload の2プロセス構成)
REM と異なり、こちらはフロントエンドを一度だけビルドし、uvicornひとつだけで
REM 画面もAPIも配信する構成で起動する。常時起動しっぱなしの運用
REM (自分でスタートアップ・タスクスケジューラ等に登録する場合など)
REM はこちらを使うことを想定している。
REM
REM 事前準備 (初回のみ):
REM     pip install -r requirements.txt
REM     cd frontend && npm install && cd ..
REM
REM 実行方法: start_production.bat をダブルクリック
REM
REM 起動後、このPC自身からは http://localhost:8000 を開く。
REM 同じLAN内の他端末 (スマホ等) からは、この画面に表示されるIPアドレスを
REM 使って http://<IPアドレス>:8000 を開く (LAN内からのアクセスを受け
REM 付ける設定にしている。外部 [インターネット] には公開されない)。
REM
REM コードを修正した場合、このウィンドウを一度閉じて再度実行する必要が
REM ある (開発用のstart.batと違い、保存しただけでは自動反映されない。
REM 本番運用は安定性を優先し、意図せず再起動が走らない構成にしている
REM ため)。

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

REM --host 0.0.0.0: LAN内の他端末からのアクセスを受け付ける
REM   (省略時のデフォルトはlocalhostのみで、このPC自身からしかアクセスできない)。
REM --reload は付けない: 本番運用では、コード変更のたびに勝手に再起動されると
REM   巡回中の処理が中断される可能性があるため。
uvicorn api.main:app --host 0.0.0.0 --port 8000
