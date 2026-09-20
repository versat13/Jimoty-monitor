"""
ウォッチリスト（投稿単位）に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import get_db
from repository.watchlist_repository import add_watch, clear_watches, remove_watch

router = APIRouter(tags=["watches"])


class WatchIn(BaseModel):
    memo: str | None = None


class ClearWatchesIn(BaseModel):
    article_ids: list[str] | None = None  # Noneなら全件解除


class ClearWatchesOut(BaseModel):
    cleared_count: int


@router.put("/api/articles/{article_id}/watch", status_code=204)
def watch_article(article_id: str, payload: WatchIn = WatchIn()):
    """投稿をウォッチリストに追加する（既に追加済みなら何もしない）。"""
    conn = get_db()
    add_watch(conn, article_id, memo=payload.memo)
    conn.commit()
    conn.close()


@router.delete("/api/articles/{article_id}/watch", status_code=204)
def unwatch_article(article_id: str):
    """投稿をウォッチリストから解除する。"""
    conn = get_db()
    remove_watch(conn, article_id)
    conn.commit()
    conn.close()


@router.post("/api/watches/clear", response_model=ClearWatchesOut)
def clear_watchlist(payload: ClearWatchesIn = ClearWatchesIn()):
    """
    ウォッチリストを一括解除する（「問い合わせ終了したら一括で消せる
    ボタン」向け）。article_idsを指定すればその投稿のみ、省略すれば全件。
    """
    conn = get_db()
    count = clear_watches(conn, article_ids=payload.article_ids)
    conn.commit()
    conn.close()
    return ClearWatchesOut(cleared_count=count)
