"""
投稿一覧に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from api.schemas import ArticleOut, row_to_article_out
from repository.watchlist_repository import get_watched_article_ids

router = APIRouter(tags=["articles"])


@router.get("/api/articles", response_model=list[ArticleOut])
def list_articles(
    visibility: Literal[
        "visible", "hidden", "all", "watched", "watched_sellers", "watched_all"
    ] = "visible",
    status: Literal["active", "missing", "all"] = "active",
):
    """
    投稿一覧を返す。

    Args:
        visibility:
            "visible" (既定) - NGワード/NGカテゴリ/NGユーザーいずれにも
                該当しない投稿のみ (通常のユーザー閲覧画面向け)
            "hidden" - いずれかのNG判定でフラグが立っている投稿のみ
                (「非表示にした投稿を確認したい」場合向け)
            "all" - フィルタ結果を問わず全件
            "watched" - ウォッチリスト（投稿単位）に入れた投稿のみ。
                NG判定に関わらず必ず表示する
                (2026-08-24 合意事項: 明示的に選んだものはノイズ除去の
                対象にしない)
            "watched_sellers" - 監視ユーザー(seller_rules.rule_type='watch')
                の投稿のみ。こちらもNG判定に関わらず必ず表示する
            "watched_all" - "watched"と"watched_sellers"のOR
                (2026-09-04新設)。フロントエンドのタブ統合
                (「監視投稿」「監視ユーザー」を1つの「監視」タブに
                まとめる) に伴い追加。"watched"・"watched_sellers"は
                内部的なデータ構造・ライフサイクル (投稿単位は気軽に
                解除できるウォッチリスト、ユーザー単位は設定画面で
                明示管理する登録) が異なるため独立したテーブルの
                ままとし、この値は表示だけを合成する目的で存在する。
            仕様書5-4の原則により、取得・保存自体はフィルタ結果に
            関わらず必ず行われているため、いずれの指定でもデータが
            欠けていることはない。
        status: article_status ('active' / 'missing' / 'all')
    """
    conn = get_db()
    watched_ids = get_watched_article_ids(conn)

    query = """
        SELECT a.*, s.seller_name AS seller_name
        FROM active_articles a
        LEFT JOIN sellers s ON a.seller_id = s.seller_id
        WHERE 1=1
    """
    if status != "all":
        query += " AND a.article_status = :status"

    if visibility == "visible":
        query += (
            " AND a.is_hidden_by_keyword = 0"
            " AND a.is_hidden_by_category = 0"
            " AND a.is_hidden_by_seller_rule = 0"
        )
    elif visibility == "hidden":
        query += (
            " AND (a.is_hidden_by_keyword = 1"
            " OR a.is_hidden_by_category = 1"
            " OR a.is_hidden_by_seller_rule = 1)"
        )
    elif visibility == "watched":
        if not watched_ids:
            conn.close()
            return []
        placeholders = ",".join(f"'{aid}'" for aid in watched_ids)  # article_idはURLセーフな英数字のみ
        query += f" AND a.article_id IN ({placeholders})"
    elif visibility == "watched_sellers":
        query += (
            " AND a.seller_id IN ("
            "   SELECT seller_id FROM seller_rules"
            "   WHERE rule_type = 'watch' AND is_active = 1"
            " )"
        )
    elif visibility == "watched_all":
        watched_placeholders = (
            ",".join(f"'{aid}'" for aid in watched_ids) if watched_ids else None
        )
        watched_article_clause = (
            f"a.article_id IN ({watched_placeholders})" if watched_placeholders else "0"
        )
        query += (
            f" AND ({watched_article_clause}"
            " OR a.seller_id IN ("
            "   SELECT seller_id FROM seller_rules"
            "   WHERE rule_type = 'watch' AND is_active = 1"
            " ))"
        )

    # デフォルトの並び順は display_order (直近巡回での一覧出現順、
    # 2026-08-24新設) を採用する。「公式サイトと同じ並び順に戻したい」
    # というユーザー要望への対応。display_order が NULL の行
    # (display_orderカラム追加より前に登録された投稿など) は末尾に回す。
    query += " ORDER BY (a.display_order IS NULL), a.display_order ASC"

    rows = conn.execute(query, {"status": status}).fetchall()
    conn.close()
    return [row_to_article_out(r, watched_ids) for r in rows]


@router.get("/api/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: str):
    conn = get_db()
    watched_ids = get_watched_article_ids(conn)
    row = conn.execute(
        """
        SELECT a.*, s.seller_name AS seller_name
        FROM active_articles a
        LEFT JOIN sellers s ON a.seller_id = s.seller_id
        WHERE a.article_id = ?
        """,
        (article_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")
    return row_to_article_out(row, watched_ids)


class ConfirmStatusOut(BaseModel):
    """POST /api/articles/{article_id}/confirm-status のレスポンス。"""

    result: Literal["restored", "closed"]
    # 2026-09-11変更: "closed"の場合も削除しなくなったため、常に
    # 更新後のArticleOutを返す (以前は"deleted"の場合Noneだった)。
    article: ArticleOut | None


@router.post("/api/articles/{article_id}/confirm-status", response_model=ConfirmStatusOut)
def confirm_article_status(article_id: str):
    """
    「終了」タブの投稿1件について、個別ページへアクセスして
    まだ受付中か (restored) 本当に終了したか (closed) を確定させる
    (2026-09-04 新設)。

    設計思想 (ユーザーとの合意事項): 旧run_missing_check() のように
    missing状態の投稿全件を機械的に確認しに行くのではなく、ユーザーが
    「終了」タブを見て興味を持った投稿だけ、この関数で個別に
    アクセスする。これによりアクセス数の増加を最小限に抑える。

    - restored (まだ受付中だった): article_statusがactiveに戻る
      (2026-09-04 合意事項: 「公開中」タブに自動的に戻す)。更新後の
      ArticleOutを返す。
    - closed (本当に終了していた): 2026-09-11変更 (「終了」タブ
      再設計、ユーザーとの合意事項) により、以前のように
      active_articlesの行を物理削除するのではなく、
      missing_kind='confirmed_closed' のまま一覧に残すようにした。
      更新後のArticleOutを返す (以前の"deleted"はarticle=Noneだった)。
      いつまで残すかは別途、保存期間削除の設定 (missing_since基準)
      に委ねる。
    - 対象がmissing状態でない (既にactiveに戻っている等) 場合は404。
    """
    from scheduler.job import confirm_single_missing_article
    from scraper.fetch import build_client

    conn = get_db()
    row = conn.execute(
        "SELECT article_id FROM active_articles WHERE article_id = ? AND article_status = 'missing'",
        (article_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="「終了」状態の投稿が見つかりません")

    with build_client() as client:
        result = confirm_single_missing_article(conn, client, article_id)

    if result is None:
        conn.close()
        raise HTTPException(status_code=404, detail="「終了」状態の投稿が見つかりません")

    watched_ids = get_watched_article_ids(conn)
    updated_row = conn.execute(
        """
        SELECT a.*, s.seller_name AS seller_name
        FROM active_articles a
        LEFT JOIN sellers s ON a.seller_id = s.seller_id
        WHERE a.article_id = ?
        """,
        (article_id,),
    ).fetchone()
    conn.close()
    return ConfirmStatusOut(result=result, article=row_to_article_out(updated_row, watched_ids))


class PriceHistoryEntryOut(BaseModel):
    old_price: int | None
    new_price: int | None
    changed_at: str


@router.get("/api/articles/{article_id}/price-history", response_model=list[PriceHistoryEntryOut])
def get_price_history(article_id: str):
    """投稿の価格変化履歴を返す (投稿詳細ページでの表示用、2026-08-25新設)。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT old_price, new_price, changed_at FROM price_history"
        " WHERE article_id = ? ORDER BY changed_at ASC",
        (article_id,),
    ).fetchall()
    conn.close()
    return [
        PriceHistoryEntryOut(
            old_price=r["old_price"], new_price=r["new_price"], changed_at=r["changed_at"]
        )
        for r in rows
    ]


class DeletedArticleOut(BaseModel):
    article_id: str
    url: str
    list_title: str
    price: int | None
    prefecture: str | None
    area_name: str | None
    category_name: str | None
    thumbnail_url: str | None
    article_status: str
    first_seen_at: str | None
    last_seen_at: str | None
    deleted_at: str


@router.get("/api/articles-deleted-log", response_model=list[DeletedArticleOut])
def list_deleted_articles_endpoint():
    """
    保存期間切れで削除された投稿の履歴一覧を返す (2026-09-14新設)。

    repository.article_repository.purge_expired_articles() が削除の
    たびにスナップショットを残しており、このエンドポイントはそれを
    削除日時の新しい順に返すだけの薄い層。履歴自体もpurge実行時に
    保存期間を過ぎたものから削除されるため、常に「まだ保存期間内の
    削除履歴」のみが返る。
    """
    from repository.article_repository import list_deleted_articles

    conn = get_db()
    rows = list_deleted_articles(conn)
    conn.close()
    return [
        DeletedArticleOut(
            article_id=r["article_id"],
            url=r["url"],
            list_title=r["list_title"],
            price=r["price"],
            prefecture=r["prefecture"],
            area_name=r["area_name"],
            category_name=r["category_name"],
            thumbnail_url=r["thumbnail_url"],
            article_status=r["article_status"],
            first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"],
            deleted_at=r["deleted_at"],
        )
        for r in rows
    ]

