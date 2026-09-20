"""
seller_repository.py のユニットテスト。
"""

from pathlib import Path

import pytest

from repository.article_repository import get_connection
from repository.seller_repository import (
    get_seller,
    get_seller_other_articles,
    get_seller_rule,
    replace_seller_other_articles,
    upsert_seller,
    upsert_seller_profile,
)
from scraper.detail_parser import parse_detail_page
from scraper.profile_parser import parse_profile_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def seller_info():
    html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    return parse_detail_page(html).seller


def test_upsert_seller_inserts_new(conn, seller_info):
    upsert_seller(conn, seller_info)

    row = get_seller(conn, seller_info.seller_id)
    assert row is not None
    assert row["seller_name"] == "テスト出品者A"
    assert row["rating"] == 5.0
    assert row["identity_verified"] == 1


def test_upsert_seller_updates_existing(conn, seller_info):
    upsert_seller(conn, seller_info)

    # post_countが変わったとして再度upsert
    import dataclasses
    updated = dataclasses.replace(seller_info, post_count=1000)
    upsert_seller(conn, updated)

    row = get_seller(conn, seller_info.seller_id)
    assert row["post_count"] == 1000

    # 重複行が作られていないこと
    count = conn.execute(
        "SELECT COUNT(*) FROM sellers WHERE seller_id = ?", (seller_info.seller_id,)
    ).fetchone()[0]
    assert count == 1


def test_upsert_seller_profile_adds_v11_fields(conn, seller_info):
    """
    追補仕様v1.1のプロフィールページ限定フィールド
    (登録日・居住区・職業・評価内訳) が反映されること。
    """
    upsert_seller(conn, seller_info)

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    profile = parse_profile_page(profile_html)

    upsert_seller_profile(conn, seller_info.seller_id, profile)

    row = get_seller(conn, seller_info.seller_id)
    assert row["registration_date_raw"] == "2020/12/11"
    assert row["residential_area"] == "福岡県北九州市"
    assert row["occupation"] == "未登録"
    assert row["rating_good"] == 10
    assert row["rating_normal"] == 0
    assert row["rating_bad"] == 0


def test_get_seller_rule_none_when_not_registered(conn, seller_info):
    """NGユーザー登録がない出品者は None が返ること。"""
    upsert_seller(conn, seller_info)
    rule = get_seller_rule(conn, seller_info.seller_id)
    assert rule is None


def test_get_seller_rule_found(conn, seller_info):
    upsert_seller(conn, seller_info)
    conn.execute(
        "INSERT INTO seller_rules (seller_id, seller_name, rule_type, memo) VALUES (?, ?, 'ng', 'テスト理由')",
        (seller_info.seller_id, seller_info.seller_name),
    )

    rule = get_seller_rule(conn, seller_info.seller_id)
    assert rule is not None
    assert rule["rule_type"] == "ng"
    assert rule["memo"] == "テスト理由"


def test_inactive_seller_rule_not_returned(conn, seller_info):
    """
    無効化されたNGユーザールールは取得されないこと。
    (仕様書5-4: あくまで表示フィルタの制御のみ)
    """
    upsert_seller(conn, seller_info)
    conn.execute(
        "INSERT INTO seller_rules (seller_id, rule_type, is_active) VALUES (?, 'ng', 0)",
        (seller_info.seller_id,),
    )

    rule = get_seller_rule(conn, seller_info.seller_id)
    assert rule is None


def test_upsert_seller_profile_overwrites_description_when_present(conn, seller_info):
    """
    2026-08-28 修正: プロフィールページ由来の自己紹介文が取得できた
    場合、個別ページ由来の(省略されている可能性がある)紹介文を
    上書きすること。
    """
    upsert_seller(conn, seller_info)
    original = get_seller(conn, seller_info.seller_id)
    assert original["description"] == seller_info.description  # 上書き前

    from scraper.profile_parser import ProfileInfo

    full_profile = ProfileInfo(
        seller_name=seller_info.seller_name,
        post_count=10,
        rating=5.0,
        rating_count=5,
        description="全文の自己紹介文です。改行を含む\n複数行のテキストもここに入ります。",
    )
    upsert_seller_profile(conn, seller_info.seller_id, full_profile)

    updated = get_seller(conn, seller_info.seller_id)
    assert "全文の自己紹介文です" in updated["description"]
    assert "複数行のテキストもここに入ります" in updated["description"]


def test_upsert_seller_profile_keeps_existing_description_when_none(conn, seller_info):
    """
    プロフィールページ側でdescriptionが取得できなかった(None)場合は、
    個別ページ由来の既存値を残すこと (COALESCE挙動の確認)。
    """
    upsert_seller(conn, seller_info)

    from scraper.profile_parser import ProfileInfo

    profile_without_description = ProfileInfo(
        seller_name=seller_info.seller_name,
        post_count=10,
        rating=5.0,
        rating_count=5,
        description=None,
    )
    upsert_seller_profile(conn, seller_info.seller_id, profile_without_description)

    row = get_seller(conn, seller_info.seller_id)
    assert row["description"] == seller_info.description  # 既存値が維持される


# --- seller_other_articles (2026-09-04 新設) ---


def test_replace_seller_other_articles_inserts_rows(conn, seller_info):
    """
    profile.other_articles の内容が seller_other_articles に
    display_order順で保存されること。
    """
    upsert_seller(conn, seller_info)

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    profile = parse_profile_page(profile_html)

    replace_seller_other_articles(conn, seller_info.seller_id, profile)

    rows = get_seller_other_articles(conn, seller_info.seller_id)
    assert len(rows) == len(profile.other_articles)
    assert rows[0]["article_id"] == profile.other_articles[0].article_id
    assert rows[0]["display_order"] == 0
    assert rows[1]["display_order"] == 1


def test_replace_seller_other_articles_overwrites_previous_snapshot(conn, seller_info):
    """
    2回目の呼び出しで、前回保存した分は消えて新しい内容に洗い替えされること
    (ジモティー側で投稿が削除された場合にも追従できるようにするため)。
    """
    upsert_seller(conn, seller_info)

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    profile = parse_profile_page(profile_html)
    replace_seller_other_articles(conn, seller_info.seller_id, profile)

    # 1件だけになった状態を模して再度呼ぶ
    from dataclasses import replace as dc_replace

    shrunk_profile = dc_replace(profile, other_articles=profile.other_articles[:1])
    replace_seller_other_articles(conn, seller_info.seller_id, shrunk_profile)

    rows = get_seller_other_articles(conn, seller_info.seller_id)
    assert len(rows) == 1
    assert rows[0]["article_id"] == profile.other_articles[0].article_id


def test_get_seller_other_articles_empty_when_not_fetched(conn, seller_info):
    """プロフィール未取得の出品者では空配列が返ること。"""
    upsert_seller(conn, seller_info)

    rows = get_seller_other_articles(conn, seller_info.seller_id)
    assert rows == []


def test_upsert_seller_profile_overwrites_post_count(conn, seller_info):
    """
    2026-09-04 修正の検証: プロフィールページ由来のpost_count
    (「全◯件中」表記から抽出した正確な値) で上書きされること。
    個別ページ由来のpost_countは不正確な場合があるため。
    """
    upsert_seller(conn, seller_info)

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    profile = parse_profile_page(profile_html)
    assert profile.post_count == 30  # 「全30件中 1-10件表示」由来

    upsert_seller_profile(conn, seller_info.seller_id, profile)

    row = get_seller(conn, seller_info.seller_id)
    assert row["post_count"] == 30


def test_upsert_seller_profile_keeps_existing_post_count_when_none(conn, seller_info):
    """プロフィール側でpost_countが取得できなかった場合は既存値を残すこと。"""
    upsert_seller(conn, seller_info)
    original_post_count = seller_info.post_count

    from scraper.profile_parser import ProfileInfo

    profile_without_post_count = ProfileInfo(
        seller_name=seller_info.seller_name,
        post_count=None,
        rating=5.0,
        rating_count=5,
    )
    upsert_seller_profile(conn, seller_info.seller_id, profile_without_post_count)

    row = get_seller(conn, seller_info.seller_id)
    assert row["post_count"] == original_post_count
