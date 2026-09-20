"""
監視対象の地域設定に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["settings-region"])


class RegionSettingsOut(BaseModel):
    prefecture: str
    area_id: str | None
    area_name: str | None


class RegionSettingsIn(BaseModel):
    prefecture: str
    # area_id/area_nameは両方指定 (市区町村を絞る) か、両方省略
    # (都道府県全域を監視) のどちらか。
    area_id: str | None = None
    area_name: str | None = None


@router.get("/api/settings/region", response_model=RegionSettingsOut)
def get_region_settings_endpoint():
    """現在の監視対象の地域 (都道府県・市区町村) を返す。"""
    from repository.scan_settings_repository import get_monitored_target

    conn = get_db()
    target = get_monitored_target(conn)
    conn.close()
    return RegionSettingsOut(
        prefecture=target.prefecture,
        area_id=target.area_id,
        area_name=target.area_name,
    )


@router.put("/api/settings/region", response_model=RegionSettingsOut)
def update_region_settings_endpoint(payload: RegionSettingsIn):
    """
    監視対象の地域 (都道府県・市区町村) を更新する (2026-09-10新設)。

    カテゴリ・取得範囲・自動更新間隔には一切触れない (他の設定タブと
    同様、更新対象の列ごとに専用関数を分ける設計方針を踏襲)。
    area_id/area_nameを両方省略すると「都道府県のみ監視 (市区町村を
    絞らない)」になる。
    """
    from repository.scan_settings_repository import update_monitored_target

    conn = get_db()
    try:
        target = update_monitored_target(
            conn,
            prefecture=payload.prefecture,
            area_id=payload.area_id,
            area_name=payload.area_name,
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=422, detail=str(e))
    conn.close()
    return RegionSettingsOut(
        prefecture=target.prefecture,
        area_id=target.area_id,
        area_name=target.area_name,
    )


class AreaOptionOut(BaseModel):
    area_id: str
    area_name: str
    display_name: str


class AreaOptionsOut(BaseModel):
    prefecture: str
    options: list[AreaOptionOut]
    fetched_at: str | None  # 最後に取得した日時。まだ一度も取得していなければNone


@router.get("/api/settings/region/areas", response_model=AreaOptionsOut)
def get_area_options_endpoint(prefecture: str):
    """
    指定した都道府県の市区町村候補一覧 (DBキャッシュ) を返す
    (2026-09-12新設)。

    キャッシュが無い (まだ一度も取得していない) 場合、optionsは空リスト
    になる。フロントエンドはこの場合「公式から市区町村を取得する」
    ボタンを案内する。
    """
    from repository.area_options_repository import get_area_options, get_area_options_fetched_at

    conn = get_db()
    options = get_area_options(conn, prefecture)
    fetched_at = get_area_options_fetched_at(conn, prefecture)
    conn.close()

    return AreaOptionsOut(
        prefecture=prefecture,
        options=[
            AreaOptionOut(area_id=o.area_id, area_name=o.area_name, display_name=o.display_name)
            for o in options
        ],
        fetched_at=fetched_at,
    )


@router.post("/api/settings/region/fetch-areas", response_model=AreaOptionsOut)
def fetch_area_options_endpoint(prefecture: str):
    """
    指定した都道府県の市区町村候補を、実際にジモティーへアクセスして
    取得し直す (2026-09-12新設。設定画面「地域」タブの「公式から
    市区町村を取得する」ボタン)。

    取得元URL・HTML構造の詳細は scraper.area_list_parser の
    モジュールdocstring参照 (2026-09-12にユーザーが実機確認した
    構造に基づく)。取得結果は repository.area_options_repository に
    丸ごと置き換えて保存する (古い候補は消える)。

    このエンドポイントはユーザーの明示的なボタン操作でのみ呼ばれる
    想定であり、自動更新や巡回処理からは呼ばれない (無駄なアクセスを
    避けるため、都道府県ごとに1回はユーザー操作が必要という設計)。
    """
    from repository.area_options_repository import get_area_options_fetched_at, replace_area_options
    from scraper.area_list_parser import parse_area_list_page
    from scraper.fetch import FetchError, build_client, fetch_html

    url = f"https://jmty.jp/{prefecture}/sale"
    try:
        with build_client() as client:
            html = fetch_html(client, url)
    except FetchError as e:
        raise HTTPException(status_code=502, detail=f"市区町村一覧の取得に失敗しました: {e}")

    options = parse_area_list_page(html)
    if not options:
        raise HTTPException(
            status_code=502,
            detail="市区町村一覧が見つかりませんでした。都道府県の指定が正しいか確認してください。",
        )

    conn = get_db()
    replace_area_options(conn, prefecture, options)
    fetched_at = get_area_options_fetched_at(conn, prefecture)
    conn.close()

    return AreaOptionsOut(
        prefecture=prefecture,
        options=[
            AreaOptionOut(area_id=o.area_id, area_name=o.area_name, display_name=o.display_name)
            for o in options
        ],
        fetched_at=fetched_at,
    )

