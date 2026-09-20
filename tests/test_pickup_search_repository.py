"""
repository/pickup_search_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection
from repository.pickup_search_repository import (
    MAX_SEARCH_HISTORY_ITEMS,
    add_search_history,
    clear_search_history,
    get_pickup_search,
    list_search_history,
    update_pickup_search,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


# ---------------------------------------------------------------------
# pickup_search (検索タブの恒常条件)
# ---------------------------------------------------------------------


def test_default_pickup_search_when_no_row(conn):
    settings = get_pickup_search(conn)
    assert settings.search_expression == ""
    assert settings.include_words == []
    assert settings.exclude_words == []
    assert settings.is_builder_synced is True


def test_update_creates_row_when_none_exists(conn):
    settings = update_pickup_search(
        conn,
        search_expression="(iPhone|iPad)",
        include_words=["iPhone", "iPad"],
        exclude_words=["ジャンク"],
    )
    assert settings.search_expression == "(iPhone|iPad)"
    assert settings.include_words == ["iPhone", "iPad"]
    assert settings.exclude_words == ["ジャンク"]
    assert settings.is_builder_synced is True

    row_count = conn.execute("SELECT COUNT(*) AS c FROM pickup_search").fetchone()["c"]
    assert row_count == 1


def test_update_reuses_existing_row(conn):
    update_pickup_search(conn, search_expression="iPhone")
    update_pickup_search(conn, search_expression="iPad")

    row_count = conn.execute("SELECT COUNT(*) AS c FROM pickup_search").fetchone()["c"]
    assert row_count == 1  # 2回目の更新で行が増えていないこと

    settings = get_pickup_search(conn)
    assert settings.search_expression == "iPad"


def test_update_persists_across_reads(conn):
    update_pickup_search(conn, search_expression="(A|B)", include_words=["A", "B"])
    settings = get_pickup_search(conn)
    assert settings.search_expression == "(A|B)"
    assert settings.include_words == ["A", "B"]


def test_is_builder_synced_flag_persists(conn):
    """
    手直し後にビルダーとの同期が切れたことを示すフラグ
    (is_builder_synced=False) が正しく保存・読み出しできること。
    """
    settings = update_pickup_search(
        conn,
        search_expression="^(?!.*ジャンク).*iPhone",
        include_words=["iPhone"],
        exclude_words=["ジャンク"],
        is_builder_synced=False,
    )
    assert settings.is_builder_synced is False

    reread = get_pickup_search(conn)
    assert reread.is_builder_synced is False


def test_empty_words_default_to_empty_list(conn):
    settings = update_pickup_search(conn, search_expression="foo")
    assert settings.include_words == []
    assert settings.exclude_words == []


def test_words_with_special_characters_roundtrip(conn):
    """
    含める/除外ワードに正規表現の特殊文字や日本語が含まれていても
    JSON化・復元が壊れないこと。
    """
    words = ["a.b", "c|d", "日本語ワード", "(かっこ)"]
    settings = update_pickup_search(conn, search_expression="x", include_words=words)
    reread = get_pickup_search(conn)
    assert reread.include_words == words


# ---------------------------------------------------------------------
# search_history (簡易フィルタの検索履歴)
# ---------------------------------------------------------------------


def test_list_search_history_empty_initially(conn):
    assert list_search_history(conn) == []


def test_add_and_list_search_history_newest_first(conn):
    add_search_history(conn, "iPhone")
    add_search_history(conn, "iPad")
    add_search_history(conn, "MacBook")

    history = list_search_history(conn)
    assert history == ["MacBook", "iPad", "iPhone"]


def test_add_duplicate_query_moves_to_front(conn):
    """
    同じ語句を再度検索した場合、履歴の先頭に移動する (重複エントリに
    ならない)。
    """
    add_search_history(conn, "iPhone")
    add_search_history(conn, "iPad")
    add_search_history(conn, "iPhone")

    history = list_search_history(conn)
    assert history == ["iPhone", "iPad"]
    assert history.count("iPhone") == 1


def test_add_search_history_ignores_blank_query(conn):
    add_search_history(conn, "")
    add_search_history(conn, "   ")
    assert list_search_history(conn) == []


def test_add_search_history_strips_whitespace(conn):
    add_search_history(conn, "  iPhone  ")
    assert list_search_history(conn) == ["iPhone"]


def test_search_history_trims_to_max_items(conn):
    for i in range(MAX_SEARCH_HISTORY_ITEMS + 5):
        add_search_history(conn, f"word{i}")

    history = list_search_history(conn, limit=MAX_SEARCH_HISTORY_ITEMS + 5)
    assert len(history) == MAX_SEARCH_HISTORY_ITEMS
    # 直近のものが残り、古いものが削除されていること
    assert f"word{MAX_SEARCH_HISTORY_ITEMS + 4}" in history
    assert "word0" not in history


def test_list_search_history_respects_limit(conn):
    for i in range(10):
        add_search_history(conn, f"word{i}")

    history = list_search_history(conn, limit=3)
    assert len(history) == 3
    assert history == ["word9", "word8", "word7"]


def test_clear_search_history(conn):
    add_search_history(conn, "iPhone")
    add_search_history(conn, "iPad")

    cleared = clear_search_history(conn)
    assert cleared == 2
    assert list_search_history(conn) == []


def test_clear_search_history_when_empty(conn):
    assert clear_search_history(conn) == 0
