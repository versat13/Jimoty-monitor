"""
repository/reset_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection, upsert_from_list_article
from repository.reset_repository import delete_all_scraped_data, reset_settings
from scraper.list_parser import parse_list_page


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def list_articles():
    html = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "list_real.html"
    ).read_text(encoding="utf-8")
    return parse_list_page(html, current_year=2026)


# ---------------------------------------------------------------------
# reset_settings
# ---------------------------------------------------------------------


def test_reset_settings_clears_ng_keywords(conn):
    conn.execute("INSERT INTO ng_keywords (keyword) VALUES ('test')")
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM ng_keywords").fetchone()["c"] == 0


def test_reset_settings_clears_ng_categories(conn):
    conn.execute(
        "INSERT INTO ng_categories (category_id, category_level) VALUES ('cat-1', 'leaf')"
    )
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM ng_categories").fetchone()["c"] == 0


def test_reset_settings_clears_seller_rules(conn):
    conn.execute(
        "INSERT INTO seller_rules (seller_id, rule_type, is_active) VALUES ('s1', 'watch', 1)"
    )
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM seller_rules").fetchone()["c"] == 0


def test_reset_settings_clears_scan_state(conn):
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug) VALUES ('fukuoka', 'sale-all')"
    )
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"] == 0


def test_reset_settings_clears_pickup_search(conn):
    conn.execute("INSERT INTO pickup_search (search_expression) VALUES ('.*(test)')")
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM pickup_search").fetchone()["c"] == 0


def test_reset_settings_clears_discord_notification_settings(conn):
    conn.execute(
        "INSERT INTO discord_notification_settings (webhook_url, enabled) "
        "VALUES ('https://discord.com/api/webhooks/1/a', 1)"
    )
    conn.commit()

    reset_settings(conn)

    assert (
        conn.execute("SELECT COUNT(*) AS c FROM discord_notification_settings").fetchone()["c"]
        == 0
    )


def test_reset_settings_does_not_touch_scraped_data(conn, list_articles):
    """設定初期化は投稿データに一切影響しないこと。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    reset_settings(conn)

    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None


def test_reset_settings_does_not_touch_search_history_or_area_options(conn):
    """search_history・area_optionsはリセット対象外であること。"""
    conn.execute("INSERT INTO search_history (query) VALUES ('test query')")
    conn.execute(
        "INSERT INTO area_options (prefecture, area_id, area_name, display_name, display_order) "
        "VALUES ('fukuoka', '731', 'kitakyushu', '北九州市', 1)"
    )
    conn.commit()

    reset_settings(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM search_history").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM area_options").fetchone()["c"] == 1


# ---------------------------------------------------------------------
# delete_all_scraped_data
# ---------------------------------------------------------------------


def test_delete_all_scraped_data_clears_active_articles(conn, list_articles):
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    delete_all_scraped_data(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM active_articles").fetchone()["c"] == 0


def test_delete_all_scraped_data_clears_sellers_and_seller_other_articles(conn, list_articles):
    """
    外部キー制約 (seller_other_articles.seller_id, active_articles.
    seller_id が sellers を参照) があっても、正しい順序で削除され
    エラーにならないこと。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute("INSERT INTO sellers (seller_id) VALUES ('seller-1')")
    conn.execute(
        "UPDATE active_articles SET seller_id = 'seller-1' WHERE article_id = ?",
        (article.article_id,),
    )
    conn.execute(
        "INSERT INTO seller_other_articles (seller_id, article_id, title, display_order) "
        "VALUES ('seller-1', 'other-1', 'test', 1)"
    )
    conn.commit()

    delete_all_scraped_data(conn)  # 外部キーエラーが起きないこと自体もこのテストの主眼

    assert conn.execute("SELECT COUNT(*) AS c FROM sellers").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM seller_other_articles").fetchone()["c"] == 0


def test_delete_all_scraped_data_clears_watched_articles(conn, list_articles):
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute("INSERT INTO watched_articles (article_id) VALUES (?)", (article.article_id,))
    conn.commit()

    delete_all_scraped_data(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM watched_articles").fetchone()["c"] == 0


def test_delete_all_scraped_data_clears_history_tables(conn, list_articles):
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute(
        "INSERT INTO article_status_history (article_id, from_status, to_status, reason) "
        "VALUES (?, 'active', 'missing', 'list_not_found')",
        (article.article_id,),
    )
    conn.execute(
        "INSERT INTO deleted_articles_log (article_id, url, list_title, article_status) "
        "VALUES (?, 'http://example.com', 'test', 'active')",
        (article.article_id,),
    )
    conn.commit()

    delete_all_scraped_data(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM article_status_history").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM deleted_articles_log").fetchone()["c"] == 0


def test_delete_all_scraped_data_does_not_touch_settings(conn):
    """投稿データ全削除は設定に一切影響しないこと。"""
    conn.execute("INSERT INTO ng_keywords (keyword) VALUES ('test')")
    conn.commit()

    delete_all_scraped_data(conn)

    assert conn.execute("SELECT COUNT(*) AS c FROM ng_keywords").fetchone()["c"] == 1
