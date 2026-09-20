"""
filters/pickup_search_filter.py のユニットテスト。

frontend/src/utils/pickupSearch.js の matchesSearchExpression と
同じ判定基準になっているかを確認する (2026-09-13新設、Discord通知
機能のため)。
"""

from filters.pickup_search_filter import is_valid_pattern, matches_search_expression


def test_empty_pattern_always_matches():
    assert matches_search_expression("何かのタイトル", "説明文", "") is True


def test_invalid_regex_pattern_always_matches():
    # 不正な正規表現 (閉じ括弧なし) は「絞り込みなし」として扱う。
    assert matches_search_expression("何かのタイトル", "説明文", "(未閉鎖") is True


def test_simple_include_word_matches_title():
    assert matches_search_expression("iPhone 13 ジャンク品", None, ".*(iPhone)") is True


def test_simple_include_word_matches_description():
    assert matches_search_expression("スマホ", "iPhone本体のみ", ".*(iPhone)") is True


def test_no_match_when_word_absent():
    assert matches_search_expression("Android端末", "本体のみ", ".*(iPhone)") is False


def test_case_insensitive():
    assert matches_search_expression("iphone 13", None, ".*(IPHONE)") is True


def test_exclude_pattern_built_by_builder():
    # フロントエンドのbuildRegexFromWordsが「ジャンク」を除外語に
    # 指定した場合に生成する形と同じパターン。
    pattern = r"^(?!.*(ジャンク)).*(iPhone)"
    assert matches_search_expression("iPhone 美品", None, pattern) is True
    assert matches_search_expression("iPhone ジャンク品", None, pattern) is False


def test_none_title_and_description_do_not_crash():
    # タイトル・説明文の両方がNoneでも例外を起こさないこと。
    assert matches_search_expression(None, None, ".*(iPhone)") is False
    assert matches_search_expression(None, None, "") is True


def test_is_valid_pattern():
    assert is_valid_pattern("") is True
    assert is_valid_pattern(".*(iPhone)") is True
    assert is_valid_pattern("(未閉鎖") is False
