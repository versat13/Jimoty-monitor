"""
keyword_filter.py のユニットテスト。

実データ (list_real.html) を使って、実際の投稿タイトルに対する
表記ゆれ吸収マッチングが機能することを確認する。
"""

from pathlib import Path

import pytest

from filters.keyword_filter import NgKeywordRule, check_ng_keywords
from scraper.list_parser import parse_list_page

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "list_real.html"


@pytest.fixture
def articles():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    return parse_list_page(html, current_year=2026)


def test_no_match_returns_false():
    result = check_ng_keywords("普通のタイトル", "普通の説明文です", [NgKeywordRule(keyword="求人")])
    assert result.matched is False
    assert result.matched_keywords == []


def test_simple_title_match():
    result = check_ng_keywords("激安ジャンク品セット", None, [NgKeywordRule(keyword="ジャンク")])
    assert result.matched is True
    assert result.matched_in_title is True
    assert result.matched_in_description is False
    assert "ジャンク" in result.matched_keywords


def test_description_match():
    result = check_ng_keywords(
        "普通のタイトル", "この商品はジャンク品です", [NgKeywordRule(keyword="ジャンク")]
    )
    assert result.matched is True
    assert result.matched_in_title is False
    assert result.matched_in_description is True


def test_matches_both_title_and_description():
    result = check_ng_keywords(
        "ジャンク品セール", "ジャンクなので注意", [NgKeywordRule(keyword="ジャンク")]
    )
    assert result.matched is True
    assert result.matched_in_title is True
    assert result.matched_in_description is True


def test_inactive_rule_is_ignored():
    """is_active=False のルールは判定対象から除外されること。"""
    result = check_ng_keywords(
        "求人あります", None, [NgKeywordRule(keyword="求人", is_active=False)]
    )
    assert result.matched is False


def test_multiple_keywords_all_reported():
    """複数のNGワードに一致する場合、全て報告されること。"""
    result = check_ng_keywords(
        "ジャンク品 求人あり", None,
        [NgKeywordRule(keyword="ジャンク"), NgKeywordRule(keyword="求人")],
    )
    assert result.matched is True
    assert set(result.matched_keywords) == {"ジャンク", "求人"}


def test_description_none_is_safe():
    """description=None でもエラーにならず、タイトルのみで判定されること。"""
    result = check_ng_keywords("求人あります", None, [NgKeywordRule(keyword="求人")])
    assert result.matched is True


def test_empty_keyword_rule_never_matches():
    """空文字列のNGワードは、常に部分一致してしまう事故を避けるため無視されること。"""
    result = check_ng_keywords("何かのタイトル", "何かの説明", [NgKeywordRule(keyword="")])
    assert result.matched is False


# --- 表記ゆれ吸収 (実データベース) ---

def test_fullwidth_keyword_matches_halfwidth_text():
    """全角で登録したNGワードが、半角表記の実際の投稿タイトルにヒットすること。"""
    result = check_ng_keywords(
        "lenovo Win11 SSD Office互換", None, [NgKeywordRule(keyword="ＳＳＤ")]
    )
    assert result.matched is True


def test_halfwidth_keyword_matches_fullwidth_text():
    """半角で登録したNGワードが、全角表記のテキストにヒットすること。"""
    result = check_ng_keywords("ＳＳＤ搭載モデル", None, [NgKeywordRule(keyword="SSD")])
    assert result.matched is True


def test_case_insensitive_match():
    """英字の大文字・小文字を区別せずヒットすること。"""
    result = check_ng_keywords("windows搭載パソコン", None, [NgKeywordRule(keyword="Windows")])
    assert result.matched is True


def test_real_data_ssd_matches_multiple_articles(articles):
    """
    実データ検証: 全角「ＳＳＤ」というNGワード登録で、
    タイトル(半角SSD)・説明文(半角SSD)の両方にヒットする投稿が
    それぞれ存在すること。
    """
    rule = [NgKeywordRule(keyword="ＳＳＤ")]
    title_hits = []
    description_hits = []
    for a in articles:
        result = check_ng_keywords(a.list_title, a.description_short, rule)
        if result.matched_in_title:
            title_hits.append(a.article_id)
        if result.matched_in_description:
            description_hits.append(a.article_id)

    assert "1razhd" in title_hits  # "SSD・Office互換" を含むタイトル
    assert "1lwjiq" in description_hits  # 説明文に "SSD240G" を含む投稿


def test_real_data_no_false_positive_on_common_word():
    """
    誤検出のないことの確認: 実データ中のどの投稿にも含まれないはずの
    架空のNGワードでは何もヒットしないこと。
    """
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    articles_list = parse_list_page(html, current_year=2026)
    rule = [NgKeywordRule(keyword="絶対に存在しないはずの架空キーワードXYZ123")]

    matched_any = any(
        check_ng_keywords(a.list_title, a.description_short, rule).matched
        for a in articles_list
    )
    assert matched_any is False
