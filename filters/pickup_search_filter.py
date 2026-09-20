"""
「検索」タブ (pickup_search) の正規表現マッチ判定。

frontend/src/utils/pickupSearch.js の matchesSearchExpression と
同じロジックをPython側に移植したもの (2026-09-13新設、Discord通知
機能のため)。

=== 移植の経緯 ===

pickup_search の判定は本来フロントエンド (JavaScriptの正規表現エンジン)
で行う設計であり (repository/pickup_search_repository.py のdocstring
参照)、バックエンド側には判定ロジックが存在しなかった。

Discord通知 (「検索タブにヒットした新規投稿が見つかったら通知する」)
は巡回処理 (scheduler/scan_runner.py、Pythonで実行) の最中に判定する
必要があるため、同じ判定ロジックをこちらにも移植した。

判定基準はフロントエンドと同一にする (list_title と
description_short の両方を対象、大文字小文字を区別しない、空文字・
不正な正規表現は「絞り込みなし」として常にマッチ扱い)。ただし
JavaScriptの正規表現とPythonのreモジュールは構文に細かな差異が
あるため、フロントエンドのビルダー機能 (含める/除外するワードの
指定) で生成される範囲の正規表現 (エスケープ済みの平文ワードを
`|`・否定先読み `(?!...)` で組み合わせたもの) では通常一致するが、
生の正規表現欄にJavaScript固有の構文 (例: 名前付きキャプチャの
一部記法) が手で書き込まれていた場合、Python側でコンパイルエラーに
なる可能性がある。その場合は「絞り込みなし」として扱う (フロント
エンド側の isValidRegex() が false を返すケースと同じ扱い)。
"""

import re


def is_valid_pattern(pattern: str) -> bool:
    """正規表現文字列が有効かどうかを検証する。空文字は常に有効。"""
    if not pattern:
        return True
    try:
        re.compile(pattern, re.IGNORECASE)
        return True
    except re.error:
        return False


def matches_search_expression(list_title: str | None, description_short: str | None, pattern: str) -> bool:
    """
    投稿のタイトル・説明文抜粋が検索条件にマッチするかどうかを判定する。

    list_title と description_short の両方を対象にする (NGワード側の
    判定範囲、およびフロントエンドの matchesSearchExpression に合わせて
    いる)。空文字・不正な正規表現の場合は「絞り込みなし」として常に
    True を返す。
    """
    if not pattern:
        return True
    if not is_valid_pattern(pattern):
        return True

    haystack = f"{list_title or ''} {description_short or ''}"
    return re.search(pattern, haystack, re.IGNORECASE) is not None
