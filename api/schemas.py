"""
複数のルーターにまたがって使われる共通レスポンスモデル。

ArticleOut / _row_to_article_out は articles ルーターだけでなく、
sellers ルーター (出品者の投稿一覧) からも参照されるため、
どちらか一方のルーターファイルに置くのではなくここに集約する。
"""

import json
import sqlite3

from pydantic import BaseModel


class ArticleOut(BaseModel):
    article_id: str
    url: str
    list_title: str
    full_title: str | None
    price: int | None
    prefecture: str | None
    area_name: str | None
    station_name: str | None
    category_id: str | None
    category_name: str | None
    # 2026-09-08新設: 大カテゴリ・ジャンルも一覧表示に含める
    # (「大カテゴリ>ジャンル>サブジャンル」表記をフロントエンドで
    # 組み立てるため。category_idはサブジャンル(またはサブジャンル
    # 未指定時はジャンル)、category_mid_nameはジャンル、
    # category_parent_nameは大カテゴリに対応する)。
    category_mid_name: str | None = None
    category_parent_name: str | None = None
    tags: list[str]
    description_short: str | None
    description_full: str | None
    thumbnail_url: str | None
    favorite_count: int | None
    is_pr_slot: bool
    is_closed: bool
    seller_id: str | None
    seller_name: str | None
    is_hidden_by_keyword: bool
    is_hidden_by_category: bool
    is_hidden_by_seller_rule: bool
    matched_ng_keywords: list[str]
    article_status: str
    first_seen_at: str
    last_seen_at: str
    missing_since: str | None = None  # 2026-09-04: 「公開終了」タブの表示用
    is_watched: bool = False
    display_order: int | None = None
    created_datetime: str | None = None
    updated_datetime: str | None = None
    # 2026-09-07新設: 個別ページが実際に取得された日時。
    # 「投稿日・最終更新日が表示されない」不具合調査の一環で追加。
    # このフィールドがnullなら「個別ページ取得自体が一度も
    # 成功していない」ことが分かり、created_datetime等がnullである
    # ことの原因切り分けに使える (パース失敗なのか、そもそも
    # 個別ページ取得が実行されていないのかを見分けられる)。
    detail_fetched_at: str | None = None
    # 2026-09-10新設: 価格変更の累計回数。0なら「一度も値変更が
    # 確認されていない」ことを表し、フロントエンドはこの場合
    # 「n回目の値変更」ラベル自体を表示しない。UP/DOWNの方向性は
    # 持たず、回数のみ (ユーザーとの合意事項)。
    price_change_count: int = 0
    # 2026-09-11新設: 「終了」タブ再設計。article_status='missing'の
    # 投稿を、取得できた投稿群のdisplay_order範囲の内側で消えたか
    # (confirmed_closed。自動で個別ページ確認済み・確定)、末尾より
    # 後ろにいたか (range_uncertain。取得範囲の外に押し出されただけの
    # 可能性がある) で細分類する。article_status='active'の投稿では
    # 常にnull。詳細はrepository.article_repository.
    # mark_missing_articles() docstring参照。
    missing_kind: str | None = None


def row_to_article_out(row: sqlite3.Row, watched_ids: set[str] | None = None) -> ArticleOut:
    watched_ids = watched_ids or set()
    return ArticleOut(
        article_id=row["article_id"],
        url=row["url"],
        list_title=row["list_title"],
        full_title=row["full_title"],
        price=row["price"],
        prefecture=row["prefecture"],
        area_name=row["area_name"],
        station_name=row["station_name"],
        category_id=row["category_id"],
        category_name=row["category_name"],
        category_mid_name=row["category_mid_name"] if "category_mid_name" in row.keys() else None,
        category_parent_name=row["category_parent_name"] if "category_parent_name" in row.keys() else None,
        tags=json.loads(row["tags"]) if row["tags"] else [],
        description_short=row["description_short"],
        description_full=row["description_full"],
        thumbnail_url=row["thumbnail_url"],
        favorite_count=row["favorite_count"],
        is_pr_slot=bool(row["is_pr_slot"]),
        is_closed=bool(row["is_closed"]),
        seller_id=row["seller_id"],
        seller_name=row["seller_name"] if "seller_name" in row.keys() else None,
        is_hidden_by_keyword=bool(row["is_hidden_by_keyword"]),
        is_hidden_by_category=bool(row["is_hidden_by_category"]),
        is_hidden_by_seller_rule=bool(row["is_hidden_by_seller_rule"]),
        matched_ng_keywords=json.loads(row["matched_ng_keywords"]) if row["matched_ng_keywords"] else [],
        article_status=row["article_status"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        missing_since=row["missing_since"] if "missing_since" in row.keys() else None,
        is_watched=row["article_id"] in watched_ids,
        display_order=row["display_order"] if "display_order" in row.keys() else None,
        created_datetime=row["created_datetime"] if "created_datetime" in row.keys() else None,
        updated_datetime=row["updated_datetime"] if "updated_datetime" in row.keys() else None,
        detail_fetched_at=row["detail_fetched_at"] if "detail_fetched_at" in row.keys() else None,
        price_change_count=row["price_change_count"] if "price_change_count" in row.keys() else 0,
        missing_kind=row["missing_kind"] if "missing_kind" in row.keys() else None,
    )


class SellerOut(BaseModel):
    seller_id: str
    seller_name: str | None
    seller_profile_url: str | None
    gender: str | None
    post_count: int | None
    rating: float | None
    rating_count: int | None
    rating_good: int | None
    rating_normal: int | None
    rating_bad: int | None
    identity_verified: bool
    phone_verified: bool
    description: str | None
    registration_date_raw: str | None
    residential_area: str | None
    occupation: str | None
    profile_fetched_at: str | None


def row_to_seller_out(row: sqlite3.Row) -> SellerOut:
    return SellerOut(
        seller_id=row["seller_id"],
        seller_name=row["seller_name"],
        seller_profile_url=row["seller_profile_url"],
        gender=row["gender"],
        post_count=row["post_count"],
        rating=row["rating"],
        rating_count=row["rating_count"],
        rating_good=row["rating_good"],
        rating_normal=row["rating_normal"],
        rating_bad=row["rating_bad"],
        identity_verified=bool(row["identity_verified"]),
        phone_verified=bool(row["phone_verified"]),
        description=row["description"],
        registration_date_raw=row["registration_date_raw"],
        residential_area=row["residential_area"],
        occupation=row["occupation"],
        profile_fetched_at=row["profile_fetched_at"] if "profile_fetched_at" in row.keys() else None,
    )
