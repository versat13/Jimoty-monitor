"""
検索タブ（ピックアップ検索）の保存条件に関するエンドポイント
(api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["settings-pickup-search"])


class PickupSearchOut(BaseModel):
    search_expression: str
    include_words: list[str]
    exclude_words: list[str]
    is_builder_synced: bool


class PickupSearchIn(BaseModel):
    search_expression: str
    include_words: list[str] = []
    exclude_words: list[str] = []
    is_builder_synced: bool = True


@router.get("/api/settings/pickup-search", response_model=PickupSearchOut)
def get_pickup_search_endpoint():
    """
    「検索」タブの現在の保存条件を返す。未設定ならすべて空の
    デフォルト値を返す (絞り込みなし)。
    """
    from repository.pickup_search_repository import get_pickup_search

    conn = get_db()
    settings = get_pickup_search(conn)
    conn.close()
    return PickupSearchOut(
        search_expression=settings.search_expression,
        include_words=settings.include_words,
        exclude_words=settings.exclude_words,
        is_builder_synced=settings.is_builder_synced,
    )


@router.put("/api/settings/pickup-search", response_model=PickupSearchOut)
def update_pickup_search_endpoint(payload: PickupSearchIn):
    """
    「検索」タブの条件を更新する (常に1件のみ保持)。

    search_expression は保存前に re.compile() で正規表現として
    妥当か検証する。フロントエンドの正規表現ビルダーが生成したもの
    でも、手直し後の生の入力でも、ここで一律に検証することで
    「検索タブを開いたら不正な式のせいでエラーになる」事態を防ぐ。
    """
    import re

    try:
        if payload.search_expression:
            re.compile(payload.search_expression)
    except re.error as e:
        raise HTTPException(
            status_code=422, detail=f"正規表現として不正です: {e}"
        )

    from repository.pickup_search_repository import update_pickup_search

    conn = get_db()
    settings = update_pickup_search(
        conn,
        search_expression=payload.search_expression,
        include_words=payload.include_words,
        exclude_words=payload.exclude_words,
        is_builder_synced=payload.is_builder_synced,
    )
    conn.close()
    return PickupSearchOut(
        search_expression=settings.search_expression,
        include_words=settings.include_words,
        exclude_words=settings.exclude_words,
        is_builder_synced=settings.is_builder_synced,
    )
