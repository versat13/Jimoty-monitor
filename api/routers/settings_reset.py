"""
「設定を初期化」「取得済みデータを全削除」のリセットAPI
(2026-09-14新設)。

設定画面の「データ」タブに置く2つの破壊的操作のエンドポイント。
どちらも取り消しができない操作のため、フロントエンド側で実行前に
確認ダイアログを挟む想定 (このAPI自体は追加の確認手段を持たない)。
"""

from fastapi import APIRouter

router = APIRouter(tags=["settings-reset"])


@router.post("/api/settings/reset-settings")
def reset_settings_endpoint():
    """
    NGワード・NGカテゴリ・ユーザー・地域・取得範囲・自動更新・
    通知設定などを初期値に戻す。投稿データには一切触れない。
    """
    from api.deps import get_db
    from repository.reset_repository import reset_settings

    conn = get_db()
    reset_settings(conn)
    conn.close()
    return {"status": "ok"}


@router.post("/api/settings/delete-all-scraped-data")
def delete_all_scraped_data_endpoint():
    """
    取得済みの投稿データ (投稿本体・出品者情報・価格履歴・
    ステータス履歴・削除履歴・☆監視) を全て削除する。設定には
    一切触れない。
    """
    from api.deps import get_db
    from repository.reset_repository import delete_all_scraped_data

    conn = get_db()
    delete_all_scraped_data(conn)
    conn.close()
    return {"status": "ok"}
