"""
Discord Webhook通知の設定に関するエンドポイント (2026-09-13新設)。

「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
ときに、Discordの指定チャンネルへ通知する機能の設定APIを提供する。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["settings-discord-notification"])


class DiscordNotificationSettingsOut(BaseModel):
    webhook_url: str
    enabled: bool
    # 2026-09-15追加: アプリ内トースト通知・ブラウザ通知のトグル。
    # 通知条件 (「検索」タブの正規表現にマッチした新規投稿) は3種類の
    # 通知先で共通。詳細はdb/schema.sqlのdiscord_notification_settings
    # テーブルコメント参照。
    in_app_enabled: bool = False
    browser_enabled: bool = False


class DiscordNotificationSettingsIn(BaseModel):
    webhook_url: str
    enabled: bool = False
    in_app_enabled: bool = False
    browser_enabled: bool = False


@router.get("/api/settings/discord-notification", response_model=DiscordNotificationSettingsOut)
def get_discord_notification_settings_endpoint():
    """現在の通知設定 (Discord/アプリ内トースト/ブラウザ) を返す。未設定なら全て無効を返す。"""
    from repository.discord_notification_repository import get_discord_notification_settings

    conn = get_db()
    settings = get_discord_notification_settings(conn)
    conn.close()
    return DiscordNotificationSettingsOut(
        webhook_url=settings.webhook_url,
        enabled=settings.enabled,
        in_app_enabled=settings.in_app_enabled,
        browser_enabled=settings.browser_enabled,
    )


@router.put("/api/settings/discord-notification", response_model=DiscordNotificationSettingsOut)
def update_discord_notification_settings_endpoint(payload: DiscordNotificationSettingsIn):
    """
    通知設定 (Discord/アプリ内トースト/ブラウザ) を更新する (常に1件のみ保持)。

    webhook_url は空文字であることを許容する (「URLを一旦消して
    未設定に戻す」操作のため)。ただし、enabled=True かつ
    webhook_url が空の場合はエラーとする (有効化するにはURLが必須)。
    URLが与えられた場合は "https://discord.com/api/webhooks/" または
    "https://discordapp.com/api/webhooks/" で始まる形式かどうかを
    簡易チェックする (誤って別のURLを貼り付けた際の早期発見のため。
    実際に有効なWebhookかどうかまではここでは検証しない。ネットワーク
    アクセスを伴う検証はこの設定保存の責務ではないため)。

    2026-09-15追加: in_app_enabled・browser_enabledはURLの有無と
    無関係に有効化できる (Discordを使わずアプリ内トースト・ブラウザ
    通知だけ使うユーザーを想定しているため、webhook_url必須チェックは
    enabled (Discord) のみに適用する)。
    """
    webhook_url = payload.webhook_url.strip()

    if payload.enabled and not webhook_url:
        raise HTTPException(
            status_code=422, detail="Discord通知を有効にするにはWebhook URLの入力が必要です"
        )

    if webhook_url and not (
        webhook_url.startswith("https://discord.com/api/webhooks/")
        or webhook_url.startswith("https://discordapp.com/api/webhooks/")
    ):
        raise HTTPException(
            status_code=422,
            detail="Discord Webhook URLの形式が正しくありません "
            "(https://discord.com/api/webhooks/... で始まるURLを指定してください)",
        )

    from repository.discord_notification_repository import update_discord_notification_settings

    conn = get_db()
    settings = update_discord_notification_settings(
        conn,
        webhook_url=webhook_url,
        enabled=payload.enabled,
        in_app_enabled=payload.in_app_enabled,
        browser_enabled=payload.browser_enabled,
    )
    conn.close()
    return DiscordNotificationSettingsOut(
        webhook_url=settings.webhook_url,
        enabled=settings.enabled,
        in_app_enabled=settings.in_app_enabled,
        browser_enabled=settings.browser_enabled,
    )


@router.post("/api/settings/discord-notification/test")
def send_discord_notification_test_endpoint():
    """
    設定済みのWebhook URLへテスト通知を送信する (2026-09-13新設)。

    設定画面で「テスト送信」ボタンを押した際に呼ばれる想定。
    実際に投稿データを使わず、固定の確認用メッセージのみを送る。
    Webhook URLが未設定・無効の場合は422を返す。送信自体が失敗した
    場合 (URLが無効化されている等) は502を返し、詳細はサーバーログに
    残す (Webhookのレスポンス内容をそのままクライアントに返すのは
    情報として過剰なため)。
    """
    from repository.discord_notification_repository import get_discord_notification_settings

    conn = get_db()
    settings = get_discord_notification_settings(conn)
    conn.close()

    if not settings.webhook_url:
        raise HTTPException(status_code=422, detail="Webhook URLが未設定です")

    import httpx

    try:
        response = httpx.post(
            settings.webhook_url,
            json={"content": "ジモティー新着監視ツールからのテスト通知です。この通知が届いていれば設定は正常です。"},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Discordへの送信に失敗しました: {e}")

    return {"status": "ok"}
