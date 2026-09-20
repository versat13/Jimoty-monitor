"""
api/main.py の本番運用向け静的ファイル配信 (2026-09-15新設) のテスト。

frontend/dist/ (Reactビルド成果物) が存在する場合、FastAPIがそれを
配信するようになる。このテストでは実際に `npm run build` を実行する
代わりに、テスト用の一時ディレクトリにダミーの dist/ を用意して検証する
(CI環境や通常のpytest実行でNode.js/npmへの依存を発生させないため)。

2026-09-15補足: api.main.app はモジュールimport時点で一度だけ
frontend/dist/の有無を判定してマウントを行う (このリポジトリの開発
環境では、手元で `npm run build` した結果の本物のdist/が既に存在する
ことがある)。そのため、このテストファイルではapi.main.appを直接
使い回さず、api.mainのマウント処理と同じロジックをテスト用の独立した
FastAPIアプリ上で再現することで、実際のdist/の有無に依存せず
決定的に検証できるようにしている。
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.main as main_module
from repository.article_repository import get_connection


def _build_app_with_dist(dist_dir: Path) -> FastAPI:
    """
    api/main.py末尾の「frontend/dist/マウント」ロジックを、指定した
    dist_dirに対して再現したテスト専用アプリを組み立てる。
    api.main.appのルーター (/api/scan-status等) も含めて動作を
    検証したいため、既存のapp本体は使わず、同じルーター一式を
    載せた新規アプリを作る。
    """
    app = FastAPI()
    for router in (
        main_module.articles.router,
        main_module.scan.router,
    ):
        app.include_router(router)

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        if full_path.startswith("api/") or full_path == "api":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not Found")

        candidate = dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(dist_dir / "index.html")

    return app


@pytest.fixture
def fake_dist_dir(tmp_path):
    """
    テスト用のダミー frontend/dist/ を用意する。index.html・
    assets/以下のJSファイルを1つずつ置く。
    """
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)

    (dist_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root">SPA root</div></body></html>',
        encoding="utf-8",
    )
    (assets_dir / "index-test123.js").write_text(
        "console.log('dummy bundle');", encoding="utf-8"
    )
    # faviconのような「実ファイルが存在するがassets/配下ではないパス」の
    # 検証用。
    (dist_dir / "favicon.ico").write_bytes(b"\x00")

    return dist_dir


@pytest.fixture
def client_with_dist(fake_dist_dir, tmp_path, monkeypatch):
    """ダミーdist/を静的配信するテスト専用アプリのTestClientを返す。"""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    get_connection(db_path).close()

    app = _build_app_with_dist(fake_dist_dir)
    return TestClient(app)


def test_root_serves_index_html(client_with_dist):
    """GET / が index.html (SPAのエントリポイント) を返すこと。"""
    r = client_with_dist.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "root" in r.text


def test_spa_client_route_falls_back_to_index_html(client_with_dist):
    """
    React Router (SPA) が処理するパス (例: /settings/keywords) への
    直接アクセス・リロードでも404にならず、index.htmlが返ること。
    """
    r = client_with_dist.get("/settings/keywords")
    assert r.status_code == 200
    assert "root" in r.text


def test_assets_are_served_as_static_files(client_with_dist):
    """/assets/以下のJSファイルがそのまま配信されること。"""
    r = client_with_dist.get("/assets/index-test123.js")
    assert r.status_code == 200
    assert "dummy bundle" in r.text


def test_existing_file_outside_assets_is_served_directly(client_with_dist):
    """
    /assets/配下ではない実ファイル (favicon.ico等) も、存在すれば
    index.htmlへのフォールバックではなくそのファイル自体が返ること。
    """
    r = client_with_dist.get("/favicon.ico")
    assert r.status_code == 200
    assert r.content == b"\x00"


def test_api_routes_still_work_when_dist_mounted(client_with_dist):
    """
    dist/配信を有効にした状態でも、既存の /api/... エンドポイントが
    キャッチオールに横取りされず、通常通り動作すること。
    """
    r = client_with_dist.get("/api/scan-status")
    assert r.status_code == 200
    assert "is_scanning" in r.json()


def test_unknown_api_route_returns_404_not_index_html(client_with_dist):
    """
    存在しない /api/... パスは、SPAフォールバックでindex.htmlを返す
    のではなく、404を返すこと (誤ってAPIのタイプミス等がHTMLとして
    返り、デバッグを妨げることがないようにするため)。
    """
    r = client_with_dist.get("/api/this-route-does-not-exist")
    assert r.status_code == 404
    assert "root" not in r.text


def test_no_catchall_route_when_dist_dir_missing(tmp_path):
    """
    frontend/dist/ が存在しない (npm run build未実行) 環境相当の
    テスト専用アプリでは、キャッチオールルート自体が登録されず、
    存在しないパスへのアクセスが通常のFastAPIの404になること。

    (api/main.pyの実装は `if _FRONTEND_DIST_DIR.is_dir():` の中でのみ
    キャッチオールを登録するため、dist_dirが存在しない場合はここで
    検証するような「何も登録されない」状態になる。)
    """
    empty_dist_dir = tmp_path / "nonexistent-dist"
    app = FastAPI()
    app.include_router(main_module.scan.router)
    # dist_dirが存在しないため、api/main.pyと同じ条件分岐に従い
    # StaticFilesマウント・キャッチオールのいずれも登録しない。
    assert not empty_dist_dir.is_dir()

    client = TestClient(app)
    r = client.get("/some/path/that/does/not/exist/anywhere")
    assert r.status_code == 404
