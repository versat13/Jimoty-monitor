"""
NGワードに関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from filters.recompute import recompute_all_filter_flags

router = APIRouter(tags=["ng-keywords"])


class NgKeywordOut(BaseModel):
    id: int
    keyword: str
    is_active: bool


class NgKeywordIn(BaseModel):
    keyword: str


@router.get("/api/ng-keywords", response_model=list[NgKeywordOut])
def list_ng_keywords():
    conn = get_db()
    rows = conn.execute("SELECT * FROM ng_keywords ORDER BY id DESC").fetchall()
    conn.close()
    return [NgKeywordOut(id=r["id"], keyword=r["keyword"], is_active=bool(r["is_active"])) for r in rows]


@router.post("/api/ng-keywords", response_model=NgKeywordOut, status_code=201)
def create_ng_keyword(payload: NgKeywordIn):
    conn = get_db()
    cursor = conn.execute("INSERT INTO ng_keywords (keyword) VALUES (?)", (payload.keyword,))
    conn.commit()
    new_id = cursor.lastrowid
    # 2026-09-05新設: 登録直後にDB内の既存投稿へ即座に反映する
    # (巡回を待たずに一覧上のNG表示が切り替わるようにするため)。
    recompute_all_filter_flags(conn)
    conn.close()
    return NgKeywordOut(id=new_id, keyword=payload.keyword, is_active=True)


@router.delete("/api/ng-keywords/{keyword_id}", status_code=204)
def delete_ng_keyword(keyword_id: int):
    conn = get_db()
    conn.execute("DELETE FROM ng_keywords WHERE id = ?", (keyword_id,))
    conn.commit()
    recompute_all_filter_flags(conn)
    conn.close()


@router.patch("/api/ng-keywords/{keyword_id}/toggle", response_model=NgKeywordOut)
def toggle_ng_keyword(keyword_id: int):
    """is_activeを反転させる (無効化/再有効化)。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM ng_keywords WHERE id = ?", (keyword_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="NGワードが見つかりません")
    new_state = 0 if row["is_active"] else 1
    conn.execute("UPDATE ng_keywords SET is_active = ? WHERE id = ?", (new_state, keyword_id))
    conn.commit()
    recompute_all_filter_flags(conn)
    conn.close()
    return NgKeywordOut(id=keyword_id, keyword=row["keyword"], is_active=bool(new_state))

