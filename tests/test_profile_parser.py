"""
profile_parser.py のユニットテスト。

対象fixture: profile_closed_real.html (実物HTML、2026-08-22 ユーザー提供)
    「ユーザーページサンプル（終了済み含む）」というファイル名だが、
    実際に確認できた投稿一覧10件はいずれも「売ります」区分のみで、
    受付終了状態の表示はこのページ(1ページ目)には含まれていなかった。
    受付終了の判定は detail_parser.is_closed に委ねる設計としている
    (profile_parser.py のdocstring参照)。

評価コメント本文 (削除済み投稿/退会済みユーザーの欠損パターン) は
実データを未入手のため、このテストファイルでは検証しない。
evaluations が常に空リストで返ることのみ確認する。
"""

from pathlib import Path

import pytest

from scraper.profile_parser import parse_profile_page

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "profile_closed_real.html"


@pytest.fixture
def html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_seller_name(html):
    result = parse_profile_page(html)
    assert result.seller_name == "テスト出品者D"


def test_gender(html):
    result = parse_profile_page(html)
    assert result.gender == "女性"


def test_verification(html):
    """この出品者は電話番号のみ認証済み、身分証は未認証。"""
    result = parse_profile_page(html)
    assert result.identity_verified is False
    assert result.phone_verified is True


def test_rating_breakdown(html):
    """
    評価内訳はテキストラベルがなく数値の出現順(良い→普通→悪い)で
    判定する (実データ検証で判明)。
    """
    result = parse_profile_page(html)
    assert result.rating_good == 10
    assert result.rating_normal == 0
    assert result.rating_bad == 0
    assert result.rating_count == 10  # 内訳の合算値


def test_registration_date_and_occupation(html):
    result = parse_profile_page(html)
    assert result.registration_date_raw == "2020/12/11"
    assert result.residential_area == "福岡県北九州市"
    assert result.occupation == "未登録"


def test_description_placeholder_returns_none(html):
    """「自己紹介文が入力されていません。」はプレースホルダーとしてNoneになること。"""
    result = parse_profile_page(html)
    assert result.description is None


def test_other_articles_count(html):
    """このページ(1ページ目)には投稿一覧が10件表示されている。"""
    result = parse_profile_page(html)
    assert len(result.other_articles) == 10


def test_other_articles_total_count_from_pagination_text(html):
    """
    2026-09-04 追加: 「全30件中 1-10件表示」というテキストから
    other_articles_total_count / post_count が抽出できること。
    投稿一覧は11件以上だと複数ページに分かれるため、このページ単体の
    other_articles件数 (10件) とは一致しない点に注意 (別途巡回する側の
    責務、scheduler/job.py参照)。
    """
    result = parse_profile_page(html)
    assert result.other_articles_total_count == 30
    assert result.post_count == 30


def test_next_page_url_extracted(html):
    """
    2026-09-04 追加: 次ページへのリンク (rel=next, id=btn_next) から
    next_page_url が絶対URLで取得できること。
    """
    result = parse_profile_page(html)
    assert result.next_page_url == "https://jmty.jp/profiles/dummy00000000000000000007?page=2"


def test_next_page_url_none_when_no_next_link(html):
    """次へリンクが無いHTML (最終ページ相当) ではNoneになること。"""
    last_page_html = html.replace(
        '<a rel=next id=btn_next href="https://jmty.jp/profiles/dummy00000000000000000007?page=2">次へ</a>',
        "",
    )
    result = parse_profile_page(last_page_html)
    assert result.next_page_url is None


def test_other_article_fields(html):
    """投稿一覧の固定順テキストノード(区分/タイトル/価格/地域/説明/更新日)の解析。"""
    result = parse_profile_page(html)
    first = result.other_articles[0]
    assert first.article_id == "1rbvrt"
    assert first.listing_type == "売ります"
    assert first.title == "マクスゼン 2ドア冷蔵庫 117L"
    assert first.price == 800
    assert first.location == "北九州市"
    assert first.updated_date_raw == "08/22"


def test_other_article_urls_backward_compat(html):
    result = parse_profile_page(html)
    assert len(result.other_article_urls) == 10
    assert all(isinstance(u, str) for u in result.other_article_urls)


def test_evaluations_empty_pending_real_data(html):
    """
    評価コメント本文は実データ未入手のため、常に空リストを返す
    (evaluations一覧ページのHTMLが手に入り次第、別途対応する)。
    """
    result = parse_profile_page(html)
    assert result.evaluations == []
