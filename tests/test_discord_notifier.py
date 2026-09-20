"""
notifications/discord_notifier.py のユニットテスト。

実際のネットワークアクセスは行わず、httpx.Client.post をモックして
ペイロードの組み立て・分割・エラー処理を検証する
(2026-09-13新設、Discord通知機能のため)。
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from notifications.discord_notifier import (
    build_article_embed,
    send_discord_notification,
)


def _article(**overrides):
    base = {
        "article_id": "a1",
        "list_title": "テスト投稿",
        "price": 1000,
        "url": "https://jmty.jp/fukuoka/sale-all/a1",
        "thumbnail_url": "https://example.com/thumb.jpg",
        "area_name": "北九州市小倉北区",
    }
    base.update(overrides)
    return base


def test_build_article_embed_includes_title_and_url():
    embed = build_article_embed(_article())
    assert embed["title"] == "テスト投稿"
    assert embed["url"] == "https://jmty.jp/fukuoka/sale-all/a1"
    assert "1,000円" in embed["description"]
    assert "北九州市小倉北区" in embed["description"]
    assert embed["thumbnail"]["url"] == "https://example.com/thumb.jpg"


def test_build_article_embed_handles_missing_price():
    embed = build_article_embed(_article(price=None))
    assert "価格不明" in embed["description"]


def test_build_article_embed_truncates_long_title():
    long_title = "あ" * 300
    embed = build_article_embed(_article(list_title=long_title))
    assert len(embed["title"]) <= 256
    assert embed["title"].endswith("...")


def test_build_article_embed_without_thumbnail():
    embed = build_article_embed(_article(thumbnail_url=None))
    assert "thumbnail" not in embed


def test_send_discord_notification_returns_false_without_webhook_url():
    result = send_discord_notification("", [_article()])
    assert result is False


def test_send_discord_notification_returns_true_for_empty_articles():
    result = send_discord_notification("https://discord.com/api/webhooks/x/y", [])
    assert result is True


def test_send_discord_notification_posts_payload():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        result = send_discord_notification(
            "https://discord.com/api/webhooks/x/y", [_article()]
        )

    assert result is True
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert len(kwargs["json"]["embeds"]) == 1


def test_send_discord_notification_splits_into_chunks_of_ten():
    articles = [_article(article_id=f"a{i}") for i in range(25)]
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        result = send_discord_notification(
            "https://discord.com/api/webhooks/x/y", articles
        )

    assert result is True
    # 25件 -> 10件 + 10件 + 5件 の3リクエストに分割されること
    assert mock_post.call_count == 3
    call_sizes = [len(call.kwargs["json"]["embeds"]) for call in mock_post.call_args_list]
    assert call_sizes == [10, 10, 5]


def test_send_discord_notification_returns_false_on_http_error():
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("failed")):
        result = send_discord_notification(
            "https://discord.com/api/webhooks/x/y", [_article()]
        )

    assert result is False
