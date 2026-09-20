"""
簡易フィルタの検索履歴に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["search-history"])


class SearchHistoryOut(BaseModel):
    queries: list[str]


class SearchHistoryIn(BaseModel):
    query: str


@router.get("/api/search-history", response_model=SearchHistoryOut)
def get_search_history_endpoint():
    from repository.pickup_search_repository import list_search_history

    conn = get_db()
    queries = list_search_history(conn)
    conn.close()
    return SearchHistoryOut(queries=queries)


@router.post("/api/search-history", response_model=SearchHistoryOut, status_code=201)
def add_search_history_endpoint(payload: SearchHistoryIn):
    from repository.pickup_search_repository import add_search_history, list_search_history

    conn = get_db()
    add_search_history(conn, payload.query)
    queries = list_search_history(conn)
    conn.close()
    return SearchHistoryOut(queries=queries)


@router.delete("/api/search-history", status_code=204)
def clear_search_history_endpoint():
    from repository.pickup_search_repository import clear_search_history

    conn = get_db()
    clear_search_history(conn)
    conn.close()

