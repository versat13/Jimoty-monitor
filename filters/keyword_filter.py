"""
NGワード判定 (フィルタリング処理フロー⑦)。

根拠: 仕様書 v1.0 5-2, 5-4, 6章
    ng_keywords：NGワード（タイトル＋一覧説明文の両方に適用）
    ⑦ NGワード判定（タイトル＋一覧説明文）

=== 設計上の絶対原則: 取得漏れゼロ ===

仕様書 5-4 のNGユーザー判定と同じ思想をNGワードにも適用する。
    「取得漏れゼロを最優先するため、除外は表示層でのフィルタに留める」
    「『取りに行かない』判断は一切行わない」

このためこのモジュールが提供するのは「NGワードに一致するか」という
判定関数のみであり、一致した投稿をリストから除去したり、DB保存を
スキップしたりする処理はここには含めない。判定結果 (is_hidden_by_rule
相当のフラグ) を付与するのは呼び出し元 (repository層や表示API) の
責務とする。

=== マッチング方式 ===

実データ (list_real.html の投稿タイトル群) で以下の表記ゆれを確認した:
    - 全角スペースと半角スペースの混在
    - 全角英数字と半角英数字の混在 (例: "ＳＳＤ" と "SSD")
    - 英字の大文字・小文字混在
このため、NGワード・被チェック文字列の両方を
scraper.normalize.normalize_text_for_matching() で正規化してから
部分一致で判定する。正規化により表記ゆれは吸収されるが、
記号・絵文字はそのまま残る (意図的な設計。記号込みのNGワード登録も可能)。
"""

from dataclasses import dataclass

from scraper.normalize import normalize_text_for_matching


@dataclass
class NgKeywordRule:
    """
    永続テーブル ng_keywords 1件分に対応する設定値。

    DB層 (repository/) 実装時に、この構造に対応するテーブルスキーマを
    設計する想定。matched_field は「タイトルでヒットしたのか、説明文で
    ヒットしたのか」をUI側が表示できるようにするための補助情報。
    """

    keyword: str
    is_active: bool = True  # 無効化されたNGワードはチェック対象から外す


@dataclass
class KeywordMatchResult:
    """判定結果。is_hidden_by_rule相当のフラグとして呼び出し元が使う。"""

    matched: bool
    matched_keywords: list[str]  # 一致したNGワードの一覧 (複数ヒットしうる)
    matched_in_title: bool
    matched_in_description: bool


def check_ng_keywords(
    title: str,
    description: str | None,
    ng_rules: list[NgKeywordRule],
) -> KeywordMatchResult:
    """
    タイトル・説明文に対してNGワード一覧を照合する。

    Args:
        title: 一覧ページのタイトル (ListArticle.list_title)
        description: 一覧ページの説明文抜粋 (ListArticle.description_short)。
            Noneの場合はタイトルのみで判定する。
        ng_rules: 永続テーブル ng_keywords から読み込んだルール一覧

    Returns:
        KeywordMatchResult。matched=Falseの場合でも、呼び出し元は
        投稿データそのものの取得・保存を行うこと (仕様書5-4の原則)。
        このフラグは表示のON/OFFにのみ使う。
    """
    normalized_title = normalize_text_for_matching(title)
    normalized_description = normalize_text_for_matching(description) if description else ""

    matched_keywords: list[str] = []
    matched_in_title = False
    matched_in_description = False

    for rule in ng_rules:
        if not rule.is_active:
            continue

        normalized_keyword = normalize_text_for_matching(rule.keyword)
        if not normalized_keyword:
            continue

        hit_title = normalized_keyword in normalized_title
        hit_description = normalized_keyword in normalized_description

        if hit_title or hit_description:
            matched_keywords.append(rule.keyword)
            matched_in_title = matched_in_title or hit_title
            matched_in_description = matched_in_description or hit_description

    return KeywordMatchResult(
        matched=bool(matched_keywords),
        matched_keywords=matched_keywords,
        matched_in_title=matched_in_title,
        matched_in_description=matched_in_description,
    )
