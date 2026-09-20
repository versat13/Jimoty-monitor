"""
取得範囲設定・自動更新間隔設定に関するエンドポイント
(api/main.py から分割、2026-09-13)。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["settings-scan-range"])


class ScanRangeSettingsOut(BaseModel):
    scan_range_mode: Literal["pages", "days"]
    scan_range_value: int
    auto_scan_interval_minutes: int | None


class ScanRangeSettingsIn(BaseModel):
    scan_range_mode: Literal["pages", "days"]
    scan_range_value: int


class AutoScanIntervalIn(BaseModel):
    # 2026-09-08時点では設定項目の器のみ。実際にこの値を使って
    # 自動巡回を定期実行する仕組みは未実装 (今後の対応予定)。
    auto_scan_interval_minutes: int | None = None


@router.get("/api/settings/scan-range", response_model=ScanRangeSettingsOut)
def get_scan_range_settings_endpoint():
    """
    現在の取得範囲設定 (ページ数 or 過去n日、排他) を返す。
    未設定ならデフォルト値 (pages, 1件=1ページ目のみ、従来の挙動) を返す。

    2026-09-08: レスポンスには自動更新間隔 (auto_scan_interval_minutes)
    も引き続き含める (「自動更新」タブがこの値を表示するために読む)。
    更新用のエンドポイントのみ、取得範囲用/自動更新用に分割した
    (下記 update_scan_range_settings_endpoint /
    update_auto_scan_interval_endpoint のdocstring参照)。
    """
    from repository.scan_settings_repository import get_scan_range_settings

    conn = get_db()
    settings = get_scan_range_settings(conn)
    conn.close()
    return ScanRangeSettingsOut(
        scan_range_mode=settings.scan_range_mode,
        scan_range_value=settings.scan_range_value,
        auto_scan_interval_minutes=settings.auto_scan_interval_minutes,
    )


@router.put("/api/settings/scan-range", response_model=ScanRangeSettingsOut)
def update_scan_range_settings_endpoint(payload: ScanRangeSettingsIn):
    """
    取得範囲設定 (scan_range_mode / scan_range_value) を更新する。
    scan_range_mode="pages" のとき scan_range_value はページ数の上限、
    "days" のとき遡る日数を表す (排他選択。両方同時に上限を課す運用は
    現時点でしない)。

    2026-09-08: 以前はこのエンドポイントで auto_scan_interval_minutes
    も一緒に更新していたが、「取得範囲」タブと「自動更新」タブを別々の
    画面/端末から編集した場合に片方の保存でもう片方の値を意図せず
    上書きしてしまう懸念があったため、自動更新間隔の更新は
    update_auto_scan_interval_endpoint (PUT /api/settings/auto-scan-interval)
    に分離した。このエンドポイントは update_scan_range_only() を使い、
    取得範囲にのみ触れる (auto_scan_interval_minutes をNoneで上書き
    してしまわないようにするため、汎用の update_scan_range_settings()
    ではなく専用関数を使っている点に注意)。
    """
    from repository.scan_settings_repository import update_scan_range_only

    conn = get_db()
    try:
        settings = update_scan_range_only(
            conn,
            scan_range_mode=payload.scan_range_mode,
            scan_range_value=payload.scan_range_value,
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=422, detail=str(e))
    conn.close()
    return ScanRangeSettingsOut(
        scan_range_mode=settings.scan_range_mode,
        scan_range_value=settings.scan_range_value,
        auto_scan_interval_minutes=settings.auto_scan_interval_minutes,
    )


@router.put("/api/settings/auto-scan-interval", response_model=ScanRangeSettingsOut)
def update_auto_scan_interval_endpoint(payload: AutoScanIntervalIn):
    """
    自動更新間隔 (auto_scan_interval_minutes) のみを更新する
    (2026-09-08新設)。取得範囲 (scan_range_mode / scan_range_value)
    には一切触れない。設定画面の「自動更新」タブから呼ばれる想定。
    """
    from repository.scan_settings_repository import update_auto_scan_interval

    conn = get_db()
    try:
        settings = update_auto_scan_interval(
            conn,
            auto_scan_interval_minutes=payload.auto_scan_interval_minutes,
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=422, detail=str(e))
    conn.close()
    return ScanRangeSettingsOut(
        scan_range_mode=settings.scan_range_mode,
        scan_range_value=settings.scan_range_value,
        auto_scan_interval_minutes=settings.auto_scan_interval_minutes,
    )

