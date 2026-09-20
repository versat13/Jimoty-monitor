"""
NGカテゴリに関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import get_db
from filters.recompute import recompute_all_filter_flags

router = APIRouter(tags=["ng-categories"])


class NgCategoryOut(BaseModel):
    id: int
    category_id: str
    category_name: str | None
    category_level: Literal["parent", "mid", "leaf"] = "leaf"
    is_active: bool


class NgCategoryIn(BaseModel):
    category_id: str
    category_name: str | None = None
    category_level: Literal["parent", "mid", "leaf"] = "leaf"


@router.get("/api/ng-categories", response_model=list[NgCategoryOut])
def list_ng_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM ng_categories ORDER BY id DESC").fetchall()
    conn.close()
    return [
        NgCategoryOut(
            id=r["id"], category_id=r["category_id"], category_name=r["category_name"],
            category_level=r["category_level"], is_active=bool(r["is_active"]),
        )
        for r in rows
    ]


@router.post("/api/ng-categories", response_model=NgCategoryOut, status_code=201)
def create_ng_category(payload: NgCategoryIn):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO ng_categories (category_id, category_name, category_level) VALUES (?, ?, ?)",
        (payload.category_id, payload.category_name, payload.category_level),
    )
    conn.commit()
    new_id = cursor.lastrowid
    # 2026-09-05新設: 登録直後にDB内の既存投稿へ即座に反映する。
    recompute_all_filter_flags(conn)
    conn.close()
    return NgCategoryOut(
        id=new_id, category_id=payload.category_id, category_name=payload.category_name,
        category_level=payload.category_level, is_active=True,
    )


@router.delete("/api/ng-categories/{category_row_id}", status_code=204)
def delete_ng_category(category_row_id: int):
    conn = get_db()
    conn.execute("DELETE FROM ng_categories WHERE id = ?", (category_row_id,))
    conn.commit()
    recompute_all_filter_flags(conn)
    conn.close()


class UsedCategoryOut(BaseModel):
    category_id: str
    category_name: str | None
    category_level: Literal["parent", "mid", "leaf"]
    # leafの場合のみ、その親ジャンルの情報を付与する (表示順序を
    # 「カテゴリ→ジャンル→配下のサブジャンル」にするための手がかり。
    # フロントエンドはこれを使ってサブジャンルを親ジャンルの下に
    # まとめて表示する)。
    parent_mid_id: str | None = None
    parent_mid_name: str | None = None
    # 2026-09-09拡張: midの場合、その親カテゴリ(大カテゴリ)の情報も
    # 付与する。フロントエンドで「大カテゴリ→ジャンル→サブジャンル」の
    # 完全な入れ子表示を組み立てるために必要 (ユーザー要望:
    # 「大カテゴリの中にジャンル、その中にサブジャンルという並びに
    # したい」)。1つのジャンルが複数の大カテゴリに属する投稿を
    # 監視している場合 (通常は無いはずだが、データ上あり得るため)、
    # 最初に見つかった大カテゴリの組み合わせを代表として採用する。
    parent_id: str | None = None
    parent_name: str | None = None


@router.get("/api/categories/used", response_model=list[UsedCategoryOut])
def list_used_categories():
    """
    実際にDBへ保存されている投稿から、出現済みのカテゴリ一覧を返す
    (2026-09-04新設)。

    ジモティー側にカテゴリ一覧を取得できるAPIが存在しないため、完全な
    カテゴリマスタは持てない。その代わり、このソフトが実際に監視して
    きた投稿が使っているカテゴリ・ジャンル・大カテゴリをDISTINCTで
    抽出して返す。設定画面のNGカテゴリ登録で、手打ち入力の補助
    (サジェスト) として使う目的。

    手打ち入力自体は引き続き可能なので、ここに出現しない
    (＝このDBがまだ見たことのない) category_idも登録できる。

    2026-09-08拡張: 大カテゴリ (category_parent_id)・ジャンル
    (category_mid_id、またはサブジャンル未指定でcategory_idに直接
    入っているジャンル)・サブジャンル (category_mid_idを伴う
    category_id) の3階層を区別して返すようにした
    (ユーザーとの打ち合わせで合意した「カテゴリ→ジャンル→サブジャンル
    の順で表示、それぞれ強調表示する」というUI要件に対応するため)。
    大カテゴリは個別ページのパンくずリストからのみ取得できるため、
    一覧のみ巡回している投稿では出現しない点に注意。

    2026-09-09拡張: ジャンル(mid)にも親の大カテゴリ情報
    (parent_id/parent_name) を付与するようにした。フロントエンドで
    「大カテゴリ→ジャンル→サブジャンル」の完全な入れ子表示を組み立てる
    ため (ユーザー要望)。
    """
    conn = get_db()

    parent_rows = conn.execute(
        "SELECT DISTINCT category_parent_id AS id, category_parent_name AS name "
        "FROM active_articles WHERE category_parent_id IS NOT NULL ORDER BY id"
    ).fetchall()

    # ジャンル: category_mid_id (サブジャンルを伴う投稿の中間カテゴリ)
    # と、サブジャンル未指定でジャンルがそのまま category_id に入って
    # いる投稿の両方から集める。親の大カテゴリ情報も一緒に集計する
    # (GROUP BYで代表の1件を採用。同じジャンルIDに複数の大カテゴリが
    # 紐づくことは通常想定されないが、万一データが割れていても
    # 表示が壊れないよう、最初の1件を採用するだけにとどめる)。
    mid_rows = conn.execute(
        "SELECT category_mid_id AS id, category_mid_name AS name, "
        "MIN(category_parent_id) AS parent_id, "
        "MIN(category_parent_name) AS parent_name "
        "FROM active_articles WHERE category_mid_id IS NOT NULL "
        "GROUP BY category_mid_id, category_mid_name "
        "UNION "
        "SELECT category_id AS id, category_name AS name, "
        "MIN(category_parent_id) AS parent_id, "
        "MIN(category_parent_name) AS parent_name "
        "FROM active_articles WHERE category_mid_id IS NULL AND category_id IS NOT NULL "
        "GROUP BY category_id, category_name "
        "ORDER BY id"
    ).fetchall()

    # サブジャンル: category_mid_id を伴う投稿の category_id
    # (=詳細カテゴリ)。親ジャンルの情報も一緒に返す。
    leaf_rows = conn.execute(
        "SELECT DISTINCT category_id AS id, category_name AS name, "
        "category_mid_id AS parent_mid_id, category_mid_name AS parent_mid_name "
        "FROM active_articles "
        "WHERE category_mid_id IS NOT NULL AND category_id IS NOT NULL "
        "ORDER BY parent_mid_id, id"
    ).fetchall()

    conn.close()

    result = []
    result += [
        UsedCategoryOut(category_id=r["id"], category_name=r["name"], category_level="parent")
        for r in parent_rows
    ]
    result += [
        UsedCategoryOut(
            category_id=r["id"], category_name=r["name"], category_level="mid",
            parent_id=r["parent_id"], parent_name=r["parent_name"],
        )
        for r in mid_rows
    ]
    result += [
        UsedCategoryOut(
            category_id=r["id"], category_name=r["name"], category_level="leaf",
            parent_mid_id=r["parent_mid_id"], parent_mid_name=r["parent_mid_name"],
        )
        for r in leaf_rows
    ]
    return result
