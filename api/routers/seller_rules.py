"""
NGユーザー／監視ユーザーに関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from filters.recompute import recompute_all_filter_flags

router = APIRouter(tags=["seller-rules"])


class SellerRuleOut(BaseModel):
    id: int
    seller_id: str
    seller_name: str | None
    rule_type: Literal["ng", "watch"]
    memo: str | None
    is_active: bool


class SellerRuleIn(BaseModel):
    seller_id: str
    seller_name: str | None = None
    rule_type: Literal["ng", "watch"]
    memo: str | None = None


@router.get("/api/seller-rules", response_model=list[SellerRuleOut])
def list_seller_rules(rule_type: Literal["ng", "watch", "all"] = "all"):
    """
    2026-09-05: rule_type="all"の場合、以前は単純にid DESC (登録した
    順)だったため、NGユーザーと監視ユーザーが登録順のまま混在して
    表示されていた。設定画面で見分けにくいという指摘を受け、
    「NGユーザー全員 (その中で登録順) → 監視ユーザー全員 (その中で
    登録順)」の順に固定した。rule_type='ng' が 'watch' よりアルファ
    ベット順で先に来ることを利用し、ORDER BY rule_type ASC, id DESC
    としている。
    """
    conn = get_db()
    if rule_type == "all":
        rows = conn.execute(
            "SELECT * FROM seller_rules ORDER BY rule_type ASC, id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM seller_rules WHERE rule_type = ? ORDER BY id DESC", (rule_type,)
        ).fetchall()
    conn.close()
    return [
        SellerRuleOut(
            id=r["id"], seller_id=r["seller_id"], seller_name=r["seller_name"],
            rule_type=r["rule_type"], memo=r["memo"], is_active=bool(r["is_active"]),
        )
        for r in rows
    ]


@router.get("/api/sellers/{seller_id}/rule", response_model=SellerRuleOut | None)
def get_seller_rule(seller_id: str):
    """
    指定した出品者の現在の登録状態 (NG／監視) を1件返す。未登録なら null。

    2026-09-04新設。出品者パネル (SellerPanel.jsx) にNG登録・監視登録
    ボタンを常時表示するため、パネルを開いた時点での現在状態を取得する
    目的。seller_rules.seller_id は一意制約があるため、出品者ごとに
    レコードは最大1件しか存在しない。
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM seller_rules WHERE seller_id = ?", (seller_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return SellerRuleOut(
        id=row["id"], seller_id=row["seller_id"], seller_name=row["seller_name"],
        rule_type=row["rule_type"], memo=row["memo"], is_active=bool(row["is_active"]),
    )


@router.post("/api/seller-rules", response_model=SellerRuleOut, status_code=201)
def create_seller_rule(payload: SellerRuleIn):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO seller_rules (seller_id, seller_name, rule_type, memo) VALUES (?, ?, ?, ?)",
            (payload.seller_id, payload.seller_name, payload.rule_type, payload.memo),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="この出品者は既に登録されています")
    new_id = cursor.lastrowid
    # 2026-09-05新設: NG登録の場合、その出品者の既存投稿へ即座に
    # 反映する (監視登録の場合はis_hidden_by_seller_ruleに影響しないが、
    # 判定関数は軽量なので rule_type を問わず一律で呼び出す)。
    recompute_all_filter_flags(conn)
    conn.close()
    return SellerRuleOut(
        id=new_id, seller_id=payload.seller_id, seller_name=payload.seller_name,
        rule_type=payload.rule_type, memo=payload.memo, is_active=True,
    )


@router.delete("/api/seller-rules/{rule_id}", status_code=204)
def delete_seller_rule(rule_id: int):
    conn = get_db()
    conn.execute("DELETE FROM seller_rules WHERE id = ?", (rule_id,))
    conn.commit()
    recompute_all_filter_flags(conn)
    conn.close()
