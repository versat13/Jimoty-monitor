"""
設定のエクスポート/インポートに関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from filters.recompute import recompute_all_filter_flags

router = APIRouter(tags=["settings-export"])


class SettingsExportOut(BaseModel):
    format_version: int
    ng_keywords: list[dict]
    ng_categories: list[dict]
    seller_rules: list[dict]
    scan_state: dict | None
    pickup_search: dict | None
    discord_notification: dict | None = None


class SettingsImportIn(BaseModel):
    format_version: int
    ng_keywords: list[dict] = []
    ng_categories: list[dict] = []
    seller_rules: list[dict] = []
    scan_state: dict | None = None
    pickup_search: dict | None = None
    discord_notification: dict | None = None


@router.get("/api/settings/export", response_model=SettingsExportOut)
def export_settings_endpoint():
    """
    全設定をエクスポートする。レスポンスをそのままJSONファイルとして
    保存し、後日 (または別端末で) インポートに使うことを想定した形式。
    """
    from repository.settings_export_repository import export_all_settings

    conn = get_db()
    export = export_all_settings(conn)
    conn.close()
    return SettingsExportOut(
        format_version=export.format_version,
        ng_keywords=export.ng_keywords,
        ng_categories=export.ng_categories,
        seller_rules=export.seller_rules,
        scan_state=export.scan_state,
        pickup_search=export.pickup_search,
        discord_notification=export.discord_notification,
    )


@router.post("/api/settings/import", response_model=SettingsExportOut)
def import_settings_endpoint(payload: SettingsImportIn):
    """
    全設定をインポートする。既存の設定 (NGワード・NGカテゴリ・
    監視/NGユーザー・検索タブの条件) は全件削除され、インポート内容
    で完全に置き換わる (マージではない。ユーザー方針:「すべての設定を
    含めたものだけでよい」)。取得範囲・自動更新間隔は1行のみの
    テーブルのためUPSERTする。

    不正な形式の場合は422エラーとし、それ以前の項目も含めて
    一切コミットされない (repository層がトランザクション全体を
    1回のcommit()にまとめているため)。
    """
    from repository.settings_export_repository import SettingsImportError, import_all_settings

    conn = get_db()
    try:
        import_all_settings(
            conn,
            {
                "format_version": payload.format_version,
                "ng_keywords": payload.ng_keywords,
                "ng_categories": payload.ng_categories,
                "seller_rules": payload.seller_rules,
                "scan_state": payload.scan_state,
                "pickup_search": payload.pickup_search,
                "discord_notification": payload.discord_notification,
            },
        )
    except SettingsImportError as e:
        conn.close()
        raise HTTPException(status_code=422, detail=str(e))

    # 2026-09-08: NGワード・NGカテゴリの内容が変わるため、既存投稿への
    # 非表示フラグを即座に再計算する (NGワード/NGカテゴリ登録時と
    # 同様の扱い)。
    recompute_all_filter_flags(conn)

    from repository.settings_export_repository import export_all_settings

    export = export_all_settings(conn)
    conn.close()
    return SettingsExportOut(
        format_version=export.format_version,
        ng_keywords=export.ng_keywords,
        ng_categories=export.ng_categories,
        seller_rules=export.seller_rules,
        scan_state=export.scan_state,
        pickup_search=export.pickup_search,
        discord_notification=export.discord_notification,
    )
