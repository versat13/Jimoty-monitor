"""
category_filter.py のユニットテスト。

実データ (list_real.html) を使い、g-数字形式・スラッグ形式(g-数字を
持たないカテゴリ、例:"その他")の両方でNGカテゴリ判定が機能することを
確認する。

2026-09-08: NGカテゴリの階層区別 (category_level: 'parent'/'mid'/
'leaf') に対応。大カテゴリ・ジャンルを選んだ場合に配下すべてがNGに
なることを検証するテストを追加した。
"""

from pathlib import Path

from filters.category_filter import NgCategoryRule, check_ng_category
from scraper.list_parser import parse_list_page

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "list_real.html"


def test_no_match_when_not_in_rules():
    result = check_ng_category("1205", [NgCategoryRule(category_id="9999", category_level="leaf")])
    assert result.matched is False


def test_match_numeric_category_id():
    result = check_ng_category("1205", [NgCategoryRule(category_id="1205", category_level="leaf")])
    assert result.matched is True
    assert result.matched_category_id == "1205"


def test_inactive_rule_ignored():
    result = check_ng_category(
        "1205", [NgCategoryRule(category_id="1205", category_level="leaf", is_active=False)]
    )
    assert result.matched is False


def test_category_id_none_never_matches():
    """category_id自体がNone(取得できなかった)の場合、誤ってマッチしないこと。"""
    result = check_ng_category(None, [NgCategoryRule(category_id="1205", category_level="leaf")])
    assert result.matched is False


def test_default_category_level_is_leaf():
    """category_levelを省略した場合、後方互換として'leaf'扱いになること。"""
    rule = NgCategoryRule(category_id="1205")
    assert rule.category_level == "leaf"


# ---------------------------------------------------------------------
# 階層判定 (2026-09-08 拡張)
# ---------------------------------------------------------------------


def test_mid_level_matches_category_mid_id():
    """
    ジャンル (category_level='mid') でのNG登録は、投稿の
    category_mid_id (サブジャンルを持つ投稿の中間カテゴリ) が
    一致すればヒットする (例: 「調理器具」をNG指定した場合、
    「鍋、グリル」という詳細カテゴリの投稿もヒットする)。
    """
    result = check_ng_category(
        "1359",
        [NgCategoryRule(category_id="1354", category_level="mid")],
        category_mid_id="1354",
    )
    assert result.matched is True
    assert result.matched_category_id == "1354"


def test_mid_level_matches_leaf_when_no_sub_genre():
    """
    ジャンル (category_level='mid') でのNG登録は、投稿がサブジャンルを
    指定しておらずジャンルのIDがそのまま category_id に入っている
    ケースでもヒットする (ユーザー方針: 「ジャンルを選べばそのジャンルと
    全てのサブジャンルがNG」であり、サブジャンル未指定もジャンル一致
    とみなすべきため)。
    """
    result = check_ng_category(
        "1354",  # サブジャンルが無く、ジャンルIDがそのままcategory_idに
        [NgCategoryRule(category_id="1354", category_level="mid")],
        category_mid_id=None,
    )
    assert result.matched is True
    assert result.matched_category_id == "1354"


def test_leaf_level_does_not_match_mid_id():
    """
    サブジャンル (category_level='leaf') でのNG登録は、詳細カテゴリ
    (category_id) が完全一致する場合のみヒットし、中間カテゴリ
    (category_mid_id) 側では誤ってヒットしないこと。
    """
    result = check_ng_category(
        "1359",
        [NgCategoryRule(category_id="1354", category_level="leaf")],
        category_mid_id="1354",
    )
    assert result.matched is False


def test_parent_level_matches_category_parent_id():
    """
    大カテゴリ (category_level='parent') でのNG登録は、投稿の
    category_parent_id が一致すればヒットする (ジャンル・サブジャンルを
    問わず、その大カテゴリ全体がNGになる)。
    """
    result = check_ng_category(
        "1359",
        [NgCategoryRule(category_id="fur", category_level="parent")],
        category_mid_id="1354",
        category_parent_id="fur",
    )
    assert result.matched is True
    assert result.matched_category_id == "fur"


def test_parent_level_does_not_match_when_parent_id_missing():
    """
    一覧段階では category_parent_id が取得できない (個別ページでのみ
    判明する) ため、category_parent_id=None のときは 'parent' 登録に
    ヒットしないこと (取得漏れゼロの原則: 投稿自体は取得され続け、
    誤って隠されないことを確認する)。
    """
    result = check_ng_category(
        "1359",
        [NgCategoryRule(category_id="fur", category_level="parent")],
        category_mid_id="1354",
        category_parent_id=None,
    )
    assert result.matched is False


def test_parent_and_leaf_both_registered_parent_takes_priority():
    """
    大カテゴリ・詳細カテゴリの両方がNG指定されている場合でも、
    どちらか一方が一致すればNGと判定されること (優先順位は
    matched_category_idの報告内容にのみ影響し、判定結果自体は
    どちらも同じくTrueになる)。
    """
    result = check_ng_category(
        "1359",
        [
            NgCategoryRule(category_id="fur", category_level="parent"),
            NgCategoryRule(category_id="9999", category_level="leaf"),
        ],
        category_parent_id="fur",
    )
    assert result.matched is True
    assert result.matched_category_id == "fur"


def test_detail_category_takes_priority_when_both_match():
    """詳細カテゴリ・中間カテゴリ両方がNG指定されている場合、詳細側が報告されること。"""
    result = check_ng_category(
        "1359",
        [
            NgCategoryRule(category_id="1359", category_level="leaf"),
            NgCategoryRule(category_id="1354", category_level="mid"),
        ],
        category_mid_id="1354",
    )
    assert result.matched is True
    assert result.matched_category_id == "1359"


# --- 実データ (スラッグ形式カテゴリ) ---

def test_real_data_slug_category_match():
    """
    g-数字を持たないスラッグ形式カテゴリ (例: "その他" = "oth") でも
    NGカテゴリ判定が機能すること。
    """
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    articles = parse_list_page(html, current_year=2026)

    rules = [NgCategoryRule(category_id="oth", category_level="leaf")]
    matched_ids = [
        a.article_id for a in articles if check_ng_category(a.category_id, rules).matched
    ]

    assert "1r9zer" in matched_ids
    assert len(matched_ids) >= 1


def test_real_data_all_articles_have_category(  ):
    """
    NGカテゴリ判定の前提として、実データの全投稿がcategory_idを
    持っていること (list_parser.pyのカテゴリ取得漏れ修正の回帰確認を兼ねる)。
    """
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    articles = parse_list_page(html, current_year=2026)

    no_category = [a for a in articles if a.category_id is None]
    assert no_category == []
