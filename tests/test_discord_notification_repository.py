"""
repository/discord_notification_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection
from repository.discord_notification_repository import (
    get_discord_notification_settings,
    update_discord_notification_settings,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


def test_default_settings_when_no_row(conn):
    settings = get_discord_notification_settings(conn)
    assert settings.webhook_url == ""
    assert settings.enabled is False
    assert settings.in_app_enabled is False
    assert settings.browser_enabled is False


def test_update_creates_row_when_none_exists(conn):
    settings = update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    assert settings.webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert settings.enabled is True
    # 2026-09-15追加: in_app_enabled/browser_enabledを省略した場合、
    # 新規作成時はFalseとして扱われること。
    assert settings.in_app_enabled is False
    assert settings.browser_enabled is False


def test_update_overwrites_existing_row(conn):
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    settings = update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/2/xyz", enabled=False
    )
    assert settings.webhook_url == "https://discord.com/api/webhooks/2/xyz"
    assert settings.enabled is False

    # 常に1件のみ保持されること (2件目の行が増えていないこと)。
    count = conn.execute("SELECT COUNT(*) AS c FROM discord_notification_settings").fetchone()["c"]
    assert count == 1


def test_get_reflects_latest_update(conn):
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    settings = get_discord_notification_settings(conn)
    assert settings.webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert settings.enabled is True


def test_update_in_app_and_browser_enabled(conn):
    """
    2026-09-15新設。アプリ内トースト通知・ブラウザ通知のトグルを
    個別に有効化できること (Discord Webhook URLの有無と無関係)。
    """
    settings = update_discord_notification_settings(
        conn, webhook_url="", enabled=False, in_app_enabled=True, browser_enabled=True
    )
    assert settings.webhook_url == ""
    assert settings.enabled is False
    assert settings.in_app_enabled is True
    assert settings.browser_enabled is True


def test_update_without_in_app_browser_args_preserves_existing_values(conn):
    """
    2026-09-15新設。update_discord_notification_settings()呼び出し時に
    in_app_enabled/browser_enabledを省略した場合 (呼び出し元がDiscord
    設定だけを更新するケース)、既存の値がリセットされず維持される
    こと。API層 (settings_discord_notification.py) は常に全フィールド
    を渡すため通常は発生しないが、リポジトリ関数単体としての後方互換
    性を保証するテスト。
    """
    update_discord_notification_settings(
        conn,
        webhook_url="https://discord.com/api/webhooks/1/abc",
        enabled=True,
        in_app_enabled=True,
        browser_enabled=True,
    )

    # in_app_enabled/browser_enabledを省略してDiscordのURLだけ更新。
    settings = update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/2/xyz", enabled=True
    )
    assert settings.webhook_url == "https://discord.com/api/webhooks/2/xyz"
    # 省略したフィールドは直前の値(True)のまま維持されること。
    assert settings.in_app_enabled is True
    assert settings.browser_enabled is True
