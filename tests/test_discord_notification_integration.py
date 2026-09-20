"""
Discord通知機能 (2026-09-13新設) の scheduler.scan_runner への
統合テスト。

「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
ときに、run_scan / run_scan_with_range から実際にDiscordへの送信
処理が正しい引数で呼ばれることを検証する。

実際のネットワークアクセス (fetch_html・Discord Webhookへのpost)は
すべてモック化し、実データ (list_real.html, detail_real.html) を
使って一連の判定フローを検証する。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repository.article_repository import get_connection
from repository.discord_notification_repository import update_discord_notification_settings
from repository.pickup_search_repository import update_pickup_search
from repository.scan_settings_repository import get_last_notified_articles
from scheduler.job import run_scan, run_scan_with_range

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def list_html():
    return (FIXTURES / "list_real.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html():
    return (FIXTURES / "detail_real.html").read_text(encoding="utf-8")


def test_run_scan_does_not_call_discord_when_disabled(conn, list_html, detail_html):
    """
    Discord通知が無効(デフォルト)の場合、通知送信自体が一切
    呼ばれないこと (既存ユーザーへの挙動変化がないことの確認)。
    """
    update_pickup_search(conn, search_expression=".*(テレビ)")
    # Discord通知は明示的に有効化していない (デフォルトのenabled=False)。

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.send_discord_notification") as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    mock_send.assert_not_called()
    assert result.discord_notified_count == 0


def test_run_scan_does_not_call_discord_when_search_expression_empty(conn, list_html, detail_html):
    """
    Discord通知は有効だが、検索タブの条件が未設定 (空文字) の場合は
    「絞り込みなし」ではなく「通知対象なし」として扱われ、送信されない
    こと (検索タブに何も設定していないのに大量通知が飛ぶのを防ぐ)。
    """
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    # pickup_searchは未設定のまま (search_expression=="")。

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.send_discord_notification") as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    mock_send.assert_not_called()
    assert result.discord_notified_count == 0


def test_run_scan_sends_discord_notification_for_matched_articles(conn, list_html, detail_html):
    """
    Discord通知が有効、かつ検索タブの条件にマッチする新規投稿がある
    場合、send_discord_notification が該当投稿のみを引数として
    呼ばれること。
    """
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.send_discord_notification", return_value=True) as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    mock_send.assert_called_once()
    call_args = mock_send.call_args
    webhook_url_arg = call_args[0][0]
    articles_arg = call_args[0][1]

    assert webhook_url_arg == "https://discord.com/api/webhooks/1/abc"
    assert len(articles_arg) > 0
    assert all("テレビ" in a["list_title"] for a in articles_arg)
    assert result.discord_notified_count == len(articles_arg)


def test_run_scan_excludes_ng_matched_articles_from_discord_notification(conn, list_html, detail_html):
    """
    NGワードに一致する投稿は、検索タブの条件にもマッチしていたとしても
    Discord通知の対象に含まれないこと (NG判定が優先される)。
    """
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    # 「冷蔵庫」にマッチする投稿は実データに複数件あり (前回セッションで
    # 確認済み)、そのうち「三菱冷蔵庫」を含む1件だけをNGワード登録して
    # 除外されることを確認する。
    conn.execute("INSERT INTO ng_keywords (keyword) VALUES ('三菱冷蔵庫')")
    conn.commit()
    update_pickup_search(conn, search_expression=".*(冷蔵庫)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.send_discord_notification", return_value=True) as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    mock_send.assert_called_once()
    articles_arg = mock_send.call_args[0][1]
    assert len(articles_arg) > 0
    assert all("三菱冷蔵庫" not in a["list_title"] for a in articles_arg)


def test_run_scan_with_range_sends_discord_notification(conn, list_html, detail_html):
    """
    run_scan_with_range (自動更新・手動更新で実際に使われるメイン
    処理) でも同様にDiscord通知が呼ばれること。
    """
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"), \
         patch("scheduler.scan_runner.send_discord_notification", return_value=True) as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    mock_send.assert_called_once()
    assert result.discord_notified_count > 0


# ---------------------------------------------------------------------
# 2026-09-15追加: トースト通知・ブラウザ通知向けの統合テスト。
#
# 通知条件 (pickup_search条件にマッチした新規投稿) はDiscordと共通
# なので、_load_pickup_search_pattern_if_any_notification_enabled()が
# 「Discordが無効でもトースト/ブラウザいずれかが有効なら読み込む」
# ことと、run_scan/run_scan_with_range完了後にscan_stateへ
# last_notified_article_idsが保存されることを検証する。
# ---------------------------------------------------------------------


def test_run_scan_updates_last_notified_articles_when_in_app_enabled(conn, list_html, detail_html):
    """
    Discordは無効でも、アプリ内トースト通知 (in_app_enabled) が有効
    なら、pickup_search条件にマッチした新規投稿がscan_stateの
    last_notified_article_idsに保存されること。
    """
    update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=True, browser_enabled=False
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.send_discord_notification") as mock_send:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    # Discordは無効のまま送信は行われない。
    mock_send.assert_not_called()
    assert result.discord_notified_count == 0
    # しかしpickup_search_matched自体は算出され、scan_stateに保存される。
    assert len(result.pickup_search_matched) > 0

    last_notified = get_last_notified_articles(conn)
    assert last_notified.article_ids == result.pickup_search_matched
    assert last_notified.notified_at is not None


def test_run_scan_updates_last_notified_articles_when_browser_enabled(conn, list_html, detail_html):
    """
    ブラウザ通知 (browser_enabled) のみが有効な場合も同様に、
    last_notified_article_idsが更新されること。
    """
    update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=False, browser_enabled=True
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    assert len(result.pickup_search_matched) > 0
    last_notified = get_last_notified_articles(conn)
    assert last_notified.article_ids == result.pickup_search_matched


def test_run_scan_last_notified_articles_empty_when_all_notifications_disabled(
    conn, list_html, detail_html
):
    """
    Discord・トースト・ブラウザ通知のいずれも無効な場合は、検索タブに
    条件を設定していても判定自体が行われず、pickup_search_matchedは
    常に空、last_notified_article_idsも空のまま更新される (洗い替え
    自体は毎回行われる) こと。既存ユーザー (通知機能を一切使わない
    ユーザー) にオーバーヘッド・挙動変化が生じないことの確認。
    """
    # 全ての通知先を明示的に無効化 (デフォルトでも無効だが、テストの
    # 意図を明確にするため明示的に呼ぶ)。
    update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=False, browser_enabled=False
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    assert result.pickup_search_matched == []
    last_notified = get_last_notified_articles(conn)
    assert last_notified.article_ids == []


def test_run_scan_with_range_updates_last_notified_articles(conn, list_html, detail_html):
    """
    run_scan_with_range (自動更新・手動更新で実際に使われるメイン処理)
    でも同様に、トースト/ブラウザ通知向けのlast_notified_article_ids
    更新が行われること。
    """
    update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=True, browser_enabled=True
    )
    update_pickup_search(conn, search_expression=".*(テレビ)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    assert len(result.pickup_search_matched) > 0
    last_notified = get_last_notified_articles(conn)
    assert last_notified.article_ids == result.pickup_search_matched


def test_run_scan_washes_out_previous_last_notified_articles_when_no_match(
    conn, list_html, detail_html
):
    """
    前回の巡回でpickup_search条件にマッチした投稿があっても、今回の
    巡回でマッチする新規投稿が0件であれば、last_notified_article_ids
    は空に洗い替えされること (前回分がいつまでも「未読の通知」として
    残り続けるのを防ぐ)。
    """
    from repository.scan_settings_repository import update_last_notified_articles

    update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=True, browser_enabled=False
    )
    # あらかじめ「前回の通知対象」を手動でセットしておく。
    update_last_notified_articles(conn, ["stale-id-from-previous-scan"])

    # 今回は絶対にマッチしない検索条件にしておく。
    update_pickup_search(conn, search_expression=".*(絶対にマッチしない特殊文字列XYZ123)")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    last_notified = get_last_notified_articles(conn)
    assert last_notified.article_ids == []
