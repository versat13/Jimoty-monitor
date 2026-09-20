"""
sellers テーブルへの読み書きを担うrepository。

article_repository.upsert_from_detail_article() は sellers.seller_id への
外部キー制約を持つため、呼び出し順序として
    1. upsert_seller() で出品者を先に登録
    2. upsert_from_detail_article() で投稿に紐付け
とする必要がある (scheduler/job.py 実装時の呼び出し順として明記)。
"""

import sqlite3

from scraper.detail_parser import SellerInfo
from scraper.profile_parser import ProfileInfo


def upsert_seller(conn: sqlite3.Connection, seller: SellerInfo) -> None:
    """
    個別ページの投稿者欄 (SellerInfo) から得た情報でsellersテーブルを更新する。

    既存レコードがあれば、個別ページ由来のフィールドのみ上書きする
    (プロフィールページ由来のフィールド: registration_date_raw等は
    upsert_seller_profile() が別途担当するため、ここでは触らない)。
    """
    if seller.seller_id is None:
        raise ValueError("SellerInfo.seller_id が None のため保存できません")

    conn.execute(
        """
        INSERT INTO sellers (
            seller_id, seller_name, seller_profile_url, gender,
            post_count, rating, rating_count, identity_verified,
            phone_verified, description, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(seller_id) DO UPDATE SET
            seller_name = excluded.seller_name,
            seller_profile_url = excluded.seller_profile_url,
            gender = excluded.gender,
            post_count = excluded.post_count,
            rating = excluded.rating,
            rating_count = excluded.rating_count,
            identity_verified = excluded.identity_verified,
            phone_verified = excluded.phone_verified,
            description = excluded.description,
            last_updated_at = datetime('now')
        """,
        (
            seller.seller_id, seller.seller_name, seller.seller_profile_url,
            seller.gender, seller.post_count, seller.rating, seller.rating_count,
            int(seller.identity_verified), int(seller.phone_verified), seller.description,
        ),
    )


def upsert_seller_profile(conn: sqlite3.Connection, seller_id: str, profile: ProfileInfo) -> None:
    """
    プロフィールページ (ProfileInfo) から得た追加情報でsellersテーブルを更新する。

    追補仕様v1.1で発見した、プロフィールページ限定の項目
    (登録日・居住区・職業・評価内訳) を反映する。
    upsert_seller() で先に基本情報が登録済みであることを前提とする
    (行が存在しない場合は何も更新されない)。

    2026-08-28 修正: description (自己紹介文) もここで上書きするように
    した。個別ページ (detail_parser.SellerInfo.description) の投稿者欄に
    書かれた紹介文は、ジモティー側の表示上すでに省略されている場合が
    あり、全文を取得できるのはプロフィールページ側であることが実データ
    検証で判明したため (ユーザー報告: 「続きを読む」を押しても全文が
    表示されない → 実は個別ページ由来のdescription自体が最初から
    ジモティー側で切り詰められていた)。profile.description が取得できて
    いる場合のみ上書きし、Noneの場合は個別ページ由来の値を残す
    (COALESCE)。

    2026-08-30 修正: 「見るまでは取らない」設計 (遅延取得) への変更に
    伴い、profile_fetched_at (このプロフィールページを最後に取得した
    時刻) も併せて記録するようにした。呼ばれる度に「今」の時刻へ
    更新する。API側 (POST /api/sellers/{seller_id}/fetch-profile) の
    「続きを読む」(未取得時のみ取得) 判定はこのカラムのNULL有無を見る。

    2026-09-04 修正: post_count もここで上書きするようにした。個別ページ
    由来のpost_countは不正確な場合がある一方、プロフィールページの
    「全◯件中」表記 (profile_parser.pyでother_articles_total_countとして
    抽出) は実際の投稿一覧のページ送りから直接得た正確な値であるため
    (投稿数が多い出品者で「他の投稿」件数が実際より少なく表示される
    不具合の調査で判明)。descriptionと同様、profile.post_countがNoneの
    場合は個別ページ由来の値を残す (COALESCE)。
    """
    conn.execute(
        """
        UPDATE sellers
        SET registration_date_raw = ?,
            residential_area = ?,
            occupation = ?,
            rating_good = ?,
            rating_normal = ?,
            rating_bad = ?,
            description = COALESCE(?, description),
            post_count = COALESCE(?, post_count),
            profile_fetched_at = datetime('now'),
            last_updated_at = datetime('now')
        WHERE seller_id = ?
        """,
        (
            profile.registration_date_raw, profile.residential_area, profile.occupation,
            profile.rating_good, profile.rating_normal, profile.rating_bad,
            profile.description, profile.post_count, seller_id,
        ),
    )


def get_seller(conn: sqlite3.Connection, seller_id: str) -> sqlite3.Row | None:
    """seller_idで1件取得する。"""
    cursor = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,))
    return cursor.fetchone()


def get_seller_rule(conn: sqlite3.Connection, seller_id: str) -> sqlite3.Row | None:
    """
    seller_rules (NGユーザー／監視ユーザー) を照合する。

    仕様書5-4の原則により、この関数の結果は表示フィルタ(is_hidden_by_rule
    相当)にのみ使うこと。呼び出し元がこの結果を理由に投稿データの
    取得・保存自体をスキップすることは絶対に行わないこと。
    """
    cursor = conn.execute(
        "SELECT * FROM seller_rules WHERE seller_id = ? AND is_active = 1",
        (seller_id,),
    )
    return cursor.fetchone()


def replace_seller_other_articles(conn: sqlite3.Connection, seller_id: str, profile: ProfileInfo) -> None:
    """
    プロフィールページの投稿一覧 (profile.other_articles) で
    seller_other_articles テーブルを洗い替えする (2026-09-04 新設)。

    「この出品者の他の投稿」表示に、監視ツールが偶然検知した投稿
    (active_articles) だけでなく、公式プロフィールページの全投稿を
    反映したいというユーザー要望により追加 (db/schema.sql のテーブル
    コメント参照)。

    洗い替え (delete → insert) にしている理由: ジモティー側で投稿が
    削除された場合や、前回取得時より投稿が減っていた場合にも
    正しく追従できるようにするため (単純なUPSERTだと消えた投稿の行が
    残り続けてしまう)。

    INSERT OR REPLACE にしている理由: 「受付中」「受付終了」の区分をまたぐ
    ページ送りの都合上、同一article_idが複数ページにまたがって重複して
    現れる可能性があるため (通常INSERTだと複合主キー違反になる)。

    fetch_seller_profile_on_demand() がプロフィールページの全ページを
    辿って profile.other_articles に合算した後、この関数を1回呼ぶ
    想定 (ページ毎に呼ぶと洗い替えで前ページ分が消えてしまうため)。
    """
    conn.execute("DELETE FROM seller_other_articles WHERE seller_id = ?", (seller_id,))

    for order, article in enumerate(profile.other_articles):
        if article.article_id is None:
            # article_idが取れなかった行は複合主キーを満たせないためスキップ
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO seller_other_articles (
                seller_id, article_id, url, listing_type, title,
                price, location, description_short, updated_date_raw,
                display_order, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                seller_id, article.article_id, article.url, article.listing_type,
                article.title, article.price, article.location,
                article.description_short, article.updated_date_raw, order,
            ),
        )


def get_seller_other_articles(conn: sqlite3.Connection, seller_id: str) -> list[sqlite3.Row]:
    """seller_other_articlesを表示順 (display_order) で取得する。"""
    cursor = conn.execute(
        "SELECT * FROM seller_other_articles WHERE seller_id = ? ORDER BY display_order",
        (seller_id,),
    )
    return cursor.fetchall()
