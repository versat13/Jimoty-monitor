"""
FastAPIサーバー本体。

仕様書 v1.0 3章の技術スタック（React + Vite + Tailwind CSS のフロント、
FastAPIのバックエンド、同一プロセスでのReactビルド成果物配信）のうち、
バックエンドAPI部分を提供する。

このAPIサーバーは repository/ 層をそのままJSON化して返す薄い層であり、
ビジネスロジック（フィルタ判定、ステータス遷移等）は持たない
(scraper/, filters/, repository/, scheduler/ の責務)。

=== 起動方法 (開発時) ===

    cd jimoty-monitor
    pip install -r requirements.txt
    uvicorn api.main:app --reload --port 8000

開発時は別途 `cd frontend && npm run dev` でVite開発サーバー
(5173番ポート) も起動し、http://localhost:5173 にアクセスする
(start.sh / start.bat がこの2つをまとめて起動する)。

起動後、http://localhost:8000/docs でSwagger UIから各エンドポイントを
試せる。

=== 起動方法 (本番運用、2026-09-15新設) ===

開発サーバー2つ (Vite + uvicorn --reload) を常時起動しっぱなしにする
運用は、Vite開発サーバーが本来「開発中に使うもの」であり、長期の
常時起動運用には向いていないため、以下の「ビルド済み静的ファイルを
uvicornだけで配信する」構成を用意した。

    cd jimoty-monitor
    pip install -r requirements.txt
    cd frontend && npm install && npm run build && cd ..
    uvicorn api.main:app --host 0.0.0.0 --port 8000

`frontend/dist/` にビルド成果物が生成されていれば、このファイルの
末尾でFastAPIがそれを配信するようマウントする (StaticFiles、
详細は末尾のコメント参照)。ビルド成果物が無い場合はこのマウントを
スキップし、開発時の動作 (Vite側でフロントを別途配信する前提) を
壊さない。

`--host 0.0.0.0` を指定すると、同じLAN内の他端末 (スマホ等) からも
`http://<このPCのIPアドレス>:8000` でアクセスできるようになる
(`--host` を省略した場合のデフォルトは`127.0.0.1` で、実行している
PC自身からしかアクセスできない)。`--reload` は開発用オプションのため
本番では付けない (コード変更のたびに勝手に再起動されると、巡回中の
処理が中断される可能性があるため)。

まとめて実行できるスクリプトとして `start_production.sh` /
`start_production.bat` を直下に用意した (詳細はREADME
「本番運用化 (2026-09-15)」セクション参照)。

=== 構成 (2026-09-13、機能別ルーターへ分割) ===

以前は全エンドポイントがこのファイル1つ (1756行) に同居していたが、
見通しの悪さを解消するため api/routers/ 以下に機能単位で分割した。
このファイル自体は
    - FastAPIアプリの生成
    - lifespan (自動更新バックグラウンドタスク) の起動・終了
    - CORS設定
    - 各routerのinclude_router
    - 本番ビルド成果物 (frontend/dist/) の静的配信 (2026-09-15追加)
のみを担当する薄いエントリポイントになっている。

DB_PATH・get_db() は分割後も api/deps.py 経由で共通利用するが、
DB_PATH という変数自体はテスト (tests/test_api.py) が
`monkeypatch.setattr(main_module, "DB_PATH", db_path)` の形で直接
書き換える設計になっているため、このファイルにモジュール変数として
残してある (api/deps.py の get_db() はこの変数を都度参照しにいく)。
"""

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from scheduler.auto_refresh import auto_refresh_loop

# 2026-09-13分割時の後方互換のための再エクスポート。
# get_db() の実体は api/deps.py に集約したが、
# tests/test_api.py が `api.main.get_db` という参照を残しているため、
# ここでも同名でアクセスできるようにしておく (実体は1つ、deps.py側)。
from api.deps import get_db  # noqa: F401

from api.routers import (
    articles,
    ng_categories,
    ng_keywords,
    scan,
    search_history,
    seller_rules,
    sellers,
    settings_discord_notification,
    settings_export,
    settings_pickup_search,
    settings_region,
    settings_reset,
    settings_retention,
    settings_scan,
    watches,
)

# 2026-09-07新設 (重要): scheduler.job等、アプリケーション独自の
# logger.info/warning/exceptionが、これまで実際にはどこにも出力されて
# いなかった問題への対応。
#
# 経緯: 「投稿日・最終更新日が表示されない」不具合の調査で、
# scheduler/job.pyにlogger.warning (article_id不一致の検知) や
# logger.exception (個別ページ処理中の例外) を仕込んで原因究明を
# 試みたが、ユーザーの実機ログにはuvicornのアクセスログ
# (INFO: 127.0.0.1:... "GET ...") しか表示されず、アプリケーション側の
# ログが一切見えなかった。
#
# 原因: logging.basicConfig() がどこからも呼ばれておらず、
# scheduler.job等のlogger (logging.getLogger(__name__)) にハンドラが
# 設定されていなかった。uvicornは自分自身のロガー(uvicorn, uvicorn.access)
# には自動でハンドラを設定するが、アプリケーション独自のロガーには
# 何もしない。このため、警告や例外が実際に発生していても、これまでの
# 調査では気づけなかった可能性がある。
#
# ここでルートロガーにハンドラを設定することで、scheduler.job等の
# logger.info/warning/exception呼び出しがすべてuvicornと同じ標準出力に
# 流れるようにする。今後の不具合調査では、このログ出力を確認することで
# 巡回処理中に何が起きているか (article_id不一致の警告、個別ページ
# 処理中の例外など) を正確に把握できるようになる。
#
# 2026-09-13変更 (ログ運用改善、ユーザーとの合意事項):
# 以前はコンソール (標準出力) にのみ出力していたが、以下の理由から
# ファイル出力のみに切り替えた:
#   - ソフトを長期間・常駐運用する前提のため、ログを後から見返せる
#     形で残しておきたい (コンソールはスクロールバッファに限りがあり、
#     BATウィンドウを閉じれば消えてしまう)。
#   - ローテーション (日付単位、7日分保持) を導入し、ディスク容量が
#     際限なく増え続けないようにする。
#   - コンソールには意図的に何も出さない (ユーザーとの合意事項。
#     起動中のBATウィンドウは空のままになるが、状態はログファイルで
#     確認する運用とする)。
#
# uvicornが自動設定する自身のロガー (uvicorn, uvicorn.access等) も、
# root loggerのハンドラ設定に影響されず標準出力へ直接出力し続けて
# しまう可能性があるため、uvicorn系のロガーにもこのファイル
# ハンドラを明示的に付与し、かつ標準出力へのpropagateを止める
# ことで、コンソールに何も出ないようにしている。
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

# TimedRotatingFileHandler: 1日(深夜0時)ごとにローテーションし、
# 直近7世代 (=直近7日分) のログファイルのみ保持する。バックアップ
# ファイルには日付が "jimoty_monitor.log.2026-09-13" のように
# 自動的に付与される (whenのデフォルトのsuffix)。
_file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / "jimoty_monitor.log",
    when="midnight",
    backupCount=7,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(_file_handler)

# uvicorn・uvicorn.access・uvicorn.error は自前でハンドラを持つ設計に
# なっており、何もしないとコンソールへ直接出力されてしまう
# (root loggerのハンドラ設定を経由しない)。このため、これらの
# ロガーにも明示的にファイルハンドラを付け、標準出力への伝播
# (propagate) を止めることで、アプリ全体のログを一貫してファイルへ
# 集約する。
for _uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _uvicorn_logger = logging.getLogger(_uvicorn_logger_name)
    _uvicorn_logger.handlers = [_file_handler]
    _uvicorn_logger.propagate = False

DB_PATH = str(Path(__file__).parent.parent / "jimoty_monitor.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    2026-09-09新設: 自動更新 (サーバー側定期実行) のバックグラウンド
    タスクを起動・終了する。

    DB_PATH をモジュール変数として直接参照せず、実行時に
    `sys.modules[__name__].DB_PATH` 経由で読むのは過剰なので、
    ここでは関数呼び出し時点のグローバル変数DB_PATHをそのまま渡す。
    テスト (tests/test_api.py) は monkeypatch.setattr(main_module,
    "DB_PATH", ...) でこの変数を差し替えるが、TestClientは
    lifespanを都度実行しない使い方もできるため、自動更新ループが
    テストの妨げにならないよう配慮している
    (scheduler.auto_refresh.auto_refresh_loop のdocstring参照)。
    """
    task = asyncio.create_task(auto_refresh_loop(DB_PATH))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="ジモティー新着監視ツール API", lifespan=lifespan)

# 開発時はReact開発サーバー(Vite、デフォルト5173番ポート)からのアクセスを許可する。
# 本番ビルドではFastAPIが同一オリジンでReact成果物を配信するため、
# CORSの許可自体が不要になる想定 (仕様書3章)。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 各ルーターを登録する (api/routers/ 以下、機能単位で分割済み)。
app.include_router(articles.router)
app.include_router(sellers.router)
app.include_router(ng_keywords.router)
app.include_router(ng_categories.router)
app.include_router(seller_rules.router)
app.include_router(watches.router)
app.include_router(settings_scan.router)
app.include_router(settings_region.router)
app.include_router(settings_retention.router)
app.include_router(settings_pickup_search.router)
app.include_router(settings_discord_notification.router)
app.include_router(search_history.router)
app.include_router(settings_export.router)
app.include_router(settings_reset.router)
app.include_router(scan.router)

# ---------------------------------------------------------------------
# 2026-09-15追加: 本番運用向け、frontend/dist/ (Reactビルド成果物) の
# 静的配信。
#
# `frontend/dist/` が存在する場合 (= `npm run build` 実行済み) のみ
# マウントする。存在しない場合は何もしない (開発時、Vite開発サーバー
# 側でフロントエンドを別途配信する従来の運用を壊さないため)。
#
# ルーティングの考え方:
#   - `/assets/...` (Viteがビルド時に出力するJS/CSSバンドル) は
#     StaticFilesがそのまま配信する。
#   - それ以外のパス (`/`, `/settings/keywords` 等) は、React Router
#     (フロントエンド側のクライアントサイドルーティング、
#     frontend/src/App.jsx参照) が処理するパスなので、常に
#     `frontend/dist/index.html` を返す (SPAの「キャッチオール」
#     フォールバック)。これにより、`/settings/keywords` のような
#     URLを直接開いた場合やブラウザの再読み込みをした場合でも、
#     404にならずReact側のルーティングに処理を委ねられる。
#   - `/api/...` は上ですでに各ルーターに登録済みのため、この
#     キャッチオールより先にFastAPIがマッチさせる (ルート登録の順序上、
#     後から追加したキャッチオールが `/api/...` を横取りすることは
#     ない。とはいえ明示的に除外しておくと安全なため、下記の
#     `serve_spa` 内でも念のため `/api` プレフィックスを弾く)。
# ---------------------------------------------------------------------
_FRONTEND_DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIST_DIR.is_dir():
    _assets_dir = _FRONTEND_DIST_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        """
        React Router (SPA) 向けのキャッチオールルート (2026-09-15新設)。

        `/api/...` へのリクエストは (本来ここに来る前に各ルーターで
        処理されているはずだが) 念のため404を返す。それ以外の
        パスは、実ファイルが frontend/dist/ 内に存在すればそれを
        (favicon.ico等)、存在しなければ index.html を返す (React
        Routerがブラウザ側でパスを解釈してくれる)。
        """
        if full_path.startswith("api/") or full_path == "api":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not Found")

        candidate = _FRONTEND_DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(_FRONTEND_DIST_DIR / "index.html")
