"""
「設定を初期化」「取得済みデータを全削除」のリセット処理
(2026-09-14新設)。

設定画面の「データ」タブに置く2つの破壊的操作を担当する。
    - reset_settings(): NGワード・NGカテゴリ・ユーザー・地域・取得範囲・
      自動更新・通知設定などを初期値に戻す。投稿データ(active_articles
      等)には触れない。
    - delete_all_scraped_data(): 投稿データ(active_articles・sellers・
      各種履歴)のみを削除する。設定には一切触れない。

この2つを両方実行すれば結果的に「全リセット」相当になる、という
ユーザーとの合意に基づき、あえて「全リセット」という第三の関数は
用意しない。

search_history (簡易検索の一時的な入力履歴) と area_options (地域取得
のキャッシュ) はどちらの操作でも対象外とする。前者は「設定」と呼ぶ
ほどのものではなく、後者は単なるキャッシュで次回自動的に再取得される
ため、意図的にリセット対象から外している。
"""

import sqlite3


def reset_settings(conn: sqlite3.Connection) -> None:
    """
    設定関連のテーブルを全て空にし、初期状態に戻す。

    scan_state (地域・取得範囲・自動更新間隔) は行ごと削除する。
    次回アクセス時に repository.scan_settings_repository.
    ensure_scan_state_row() がデフォルト値で行を作り直すため、
    ここでデフォルト値を個別に書き込む必要はない。

    投稿データ (active_articles等) には一切触れない。
    """
    conn.execute("DELETE FROM ng_keywords")
    conn.execute("DELETE FROM ng_categories")
    conn.execute("DELETE FROM seller_rules")
    conn.execute("DELETE FROM scan_state")
    conn.execute("DELETE FROM pickup_search")
    conn.execute("DELETE FROM discord_notification_settings")
    conn.commit()


def delete_all_scraped_data(conn: sqlite3.Connection) -> None:
    """
    取得済みの投稿データを全て削除する。

    active_articlesを削除すればprice_historyはON DELETE CASCADEで
    連動して消える (db/schema.sql参照)。article_status_history・
    deleted_articles_logはCASCADE対象ではない (削除後も履歴として
    残す設計、または削除専用ログのため) ため、明示的に削除する。

    watched_articles (投稿単位の☆登録) も、対象の投稿自体が
    全削除されるため一緒に削除する (投稿がないのに☆登録情報だけ
    残っていても意味がないため)。

    削除順序に注意: active_articles.seller_id と
    seller_other_articles.seller_id が sellers を参照する外部キーの
    ため (db/schema.sql、PRAGMA foreign_keys=ON で有効)、sellersを
    削除する前にそれらを先に削除する必要がある。

    設定 (NGワード・NGカテゴリ・ユーザー・地域設定等) には
    一切触れない。
    """
    conn.execute("DELETE FROM watched_articles")
    conn.execute("DELETE FROM article_status_history")
    conn.execute("DELETE FROM deleted_articles_log")
    conn.execute("DELETE FROM seller_other_articles")
    conn.execute("DELETE FROM active_articles")
    conn.execute("DELETE FROM sellers")
    conn.commit()
