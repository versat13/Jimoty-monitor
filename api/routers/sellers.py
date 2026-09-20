"""
出品者に関するエンドポイント (api/main.py から分割、2026-09-13)。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from api.schemas import ArticleOut, SellerOut, row_to_article_out, row_to_seller_out
from repository.watchlist_repository import get_watched_article_ids

router = APIRouter(tags=["sellers"])


@router.get("/api/sellers/{seller_id}", response_model=SellerOut)
def get_seller(seller_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="出品者が見つかりません")
    return row_to_seller_out(row)


@router.post("/api/sellers/{seller_id}/fetch-profile", response_model=SellerOut)
def fetch_seller_profile(seller_id: str):
    """
    出品者のプロフィールページを取得し、詳細情報 (全文紹介文・登録日・
    居住区・職業・評価内訳) で sellers テーブルを更新する。

    「見るまでは取らない」設計 (2026-08-30 設計合意事項)。
    このエンドポイントは呼ばれたら常に取得する (無条件)。
    「続きを読む」(未取得時のみ取得したい) と「更新」(常に取得したい)
    の使い分けはフロントエンド側 (SellerPanel.jsx の handleReadMore /
    handleRefresh) が profile_fetched_at を見て判断し、取得すべきと
    判断した場合にのみこのエンドポイントを呼ぶ。

    実際の取得・DB更新処理は scheduler/job.py の
    fetch_seller_profile_on_demand() に委譲する (巡回ジョブ側からも
    将来再利用できるようにするため)。

    この関数は同期的にHTTPリクエストを行うため、応答まで約1秒程度
    かかりうる。呼び出し元 (フロントエンド) はローディング表示を
    必須とすること。取得に失敗した場合は502を返し、
    「更新しました」という嘘の成功表示を避ける。
    """
    from scheduler.job import fetch_seller_profile_on_demand
    from scraper.fetch import build_client

    conn = get_db()
    row = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="出品者が見つかりません")

    with build_client() as client:
        success = fetch_seller_profile_on_demand(conn, client, seller_id)

    if not success:
        conn.close()
        raise HTTPException(status_code=502, detail="プロフィールページの取得に失敗しました")

    updated_row = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    conn.close()
    return row_to_seller_out(updated_row)


@router.get("/api/sellers/{seller_id}/articles", response_model=list[ArticleOut])
def get_seller_articles(seller_id: str):
    """指定した出品者の投稿一覧 (仕様書5-4「良い出品者の他の投稿を見る」導線)。"""
    conn = get_db()
    watched_ids = get_watched_article_ids(conn)
    rows = conn.execute(
        """
        SELECT a.*, s.seller_name AS seller_name
        FROM active_articles a
        LEFT JOIN sellers s ON a.seller_id = s.seller_id
        WHERE a.seller_id = ?
        ORDER BY a.last_seen_at DESC
        """,
        (seller_id,),
    ).fetchall()
    conn.close()
    return [row_to_article_out(r, watched_ids) for r in rows]


class SellerOtherArticleOut(BaseModel):
    """
    プロフィールページの投稿一覧1件分 (seller_other_articles由来)。

    2026-09-04 新設。ArticleOutとの違い: これは公式プロフィールページの
    サマリ情報のみで、NGフィルタ判定・is_watched等は適用されていない
    (db/schema.sql の seller_other_articles テーブルコメント参照)。
    """

    article_id: str
    url: str | None
    listing_type: str | None
    title: str | None
    price: int | None
    location: str | None
    description_short: str | None
    updated_date_raw: str | None


@router.get("/api/sellers/{seller_id}/other-articles", response_model=list[SellerOtherArticleOut])
def get_seller_other_articles_endpoint(seller_id: str):
    """
    指定した出品者の、公式プロフィールページに載っている投稿一覧
    (2026-09-04 新設)。

    /api/sellers/{seller_id}/articles (active_articles由来、監視ツールが
    偶然検知した投稿のみ) とは別物。こちらは「続きを読む」「更新」で
    プロフィールページを取得した際に保存された、公式プロフィールページ
    の全投稿一覧 (seller_other_articles由来)。プロフィールを一度も
    取得していない出品者では空配列を返す。
    """
    conn = get_db()
    from repository.seller_repository import get_seller_other_articles
    rows = get_seller_other_articles(conn, seller_id)
    conn.close()
    return [
        SellerOtherArticleOut(
            article_id=row["article_id"],
            url=row["url"],
            listing_type=row["listing_type"],
            title=row["title"],
            price=row["price"],
            location=row["location"],
            description_short=row["description_short"],
            updated_date_raw=row["updated_date_raw"],
        )
        for row in rows
    ]
