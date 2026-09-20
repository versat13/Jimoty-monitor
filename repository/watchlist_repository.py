"""
watched_articles テーブルへの読み書きを担うrepository。

「気軽に保存して気軽に消せる」ウォッチリスト機能 (2026-08-24 新設)。
NGルール判定とは独立しており、このrepositoryはON/OFFの管理のみを行う。
表示時にNG判定より優先する処理は、呼び出し元 (api/main.py の
GET /api/articles?visibility=watched 相当) の責務とする。
"""

import sqlite3


def add_watch(conn: sqlite3.Connection, article_id: str, memo: str | None = None) -> None:
    """
    投稿をウォッチリストに追加する。

    既に追加済みの場合は何もしない (UNIQUE制約があるため INSERT OR IGNORE
    を使う。「気軽に追加/解除できる」という要件上、二重登録をエラーに
    する必要はないと判断した)。
    """
    conn.execute(
        "INSERT OR IGNORE INTO watched_articles (article_id, memo) VALUES (?, ?)",
        (article_id, memo),
    )


def remove_watch(conn: sqlite3.Connection, article_id: str) -> None:
    """ウォッチリストから1件解除する。存在しない場合も無視する。"""
    conn.execute("DELETE FROM watched_articles WHERE article_id = ?", (article_id,))


def clear_watches(conn: sqlite3.Connection, article_ids: list[str] | None = None) -> int:
    """
    ウォッチリストを一括解除する (「問い合わせ終了したら一括で消せる
    ボタン」というユーザー要望に対応)。

    Args:
        article_ids: 指定した場合はこれらのみ解除する。Noneなら全件解除する。

    Returns:
        解除した件数
    """
    if article_ids is None:
        cursor = conn.execute("DELETE FROM watched_articles")
    else:
        placeholders = ",".join("?" for _ in article_ids)
        cursor = conn.execute(
            f"DELETE FROM watched_articles WHERE article_id IN ({placeholders})",
            article_ids,
        )
    return cursor.rowcount


def is_watched(conn: sqlite3.Connection, article_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM watched_articles WHERE article_id = ?", (article_id,)
    ).fetchone()
    return row is not None


def get_watched_article_ids(conn: sqlite3.Connection) -> set[str]:
    """ウォッチリストに入っている全article_idを返す。"""
    rows = conn.execute("SELECT article_id FROM watched_articles").fetchall()
    return {r["article_id"] for r in rows}
