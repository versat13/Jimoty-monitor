"""
「検索ワードでピックアップするフィルタ」(2026-09-08 新設) の読み書きを
担当するモジュール。

=== 設計メモ ===

NGワード (filters/keyword_filter.py) とは役割が逆で、こちらは
「一致したものだけを抽出・強調表示する」ためのもの。判定自体は
巡回時ではなくクライアントサイド (フロントエンド) の正規表現エンジンで
行うため、このモジュールが提供するのは「検索条件・検索履歴の保存/読み出し」
のみであり、記事データへの判定結果フラグ付けは一切行わない
(ユーザーとの打ち合わせで合意した設計)。

2つの独立した仕組みを扱う:

  1. pickup_search (検索タブ): 恒常的に保存される検索条件。常に1件のみ
     (アプリ全体で共有する単一の設定。scan_settings_repository と
     同じ考え方)。次回このツールを開いたときも同じ条件が自動適用される。

  2. search_history (簡易フィルタの履歴): 「フィルタ」「NG」「すべて」
     「終了」「監視」タブで一時的に使う検索ワードの履歴。検索条件自体は
     都度リセットされるが、打ち込んだ語句の履歴だけは複数件残す。
"""

import json
from dataclasses import dataclass

# 履歴として保持する最大件数。あくまで「直近使ったワードの候補」表示用
# であり、無制限に貯め込む必要はないため上限を設ける。
MAX_SEARCH_HISTORY_ITEMS = 20


@dataclass
class PickupSearchSettings:
    search_expression: str
    include_words: list[str]
    exclude_words: list[str]
    is_builder_synced: bool


def get_pickup_search(conn) -> PickupSearchSettings:
    """
    現在の検索タブ設定を返す。pickup_search にまだ行が無ければ
    「未設定」を表すデフォルト値 (空文字・空リスト・同期済み) を返す。
    """
    row = conn.execute(
        "SELECT search_expression, include_words_json, exclude_words_json, is_builder_synced "
        "FROM pickup_search ORDER BY id LIMIT 1"
    ).fetchone()

    if row is None:
        return PickupSearchSettings(
            search_expression="",
            include_words=[],
            exclude_words=[],
            is_builder_synced=True,
        )

    return PickupSearchSettings(
        search_expression=row["search_expression"] or "",
        include_words=_parse_word_list(row["include_words_json"]),
        exclude_words=_parse_word_list(row["exclude_words_json"]),
        is_builder_synced=bool(row["is_builder_synced"]),
    )


def update_pickup_search(
    conn,
    *,
    search_expression: str,
    include_words: list[str] | None = None,
    exclude_words: list[str] | None = None,
    is_builder_synced: bool = True,
) -> PickupSearchSettings:
    """
    検索タブの条件を更新する (常に1件のみ保持。既存行があれば上書き)。

    Args:
        search_expression: フロントエンドの正規表現エンジンにそのまま
            渡す文字列。空文字は「絞り込みなし」を意味する。
        include_words, exclude_words: 正規表現ビルダーの入力欄の内容
            (次回開いたときにビルダー欄を復元するための補助情報)。
        is_builder_synced: search_expression がビルダーの入力からの
            自動生成のままか (True)、手直しされて食い違っているか
            (False)。手直し後にビルダー欄を操作しても上書きされない
            ようにするためのフラグ (打ち合わせで合意した仕様)。

    Note:
        正規表現として無効な文字列かどうかの検証はここでは行わない
        (呼び出し元のAPI層が re.compile() で検証する。理由:
        このモジュールは「保存する箱」に徹し、正規表現の妥当性という
        フロントエンド側の関心事に依存しないようにするため)。
    """
    include_words_json = json.dumps(include_words or [], ensure_ascii=False)
    exclude_words_json = json.dumps(exclude_words or [], ensure_ascii=False)

    row = conn.execute("SELECT id FROM pickup_search ORDER BY id LIMIT 1").fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO pickup_search (
                search_expression, include_words_json, exclude_words_json,
                is_builder_synced, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (search_expression, include_words_json, exclude_words_json, int(is_builder_synced)),
        )
    else:
        conn.execute(
            """
            UPDATE pickup_search
            SET search_expression = ?, include_words_json = ?, exclude_words_json = ?,
                is_builder_synced = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                search_expression, include_words_json, exclude_words_json,
                int(is_builder_synced), row["id"],
            ),
        )

    conn.commit()
    return get_pickup_search(conn)


def _parse_word_list(raw_json: str | None) -> list[str]:
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(w) for w in parsed]


# ---------------------------------------------------------------------
# 簡易フィルタの検索履歴 (search_history)
# ---------------------------------------------------------------------


def add_search_history(conn, query: str) -> None:
    """
    簡易フィルタで使った検索ワードを履歴に追加する。

    同じ語句を続けて検索した場合に履歴が同じ語句だらけになるのを
    避けるため、既存の同一queryがあれば削除してから追加し直す
    (＝実質的に「最近使った順」に並び替えられる)。
    件数がMAX_SEARCH_HISTORY_ITEMSを超えたら古いものから削除する。
    """
    query = query.strip()
    if not query:
        return

    conn.execute("DELETE FROM search_history WHERE query = ?", (query,))
    conn.execute(
        "INSERT INTO search_history (query, searched_at) VALUES (?, datetime('now'))",
        (query,),
    )

    # 上限を超えた古い履歴を削除
    conn.execute(
        """
        DELETE FROM search_history
        WHERE id NOT IN (
            SELECT id FROM search_history ORDER BY searched_at DESC, id DESC LIMIT ?
        )
        """,
        (MAX_SEARCH_HISTORY_ITEMS,),
    )
    conn.commit()


def list_search_history(conn, limit: int = MAX_SEARCH_HISTORY_ITEMS) -> list[str]:
    """直近使った検索ワードを新しい順に返す。"""
    rows = conn.execute(
        "SELECT query FROM search_history ORDER BY searched_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row["query"] for row in rows]


def clear_search_history(conn) -> int:
    """検索履歴を全件削除する。削除件数を返す。"""
    cursor = conn.execute("SELECT COUNT(*) AS c FROM search_history")
    count = cursor.fetchone()["c"]
    conn.execute("DELETE FROM search_history")
    conn.commit()
    return count
