#!/bin/bash
# ジモティー監視ツール 起動スクリプト (Mac/Linux用)
#
# 事前準備 (初回のみ):
#     pip install -r requirements.txt
#     cd frontend && npm install && cd ..
#
# 実行方法:
#     chmod +x start.sh   (初回のみ)
#     ./start.sh
#
# 起動後、ブラウザで http://localhost:5173 を開く。
# 終了する場合は Ctrl+C を押す (バックエンド・フロントエンド両方が停止する)。

set -e
cd "$(dirname "$0")"

echo "ジモティー監視ツールを起動します..."
echo "バックエンドのログは logs/jimoty_monitor.log に出力されます（このコンソールには表示されません）。"
echo ""

# Ctrl+C (SIGINT) が来たら、起動した子プロセスを両方まとめて終了する
cleanup() {
    echo ""
    echo "終了します..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# バックエンド(FastAPI)をバックグラウンドで起動
uvicorn api.main:app --reload --port 8000 &
BACKEND_PID=$!

# フロントエンドの起動が早すぎるとAPIサーバーが間に合わないことがあるため、少し待つ
sleep 3

# フロントエンド(Vite)をバックグラウンドで起動 (node_modules未生成なら自動インストール)
(cd frontend && [ -d node_modules ] || npm install && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "バックエンド・フロントエンドを起動しました。"
echo "数秒後、ブラウザで http://localhost:5173 を開いてください。"
echo "終了するには Ctrl+C を押してください。"
echo ""

wait
