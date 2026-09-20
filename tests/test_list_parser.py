"""
list_parser.py のユニットテスト。

対象fixture: tests/fixtures/list_sample.html
    投稿1: 通常投稿 (駅情報あり、お気に入り数あり) - article_id=1jntvx
    投稿2: 通常投稿 (駅情報なし、お気に入り数空欄)  - article_id=1rbrbe
    投稿3: alliance広告 (除外されるべき)            - 求人
    投稿4: PR枠 (from=pr、広告ではなく通常投稿扱い)  - article_id=1r8jq4

注意: このfixtureはWeb取得結果(Markdown化済み)から推定構築したダミーHTMLであり、
実サイトの生DOMそのものではない。実サイトに対する最終検証は実行環境
(ユーザーのローカルPC)で行うこと。
"""

from pathlib import Path

import pytest

from scraper.list_parser import extract_total_count, parse_list_page

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "list_sample.html"


@pytest.fixture
def html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_ad_is_excluded(html):
    """alliance-広告は結果に含まれないこと。"""
    articles = parse_list_page(html, current_year=2026)
    ids = [a.article_id for a in articles]
    assert "alliance_980712" not in ids
    # 求人特有のタイトルが結果に混ざっていないことも確認
    assert not any("派遣社員" in a.list_title for a in articles)


def test_normal_article_count(html):
    """広告1件を除いた3件が取得できること。"""
    articles = parse_list_page(html, current_year=2026)
    assert len(articles) == 3


def test_article_id_extraction(html):
    articles = parse_list_page(html, current_year=2026)
    ids = {a.article_id for a in articles}
    assert ids == {"1jntvx", "1rbrbe", "1r8jq4"}


def test_price_normalization(html):
    """価格文字列が数値化されていること。広告の時給表記が混ざらないこと。"""
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].price == 240
    assert by_id["1rbrbe"].price == 3000
    assert by_id["1r8jq4"].price == 29800


def test_category_extracted_from_list_page(html):
    """カテゴリが詳細ページなしで一覧段階から取得できること (訂正済み仕様)。"""
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].category_id == "1205"
    assert by_id["1jntvx"].category_name == "OA用品"


def test_station_optional(html):
    """駅情報は必須ではなく、存在しない投稿ではNoneになること。"""
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].station_id == "1190607"
    assert by_id["1jntvx"].station_name == "城野駅"
    # スーツケース投稿には駅情報がない
    assert by_id["1rbrbe"].station_id is None
    assert by_id["1rbrbe"].station_name is None


def test_area_extraction(html):
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].area_id == "731"
    assert by_id["1jntvx"].area_name == "北九州市"


def test_favorite_count_null_vs_zero(html):
    """
    お気に入り数のNULL/0区別 (HTML解析仕様確定版 15 の推奨仕様)。
    空欄の投稿はNone、数値がある投稿はintになること。
    """
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].favorite_count == 1
    assert by_id["1rbrbe"].favorite_count is None  # 空欄 → NULL


def test_tags_separated_from_category(html):
    """タグ(ELECOM等)がカテゴリと混同されず別フィールドに入ること。"""
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert "ELECOM" in by_id["1jntvx"].tags
    assert by_id["1jntvx"].category_name == "OA用品"  # タグと混ざっていない


def test_pr_slot_flagged_not_excluded(html):
    """
    from=pr のPR枠は広告として除外せず、フラグ付きの通常投稿として扱うこと。
    (このパターンはHTML解析仕様確定版に未記載の新規発見のため、
     除外はせずフラグ保持に留める仕様とした)
    """
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1r8jq4"].is_pr_slot is True
    assert by_id["1jntvx"].is_pr_slot is False


def test_thumbnail_url_extracted(html):
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert by_id["1jntvx"].thumbnail_url is not None
    assert "cdn.jmty.jp" in by_id["1jntvx"].thumbnail_url


def test_description_short_extracted(html):
    articles = parse_list_page(html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    assert "Apple Pencil" in by_id["1jntvx"].description_short


# =============================================================
# 実物HTMLでの検証 (2026-08-22 ユーザー提供、list_real.html)
#
# 上記のダミーfixtureテストは境界ケースの単体検証用に維持しつつ、
# こちらは実際のジモティーのページで取得漏れ・誤分類がないかを
# 検証する回帰テスト。list_real.html は北九州市の全カテゴリ一覧
# (広告ブロックしていない状態、59件の<li>を含む)。
# =============================================================

REAL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "list_real.html"


@pytest.fixture
def real_html() -> str:
    return REAL_FIXTURE_PATH.read_text(encoding="utf-8")


def test_real_total_li_count(real_html):
    """li.p-articles-list-item の総数は59件(広告7件を含む)。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(real_html, "lxml")
    assert len(soup.select("li.p-articles-list-item")) == 59


def test_real_extraction_count_matches_non_ad(real_html):
    """
    広告(alliance-)7件を除いた52件が取得できること (取得漏れゼロ)。

    このテストは過去に2件のPR枠 (?from=pr) が
    「タイトルリンクが2つあり最初の<a>が決済導線リンク」という
    実物特有の構造によって誤って脱落するバグを検出したテストである。
    """
    articles = parse_list_page(real_html, current_year=2026)
    assert len(articles) == 52


def test_real_pr_slot_not_lost(real_html):
    """
    PR枠(?from=pr)はタイトルリンクが2つある(決済導線+本来のリンク)が、
    article_idが正しく抽出され、is_pr_slot=Trueとして残ること。
    """
    articles = parse_list_page(real_html, current_year=2026)
    pr_articles = [a for a in articles if a.is_pr_slot]
    assert len(pr_articles) == 2
    ids = {a.article_id for a in pr_articles}
    assert ids == {"1r9zer", "1r8jq4"}


def test_real_no_category_loss(real_html):
    """
    g-数字を持たないカテゴリURL (例: /all/sale-oth) を持つ投稿でも、
    カテゴリが取得漏れにならないこと。
    """
    articles = parse_list_page(real_html, current_year=2026)
    no_category = [a for a in articles if a.category_name is None]
    assert no_category == []


def test_real_category_slug_not_misfiled_as_tag(real_html):
    """
    「その他」のようなg-数字を持たないカテゴリ名が、タグ配列に
    誤って混入していないこと。
    """
    articles = parse_list_page(real_html, current_year=2026)
    by_id = {a.article_id: a for a in articles}
    pr_slot = by_id["1r9zer"]
    assert pr_slot.category_name == "その他"
    assert "その他" not in pr_slot.tags
    assert pr_slot.tags == ["商品"]


def test_real_ad_urls_excluded(real_html):
    """alliance-を含む投稿が結果に一切含まれていないこと。"""
    articles = parse_list_page(real_html, current_year=2026)
    for a in articles:
        assert "alliance-" not in a.url


# =============================================================
# 相対URL形式のカテゴリリンクに関する回帰テスト
# (2026-08-23、ユーザーの実行環境で発見されたバグ)
#
# 一覧ページ内で、同じ .p-item-supplementary-info でも
# 投稿によって絶対URL (https://jmty.jp/all/sale-oth) と
# 相対URL (/all/sale-oth) が混在することが実データで判明した。
# 当初 is_category_slug_url() は絶対URLしか想定しておらず、
# 相対URL形式の投稿でカテゴリが一切取得できず、キーワードタグにも
# 分類されず消失するというデータロスがあった。
#
# ユーザーが scripts/debug_category_loss.py で実際に取得した
# 一覧ページから、影響を受けていた12件のうち代表的なDOM構造を
# そのまま再現し、二度と回帰しないことを確認する。
# =============================================================

def test_relative_url_category_link_is_recognized():
    """
    相対URL形式 (/all/sale-oth) のカテゴリリンクでも、
    category_id/category_nameが正しく取得できること。

    実際にユーザー環境で確認されたDOM構造 (article_id=1r9ziu、
    「GEX製の水槽と水槽台のセット」) をそのまま再現している。
    """
    from bs4 import BeautifulSoup
    from scraper.list_parser import parse_list_item

    html = """
    <li class="p-articles-list-item">
    <div class="p-item-title">
    <a href="https://jmty.jp/fukuoka/sale-oth/article-1r9ziu">GEX製の水槽と水槽台のセット</a>
    </div>
    <div class="p-item-supplementary-info">
    <a href="/fukuoka/sale-oth/g-all/a-731-kitakyushu">北九州市</a>
    <a href="/fukuoka/sale-oth/g-all/s-9990802">平和通駅</a>
    <a href="/all/sale-oth">その他</a>
    </div>
    </li>
    """
    soup = BeautifulSoup(html, "lxml")
    item = soup.select_one("li.p-articles-list-item")
    result = parse_list_item(item, current_year=2026)

    assert result is not None
    assert result.category_id == "oth"
    assert result.category_name == "その他"
    assert result.tags == []  # カテゴリがタグに誤混入していないこと


def test_relative_url_category_with_keyword_tag_block():
    """
    相対URL形式のカテゴリ + 別ブロックのキーワードタグが両方存在する
    パターン (article_id=1mjuw9、「無印良品 アルバム」相当) の検証。
    キーワードタグ (/all/sale-kw-...) は引き続きtagsに分類されること。
    """
    from bs4 import BeautifulSoup
    from scraper.list_parser import parse_list_item

    html = """
    <li class="p-articles-list-item">
    <div class="p-item-title">
    <a href="https://jmty.jp/fukuoka/sale-oth/article-1mjuw9">無印良品 アルバム</a>
    </div>
    <div class="p-item-supplementary-info">
    <a href="/fukuoka/sale-oth/g-all/a-731-kitakyushu">北九州市</a>
    <a href="/fukuoka/sale-oth/g-all/s-9990916">楠橋駅</a>
    <a href="/all/sale-oth">その他</a>
    </div>
    <div class="p-item-supplementary-info">
    <a href="/all/sale-kw-%E7%84%A1%E5%8D%B0%E8%89%AF%E5%93%81">無印良品</a>
    </div>
    </li>
    """
    soup = BeautifulSoup(html, "lxml")
    item = soup.select_one("li.p-articles-list-item")
    result = parse_list_item(item, current_year=2026)

    assert result.category_id == "oth"
    assert result.category_name == "その他"
    assert result.tags == ["無印良品"]


def test_relative_url_category_food():
    """相対URL形式で「食品」カテゴリ (/all/sale-food) も正しく判定されること。"""
    from bs4 import BeautifulSoup
    from scraper.list_parser import parse_list_item

    html = """
    <li class="p-articles-list-item">
    <div class="p-item-title">
    <a href="https://jmty.jp/fukuoka/sale-food/article-1rboqt">煎茶 玄米茶</a>
    </div>
    <div class="p-item-supplementary-info">
    <a href="/fukuoka/sale-food/g-all/a-731-kitakyushu">北九州市</a>
    <a href="/all/sale-food">食品</a>
    </div>
    </li>
    """
    soup = BeautifulSoup(html, "lxml")
    item = soup.select_one("li.p-articles-list-item")
    result = parse_list_item(item, current_year=2026)

    assert result.category_id == "food"
    assert result.category_name == "食品"


def test_absolute_and_relative_category_urls_both_work_in_same_page():
    """
    絶対URLと相対URLのカテゴリリンクが同一ページ内に混在していても、
    両方とも正しく取得できること (実際のジモティー一覧ページで
    確認された挙動の揺れに対する回帰確認)。
    """
    from bs4 import BeautifulSoup
    from scraper.list_parser import parse_list_page

    html = """
    <html><body><ul>
    <li class="p-articles-list-item">
    <div class="p-item-title"><a href="https://jmty.jp/fukuoka/sale-oth/article-aaa111">投稿A(絶対URL)</a></div>
    <div class="p-item-supplementary-info">
    <a href="https://jmty.jp/all/sale-oth">その他</a>
    </div>
    </li>
    <li class="p-articles-list-item">
    <div class="p-item-title"><a href="https://jmty.jp/fukuoka/sale-oth/article-bbb222">投稿B(相対URL)</a></div>
    <div class="p-item-supplementary-info">
    <a href="/all/sale-oth">その他</a>
    </div>
    </li>
    </ul></body></html>
    """
    articles = parse_list_page(html, current_year=2026)
    assert len(articles) == 2
    by_id = {a.article_id: a for a in articles}
    assert by_id["aaa111"].category_name == "その他"
    assert by_id["bbb222"].category_name == "その他"


# =============================================================
# サムネイル画像セレクタに関する回帰テスト
# (2026-08-24、React UI実装時のスクリーンショット確認で発見)
#
# 当初 THUMBNAIL_IMG = ".p-item-image img" としていたが、
# 実際のジモティーのDOM構造では p-item-image は img タグ自身の
# クラスであり (親要素は p-item-image-component)、子孫セレクタでは
# 一致しないため、全件で thumbnail_url が None になっていた。
# =============================================================

def test_thumbnail_extracted_from_real_data(real_html):
    """
    実データで、Base64データURL形式のサムネイル画像が
    正しく取得できる投稿が存在すること (list_real.html は
    SingleFileで保存されたHTMLのため、遅延読み込み画像の一部は
    src属性自体が失われているが、取得できているものは正しく拾える
    ことを確認する)。
    """
    articles = parse_list_page(real_html, current_year=2026)
    with_thumbnail = [a for a in articles if a.thumbnail_url]
    assert len(with_thumbnail) > 0
    # data URL形式であることの確認 (Base64インライン画像)
    assert with_thumbnail[0].thumbnail_url.startswith("data:image/")


# ---------------------------------------------------------------------
# extract_total_count (2026-09-14新設、更新中の進捗バー用)
# ---------------------------------------------------------------------


def test_extract_total_count_from_real_html(real_html):
    """
    list_real.html の「全242690件中 1-50件表示」から総件数
    242690 を抽出できること。
    """
    assert extract_total_count(real_html) == 242690


def test_extract_total_count_returns_none_when_element_missing():
    """c-paginate-navi要素自体が無いHTMLではNoneを返すこと。"""
    html = "<html><body><div>no paginate navi here</div></body></html>"
    assert extract_total_count(html) is None


def test_extract_total_count_returns_none_when_text_unparseable():
    """要素はあるが件数の数値パターンが無い場合はNoneを返すこと。"""
    html = '<html><body><div class="c-paginate-navi">該当する投稿がありません</div></body></html>'
    assert extract_total_count(html) is None


def test_extract_total_count_handles_comma_formatted_number():
    """カンマ区切りの件数表記も正しく数値化できること。"""
    html = '<html><body><div class="c-paginate-navi">全1,234件中 1-50件表示</div></body></html>'
    assert extract_total_count(html) == 1234


def test_extract_total_count_handles_small_number_without_comma():
    """3桁以下(カンマなし)の件数も正しく抽出できること。"""
    html = '<html><body><div class="c-paginate-navi">全42件中 1-42件表示</div></body></html>'
    assert extract_total_count(html) == 42
