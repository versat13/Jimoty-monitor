"""
通知設定 (Discord Webhook / アプリ内トースト / ブラウザ通知) の読み書きを
担当するモジュール (2026-09-13新設、2026-09-15拡張)。

「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
ときに通知する機能の設定部分。3種類の通知先 (Discord・アプリ内トースト・
ブラウザ通知) は同じ通知条件を共有し、それぞれ個別のenabledフラグで
有効/無効を切り替える (「設定＞巡回設定＞通知」タブに統合、
ユーザーとの合意事項)。常に1件のみ保存する
(pickup_search・scan_settings_repository と同じ考え方)。

実際にDiscordへ送信する処理は notifications/discord_notifier.py が担う。
アプリ内トースト・ブラウザ通知は、対象投稿の算出をバックエンド側
(scheduler/scan_runner.py) が行い、実際の表示・発火はフロントエンド側
(ScanStatusContext) が担う。このモジュールは設定の保存/読み出しに専念する。
"""

from dataclasses import dataclass


@dataclass
class DiscordNotificationSettings:
    webhook_url: str
    enabled: bool
    in_app_enabled: bool = False
    browser_enabled: bool = False


def get_discord_notification_settings(conn) -> DiscordNotificationSettings:
    """
    現在の通知設定を返す。まだ行が無ければ
    「すべて未設定・無効」を表すデフォルト値を返す。
    """
    row = conn.execute(
        """
        SELECT webhook_url, enabled, in_app_enabled, browser_enabled
        FROM discord_notification_settings ORDER BY id LIMIT 1
        """
    ).fetchone()

    if row is None:
        return DiscordNotificationSettings(
            webhook_url="", enabled=False, in_app_enabled=False, browser_enabled=False
        )

    return DiscordNotificationSettings(
        webhook_url=row["webhook_url"] or "",
        enabled=bool(row["enabled"]),
        in_app_enabled=bool(row["in_app_enabled"]),
        browser_enabled=bool(row["browser_enabled"]),
    )


def update_discord_notification_settings(
    conn,
    *,
    webhook_url: str,
    enabled: bool,
    in_app_enabled: bool | None = None,
    browser_enabled: bool | None = None,
) -> DiscordNotificationSettings:
    """
    通知設定を更新する (常に1件のみ保持。既存行があれば上書き)。

    Args:
        webhook_url: DiscordのWebhook URL。空文字は「未設定」を意味する。
        enabled: Discord通知を実際に送るかどうかのトグル。URLを保持
            したまま一時的に通知だけ止めたい場合に False にする。
        in_app_enabled: アプリ内トースト通知のトグル。省略 (None) した
            場合は既存の値を維持する (2026-09-15追加。呼び出し元が
            Discord設定だけを更新する既存コード・テストとの後方互換のため。
            新規行作成時に省略された場合は False として扱う)。
        browser_enabled: ブラウザ通知のトグル。in_app_enabledと同様、
            省略時は既存値を維持する。

    Note:
        webhook_urlの形式検証 (https://discord.com/api/webhooks/... で
        あるか等) はここでは行わない (呼び出し元のAPI層の責務。
        このモジュールは「保存する箱」に徹する)。
    """
    row = conn.execute(
        "SELECT id, in_app_enabled, browser_enabled FROM discord_notification_settings ORDER BY id LIMIT 1"
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO discord_notification_settings
                (webhook_url, enabled, in_app_enabled, browser_enabled, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (
                webhook_url,
                int(enabled),
                int(bool(in_app_enabled)),
                int(bool(browser_enabled)),
            ),
        )
    else:
        # in_app_enabled/browser_enabledが省略された場合は既存値を
        # そのまま使う (「Discord設定だけ更新する」呼び出しで、他の
        # 通知先の設定が意図せずFalseにリセットされるのを防ぐため)。
        resolved_in_app = row["in_app_enabled"] if in_app_enabled is None else int(in_app_enabled)
        resolved_browser = row["browser_enabled"] if browser_enabled is None else int(browser_enabled)
        conn.execute(
            """
            UPDATE discord_notification_settings
            SET webhook_url = ?, enabled = ?, in_app_enabled = ?, browser_enabled = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (webhook_url, int(enabled), resolved_in_app, resolved_browser, row["id"]),
        )

    conn.commit()
    return get_discord_notification_settings(conn)
