#!/bin/bash
# ジモティー監視ツール 本番運用起動スクリプト (Mac/Linux用、2026-09-15新設)
#
# start.sh (開発用、Vite開発サーバー + uvicorn --reload の2プロセス構成)
# と異なり、こちらはフロントエンドを一度だけビルドし、uvicornひとつだけで
# 画面もAPIも配信する構成で起動する。常時起動しっぱなしの運用
# (自分でOSのスタートアップ・タスクスケジューラ等に登録する場合など)
# はこちらを使うことを想定している。
#
# 事前準備 (初回のみ):
#     pip install -r requirements.txt
#     cd frontend && npm install && cd ..
#
# 実行方法:
#     chmod +x start_production.sh   (初回のみ)
#     ./start_production.sh
#
# 起動後、このPC自身からは http://localhost:8000 を開く。
# 同じLAN内の他端末 (スマホ等) からは、下記に表示されるIPアドレスを
# 使って http://<IPアドレス>:8000 を開く (--host 0.0.0.0 により、
# LAN内からのアクセスを受け付ける設定にしている。外部 [インター
# ネット] には公開されない)。
#
# コードを修正した場合、この起動スクリプトを一度終了 (Ctrl+C) して
# 再度実行する必要がある (開発用のstart.shと違い、保存しただけでは
# 自動反映されない。本番運用は安定性を優先し、意図せず再起動が走らない
# 構成にしているため)。
#
# 終了する場合は Ctrl+C を押す。

set -e
cd "$(dirname "$0")"

echo "ジモティー監視ツール (本番運用モード) を起動します..."
echo ""

# フロントエンドのビルド (node_modules未生成なら自動インストール)
echo "フロントエンドをビルドしています..."
(cd frontend && [ -d node_modules ] || npm install && npm run build)
echo "ビルドが完了しました。"
echo ""

# 2026-09-15: LAN内アクセス用に、このPCのIPアドレスを画面に表示する。
# OSによってipコマンドの有無・出力形式が異なるため、いくつかの方法を
# 順に試し、見つからなければ「不明」のまま案内文だけ表示する
# (IPアドレスの特定に失敗してもアプリの起動自体は妨げない)。
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')

echo "バックエンドのログは logs/jimoty_monitor.log に出力されます（このコンソールには表示されません）。"
echo ""
echo "起動後のアクセス先:"
echo "  このPCから:        http://localhost:8000"
if [ -n "$LOCAL_IP" ]; then
    echo "  同じLAN内の他端末から: http://$LOCAL_IP:8000"
else
    echo "  同じLAN内の他端末から: http://<このPCのIPアドレス>:8000 （IPアドレスの自動検出に失敗しました。OSのネットワーク設定から確認してください）"
fi
echo ""
echo "終了するには Ctrl+C を押してください。"
echo ""

# --host 0.0.0.0: LAN内の他端末からのアクセスを受け付ける
#   (省略時のデフォルトはlocalhostのみで、このPC自身からしかアクセスできない)。
# --reload は付けない: 本番運用では、コード変更のたびに勝手に再起動されると
#   巡回中の処理が中断される可能性があるため。
uvicorn api.main:app --host 0.0.0.0 --port 8000
