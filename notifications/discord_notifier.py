"""
Discord Webhookへの通知送信 (2026-09-13新設)。

「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
ときに、設定済みのDiscord Webhook URLへEmbed形式で通知を送る。

=== 設計メモ ===

- 1回のWebhookリクエストにつき最大10件のEmbedをまとめて送信する
  (Discordの仕様上の上限)。30分に1回程度の巡回頻度であれば、
  1回の巡回で見つかる「検索タブヒットの新規投稿」が10件を超える
  ことは通常想定しにくいが、超えた場合は複数リクエストに分割する。
- Discord Webhookのレート制限は1URLあたり30リクエスト/分
  (2026年時点の一般的な制限)。この実装では巡回1回につき最大でも
  数リクエスト程度しか発生しない想定のため、明示的なレート制限
  対応 (429時のretry_after待機等) は行わない。将来、頻繁に上限に
  達するようであれば追加を検討する。
- 送信失敗 (ネットワークエラー、Webhook URLが無効化された等) は
  巡回処理全体を失敗させない。ログに警告を出すだけに留める
  (通知はあくまで補助機能であり、本体の巡回・保存処理が通知の
  成否に左右されるべきではないため)。
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Discordの仕様上の上限 (1メッセージあたりのEmbed数)。
_MAX_EMBEDS_PER_MESSAGE = 10

# Webhook送信のタイムアウト (秒)。巡回処理全体をブロックしすぎない
# よう、scraper.fetch のDEFAULT_TIMEOUTと同程度の短めの値にする。
_WEBHOOK_TIMEOUT_SECONDS = 10.0

# Discordの日本語ロケールで見慣れた色に寄せた、通知用Embedのアクセント
# カラー (Discordの「ブルー」寄りの色。特別な意味はなく、視認性のため)。
_EMBED_COLOR = 0x5865F2


def build_article_embed(article: dict) -> dict:
    """
    1件の投稿からDiscord Embed用の辞書を組み立てる。

    Args:
        article: article_id, list_title, price, url, thumbnail_url,
            area_name 等を含む辞書 (api.schemas.ArticleOut を
            dict化したもの、またはDBのrowから組み立てた同等の辞書)。
    """
    title = article.get("list_title") or "(タイトル不明)"
    # Discord Embed titleの上限は256文字 (Discord API仕様)。
    if len(title) > 256:
        title = title[:253] + "..."

    price = article.get("price")
    price_label = f"{price:,}円" if isinstance(price, int) else "価格不明"

    description_parts = [price_label]
    area_name = article.get("area_name")
    if area_name:
        description_parts.append(area_name)
    description = " ・ ".join(description_parts)

    embed = {
        "title": title,
        "url": article.get("url") or "",
        "description": description,
        "color": _EMBED_COLOR,
    }

    thumbnail_url = article.get("thumbnail_url")
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    return embed


def send_discord_notification(webhook_url: str, articles: list[dict]) -> bool:
    """
    検索タブにヒットした新規投稿をDiscord Webhookへ通知する。

    Args:
        webhook_url: Discordのチャンネル設定から発行したWebhook URL。
        articles: 通知対象の投稿の辞書のリスト (build_article_embed
            が期待するキーを持つもの)。空リストの場合は何もしない
            (呼び出し元で0件チェック済みの想定だが、念のため)。

    Returns:
        全リクエストが成功した場合True。1件でも失敗した場合False
        (呼び出し元は戻り値をログ・UI表示に使ってよいが、巡回処理
        自体を失敗させる目的では使わないこと)。
    """
    if not webhook_url:
        logger.warning("Discord Webhook URLが未設定のため通知をスキップします。")
        return False
    if not articles:
        return True

    all_ok = True
    with httpx.Client(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
        for i in range(0, len(articles), _MAX_EMBEDS_PER_MESSAGE):
            chunk = articles[i : i + _MAX_EMBEDS_PER_MESSAGE]
            embeds = [build_article_embed(a) for a in chunk]
            payload = {
                "content": f"検索条件にヒットした新着投稿が{len(chunk)}件あります。",
                "embeds": embeds,
            }
            try:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Discord Webhookへの通知送信に失敗しました: %s", e)
                all_ok = False

    return all_ok
