"""watchlist_repository.py のユニットテスト。"""

import pytest

from repository.article_repository import get_connection
from repository.watchlist_repository import (
    add_watch,
    clear_watches,
    get_watched_article_ids,
    is_watched,
    remove_watch,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


def test_add_and_is_watched(conn):
    add_watch(conn, "art1")
    assert is_watched(conn, "art1") is True
    assert is_watched(conn, "art2") is False


def test_add_duplicate_does_not_error(conn):
    """気軽に追加/解除できる要件のため、重複追加はエラーにならないこと。"""
    add_watch(conn, "art1")
    add_watch(conn, "art1")  # 例外が出ないこと
    conn.commit()
    ids = get_watched_article_ids(conn)
    assert ids == {"art1"}


def test_add_with_memo(conn):
    add_watch(conn, "art1", memo="値下げ交渉中")
    row = conn.execute(
        "SELECT memo FROM watched_articles WHERE article_id = ?", ("art1",)
    ).fetchone()
    assert row["memo"] == "値下げ交渉中"


def test_remove_watch(conn):
    add_watch(conn, "art1")
    remove_watch(conn, "art1")
    assert is_watched(conn, "art1") is False


def test_remove_nonexistent_does_not_error(conn):
    remove_watch(conn, "存在しないID")  # 例外が出ないこと


def test_get_watched_article_ids(conn):
    add_watch(conn, "art1")
    add_watch(conn, "art2")
    add_watch(conn, "art3")
    ids = get_watched_article_ids(conn)
    assert ids == {"art1", "art2", "art3"}


def test_clear_watches_all(conn):
    """一括解除ボタン相当。article_idsを指定しない場合は全件解除。"""
    add_watch(conn, "art1")
    add_watch(conn, "art2")
    count = clear_watches(conn)
    assert count == 2
    assert get_watched_article_ids(conn) == set()


def test_clear_watches_partial(conn):
    """一部だけ指定した解除。"""
    add_watch(conn, "art1")
    add_watch(conn, "art2")
    add_watch(conn, "art3")
    count = clear_watches(conn, article_ids=["art1", "art3"])
    assert count == 2
    assert get_watched_article_ids(conn) == {"art2"}


def test_watchlist_independent_from_active_articles(conn):
    """
    watched_articlesはactive_articlesへの外部キー制約を持たないこと
    (投稿がDBから削除された後もウォッチ状態自体は残せる設計の確認)。
    """
    add_watch(conn, "存在しないarticle_id")  # 外部キーエラーが出ないこと
    conn.commit()
    assert is_watched(conn, "存在しないarticle_id") is True
