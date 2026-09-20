"""
保存期間削除の設定に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["settings-retention"])


class RetentionSettingsOut(BaseModel):
    enabled: bool
    retention_days: int


class RetentionSettingsIn(BaseModel):
    enabled: bool
    retention_days: int


@router.get("/api/settings/retention", response_model=RetentionSettingsOut)
def get_retention_settings_endpoint():
    """現在の保存期間削除設定を返す。"""
    from repository.scan_settings_repository import get_retention_settings

    conn = get_db()
    settings = get_retention_settings(conn)
    conn.close()
    return RetentionSettingsOut(enabled=settings.enabled, retention_days=settings.retention_days)


@router.put("/api/settings/retention", response_model=RetentionSettingsOut)
def update_retention_settings_endpoint(payload: RetentionSettingsIn):
    """
    保存期間削除の設定を更新する (2026-09-11新設)。

    他の設定タブ (取得範囲・自動更新・地域) には一切触れない。
    enabled=Falseの間は、巡回のたびに行われる保存期間削除処理自体が
    スキップされる (scheduler.job.run_scan_with_range参照)。
    """
    from repository.scan_settings_repository import update_retention_settings

    conn = get_db()
    try:
        settings = update_retention_settings(
            conn, enabled=payload.enabled, retention_days=payload.retention_days
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=422, detail=str(e))
    conn.close()
    return RetentionSettingsOut(enabled=settings.enabled, retention_days=settings.retention_days)
