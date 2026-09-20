"""
detail_parser.py のユニットテスト。

対象fixture: 実物HTML2件 (2026-08-22 ユーザー提供)
    detail_real.html         : 通常投稿 (テスト出品者A、ELECOM Apple Pencil)
    detail_closed_real.html  : 受付終了投稿 (k、マイヤー電子レンジ用圧力鍋)

当初 (v1.1追補まで) はダミーfixtureを使っていたが、実物検証の結果
セレクタ設計が大きく異なることが判明したため、実物HTMLをそのまま
fixtureとして採用している。これにより「ダミーHTMLに対しては通るが
実物には通らない」という往復コストを避ける。
"""

from pathlib import Path

import pytest

from scraper.detail_parser import parse_detail_page

NORMAL_PATH = Path(__file__).parent / "fixtures" / "detail_real.html"
CLOSED_PATH = Path(__file__).parent / "fixtures" / "detail_closed_real.html"


@pytest.fixture
def normal_html() -> str:
    return NORMAL_PATH.read_text(encoding="utf-8")


@pytest.fixture
def closed_html() -> str:
    return CLOSED_PATH.read_text(encoding="utf-8")


# --- 通常投稿 (detail_real.html) ---

def test_article_id_from_canonical(normal_html):
    result = parse_detail_page(normal_html)
    assert result.article_id == "1jntvx"


def test_full_title(normal_html):
    result = parse_detail_page(normal_html)
    assert result.full_title == "【PCセット割】ELECOM Apple Pencil 交換ペン先 3個"


def test_price_from_structured_table(normal_html):
    result = parse_detail_page(normal_html)
    assert result.price == 240


def test_category_single_level(normal_html):
    """1階層カテゴリ(ジャンル欄にaタグが1つのみ)の場合。"""
    result = parse_detail_page(normal_html)
    assert result.category_id == "1205"
    assert result.category_name == "OA用品"
    assert result.category_mid_id is None  # 1階層のみのため中間カテゴリなし


def test_category_parent_from_breadcrumb(normal_html):
    """親カテゴリはBreadcrumbList (JSON-LD、Thingオブジェクトにネストされた形式) からのみ取得できる。"""
    result = parse_detail_page(normal_html)
    assert result.category_parent_name == "パソコン"
    assert result.category_parent_id == "sale-pcp"


def test_location_from_structured_table(normal_html):
    """
    受け渡し場所テーブルには県名が含まれない (実データ検証で判明)。
    県名はBreadcrumbListから補完する。
    """
    result = parse_detail_page(normal_html)
    assert result.prefecture == "福岡県"  # BreadcrumbListから補完
    assert result.city == "北九州市"
    assert result.ward == "小倉北区"
    assert result.town == "東城野町"
    assert result.area_id == "731"


def test_station_and_railway(normal_html):
    """「最寄駅」という独立行はなく、受け渡し場所欄に同居している。"""
    result = parse_detail_page(normal_html)
    assert result.station_id == "1190607"
    assert result.station_name == "城野駅"
    assert result.railway_line == "JR日豊本線(門司港～佐伯)"


def test_description_full(normal_html):
    """本文は「いいね！」直後のテキストノードとして取得する。"""
    result = parse_detail_page(normal_html)
    assert "型番" in result.description_full
    assert "ELECOM" in result.description_full


def test_seller_info(normal_html):
    result = parse_detail_page(normal_html)
    seller = result.seller
    assert seller is not None
    assert seller.seller_id == "dummy00000000000000000002"
    assert seller.seller_name == "テスト出品者A"
    assert seller.gender == "男性"
    assert seller.post_count == 965
    assert seller.rating == 5.0
    assert seller.rating_count == 548
    assert seller.identity_verified is True
    assert seller.phone_verified is True
    assert "断捨離中" in seller.description


def test_history_datetime_with_time(normal_html):
    """
    追補仕様 v1.1: 個別ページ本文の日時には時刻が含まれる場合がある。
    このサンプルは「作成」のみで「更新」表示はない(更新されていない投稿)。
    """
    result = parse_detail_page(normal_html)
    assert "作成" in result.history_datetimes
    created = result.history_datetimes["作成"]
    assert created.year == 2026
    assert created.month == 8
    assert created.day == 22
    assert created.hour == 17
    assert created.minute == 42


def test_thumbnail_from_og_image(normal_html):
    result = parse_detail_page(normal_html)
    assert "cdn.jmty.jp" in result.thumbnail_url


def test_not_closed(normal_html):
    result = parse_detail_page(normal_html)
    assert result.is_closed is False


# --- 受付終了投稿 (detail_closed_real.html) ---

def test_closed_article_id(closed_html):
    result = parse_detail_page(closed_html)
    assert result.article_id == "1oj5xu"


def test_closed_flag_detected(closed_html):
    """「お問い合わせの受付は終了いたしました。」の検出。"""
    result = parse_detail_page(closed_html)
    assert result.is_closed is True


def test_category_two_levels(closed_html):
    """
    2階層カテゴリ(調理器具 > 鍋、グリル)の場合、末尾(最も詳細)を
    category、それより前を category_mid として扱う。
    """
    result = parse_detail_page(closed_html)
    assert result.category_id == "1359"
    assert result.category_name == "鍋、グリル"
    assert result.category_mid_id == "1354"
    assert result.category_mid_name == "調理器具"


def test_category_parent_with_three_levels(closed_html):
    """
    2026-09-08 バグ修正の回帰テスト。

    大カテゴリ+ジャンル+サブジャンルの3階層すべてが指定されている
    投稿 (生活雑貨 > 調理器具 > 鍋、グリル) では、修正前は
    「末尾から4番目」を大カテゴリとして扱っており、実際には
    「調理器具」(本来のジャンル) を大カテゴリとして誤登録し、
    本来の大カテゴリ「生活雑貨」は取得されていなかった。

    修正後は、パンくずの「先頭2エントリ(ジモティー/売ります・
    あげます)と末尾2エントリ(都道府県/市区町村)を除いた残りの
    個数」で階層を判定するため、大カテゴリ「生活雑貨」を正しく
    取得できることを確認する。
    """
    result = parse_detail_page(closed_html)
    assert result.category_parent_name == "生活雑貨"
    assert result.category_parent_id == "sale-hom"
    # ジャンル・サブジャンルも同時に正しく区別できていること
    assert result.category_mid_name == "調理器具"
    assert result.category_mid_id == "1354"
    assert result.category_name == "鍋、グリル"
    assert result.category_id == "1359"


# --- 大カテゴリのみ指定 (ジャンル・サブジャンル未指定) のケース ---
#
# 実物フィクスチャにこのパターンが無いため、_parse_breadcrumb_json_ld
# を直接呼び出し、最小限のBreadcrumbList (JSON-LD) スニペットで検証する
# (2026-09-08、ユーザーへのヒアリングで判明した3パターン目の仕様)。


def _make_breadcrumb_html(entries: list[tuple[str, str]], title: str) -> str:
    """
    entries: [(name, item_id_path), ...] の先頭から順にBreadcrumbListの
    itemListElementを組み立てる。末尾に投稿タイトルのエントリ(item無し)
    を追加する。
    """
    import json as json_module

    items = []
    for i, (name, item_id) in enumerate(entries, start=1):
        items.append(
            {
                "@type": "ListItem",
                "position": i,
                "item": {"@type": "Thing", "@id": item_id, "name": name},
            }
        )
    items.append({"@type": "ListItem", "position": len(entries) + 1, "name": title})

    data = {
        "@context": "http://schema.org/",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }
    return f'<script type="application/ld+json">{json_module.dumps(data, ensure_ascii=False)}</script>'


def test_category_parent_only_no_genre():
    """
    大カテゴリのみ指定 (ジャンル・サブジャンル未指定) のパンくず
    (ジモティー/売ります・あげます/服・ファッション/福岡県の
    服・ファッション/北九州市の服・ファッション/投稿タイトル、
    全6エントリ=カテゴリ部分1個) では、大カテゴリのみが取得され、
    category_mid_id/category_mid_nameはNoneのままであること。
    """
    from bs4 import BeautifulSoup

    from scraper.detail_parser import _parse_breadcrumb_json_ld

    html = _make_breadcrumb_html(
        [
            ("ジモティー", "/"),
            ("売ります・あげます", "/all/sale"),
            ("服・ファッション", "/all/sale-clo"),
            ("福岡県の服・ファッション", "/fukuoka/sale-clo"),
            ("北九州市の服・ファッション", "/fukuoka/sale-clo/a-731-kitakyushu"),
        ],
        "何かの投稿タイトル",
    )
    soup = BeautifulSoup(html, "lxml")
    result = _parse_breadcrumb_json_ld(soup)

    assert result["category_parent_name"] == "服・ファッション"
    assert result["category_parent_id"] == "sale-clo"
    assert result["category_mid_id"] is None
    assert result["category_mid_name"] is None
    assert result["prefecture"] == "福岡県"


def test_category_parent_and_mid_no_sub_genre():
    """
    大カテゴリ+ジャンル指定 (サブジャンル未指定) のパンくず
    (カテゴリ部分2個) では、大カテゴリ・ジャンルが正しく区別され、
    サブジャンル相当のcategory_id/category_nameにはジャンルの値が
    入ること (ジャンルが「今分かっている最も詳細なカテゴリ」のため)。
    """
    from bs4 import BeautifulSoup

    from scraper.detail_parser import _parse_breadcrumb_json_ld

    html = _make_breadcrumb_html(
        [
            ("ジモティー", "/"),
            ("売ります・あげます", "/all/sale"),
            ("服・ファッション", "/all/sale-clo"),
            ("コート", "/all/sale-clo/g-813"),
            ("福岡県のコート", "/fukuoka/sale-clo/g-813"),
            ("北九州市のコート", "/fukuoka/sale-clo/g-813/a-731-kitakyushu"),
        ],
        "何かの投稿タイトル",
    )
    soup = BeautifulSoup(html, "lxml")
    result = _parse_breadcrumb_json_ld(soup)

    assert result["category_parent_name"] == "服・ファッション"
    assert result["category_parent_id"] == "sale-clo"
    assert result["category_name"] == "コート"
    assert result["category_id"] == "813"
    assert result["category_mid_id"] is None


def test_category_parent_mid_and_sub_genre():
    """
    大カテゴリ+ジャンル+サブジャンル指定 (カテゴリ部分3個) の
    パンくずでは、3階層すべてが正しく区別されること
    (ユーザー提示の実例: 服/ファッション > コート > レディース)。
    """
    from bs4 import BeautifulSoup

    from scraper.detail_parser import _parse_breadcrumb_json_ld

    html = _make_breadcrumb_html(
        [
            ("ジモティー", "/"),
            ("売ります・あげます", "/all/sale"),
            ("服/ファッション", "/all/sale-clo"),
            ("コート", "/all/sale-clo/g-813"),
            ("レディース", "/all/sale-clo/g-837"),
            ("福岡県のレディース", "/fukuoka/sale-clo/g-837"),
            ("北九州市のレディース", "/fukuoka/sale-clo/g-837/a-731-kitakyushu"),
        ],
        "DIESE　レディースL　デニムコート",
    )
    soup = BeautifulSoup(html, "lxml")
    result = _parse_breadcrumb_json_ld(soup)

    assert result["category_parent_name"] == "服/ファッション"
    assert result["category_parent_id"] == "sale-clo"
    assert result["category_mid_name"] == "コート"
    assert result["category_mid_id"] == "813"
    assert result["category_name"] == "レディース"
    assert result["category_id"] == "837"


def test_closed_history_both_dates(closed_html):
    """このサンプルには更新・作成両方の日時がある。"""
    result = parse_detail_page(closed_html)
    assert "更新" in result.history_datetimes
    assert "作成" in result.history_datetimes
    assert result.history_datetimes["更新"].month == 8
    assert result.history_datetimes["更新"].day == 21
    assert result.history_datetimes["作成"].month == 4
    assert result.history_datetimes["作成"].day == 18


def test_closed_description_is_thin(closed_html):
    """
    実データでは本文が実質タイトルの繰り返し程度しかない投稿も存在する。
    これは取得ロジックの不備ではなく実際の投稿内容であるため、
    短い文字列がそのまま返ることを期待する(Noneにはしない)。
    """
    result = parse_detail_page(closed_html)
    assert result.description_full == "マイヤー 電子レンジ用圧力鍋 2.3L"


def test_closed_seller_no_identity_verification(closed_html):
    """この出品者は身分証は未認証、電話番号のみ認証済み。"""
    result = parse_detail_page(closed_html)
    seller = result.seller
    assert seller.seller_name == "テスト出品者D"
    assert seller.gender == "女性"
    assert seller.identity_verified is False
    assert seller.phone_verified is True


def test_closed_seller_no_description_placeholder_excluded(closed_html):
    """
    「自己紹介文が設定されていません」はプレースホルダーであり、
    description は None になるべき (かつ、次に出現する評価コメントを
    誤って拾わないこと)。
    """
    result = parse_detail_page(closed_html)
    assert result.seller.description is None


# --- 相対URLでのseller_profile_url (2026-08-27発見のバグの回帰テスト) ---

def test_seller_profile_url_absolute_when_source_is_relative():
    """
    実データ検証で判明: 出品者プロフィールリンクが相対URL
    (/profiles/xxxx) の場合がある。フロントでwindow.open()する際に
    相対URLのままだと現在のオリジンに対して開こうとして失敗するため、
    パーサー側で必ず絶対URL化しておく必要がある。
    """
    html = """
    <html><body>
    <link rel="canonical" href="https://jmty.jp/fukuoka/sale-oth/article-1abcde">
    <h1>テスト投稿</h1>
    <p>いいね！</p>
    <p>本文テキストです。それなりの長さがあります。</p>
    <table><tr><td>商品価格</td><td>500円</td></tr></table>
    <div>投稿者
      <div>
        <a href="/profiles/relative123">相対出品者</a>
        男性 投稿：10 5.0 (3)
      </div>
    </div>
    </body></html>
    """
    from scraper.detail_parser import parse_detail_page
    result = parse_detail_page(html)
    assert result.seller.seller_profile_url == "https://jmty.jp/profiles/relative123"
    assert result.seller.seller_id == "relative123"


# --- 出品者紹介文の切り詰めバグ (2026-08-28発見の回帰テスト) ---

def test_seller_description_multiline_not_truncated():
    """
    実データ検証で判明: 出品者の紹介文が複数のテキストノードに
    分かれている場合 (改行やbr等)、direct_texts[0]だけを拾うと
    最初の1文だけで切り詰められてしまっていた。get_text()で
    要素内の全テキストを結合するよう修正した後、複数行の紹介文が
    全文取得できることを確認する。
    """
    html = """
    <html><body>
    <link rel="canonical" href="https://jmty.jp/fukuoka/sale-oth/article-1abcde">
    <h1>テスト投稿</h1>
    <p>いいね！</p>
    <p>本文テキストです。それなりの長さがあります。</p>
    <table><tr><td>商品価格</td><td>500円</td></tr></table>
    <div>
      <div>
        <div>投稿者</div>
        <a href="https://jmty.jp/profiles/multiline123">チョコ</a>
        男性 投稿：64 5.0 (14)
        <p>気持ちの良いお取引を心掛けておりますが、複数のお取引希望があった場合は、最初に日時まで決定いただいた方にお譲りいたします。
ご理解いただけない方のコメントご遠慮下さい。</p>
      </div>
    </div>
    </body></html>
    """
    from scraper.detail_parser import parse_detail_page
    result = parse_detail_page(html)
    assert result.seller is not None
    assert "気持ちの良いお取引を心掛けております" in result.seller.description
    assert "ご理解いただけない方のコメントご遠慮下さい" in result.seller.description


# --- 2026-09-07 バグ修正の回帰テスト ---
# fixture: detail_real3_comment_split.html (「フェルトブーツ」1rnjaf、
# ユーザー提供のデバッグ巡回取得HTML。React由来のコメントノードが
# 保持された、加工していない生のHTML)

COMMENT_SPLIT_PATH = Path(__file__).parent / "fixtures" / "detail_real3_comment_split.html"


@pytest.fixture
def comment_split_html() -> str:
    return COMMENT_SPLIT_PATH.read_text(encoding="utf-8")


def test_history_datetime_survives_react_comment_split(comment_split_html):
    """
    「作成<!-- -->2026年9月7日 09:17」のように、Reactのハイドレーション
    用コメント (中身は空) が「作成」と日付本体の間に挟まっていても、
    作成日時が正しく取得できること。

    修正前は find_all(string=re.compile(...)) がテキストノード単体に
    正規表現を適用していたため、コメントで分断された断片同士が
    一致せず history_datetimes が常に空になっていた。
    """
    result = parse_detail_page(comment_split_html)
    assert result.history_datetimes.get("作成") is not None
    assert result.history_datetimes["作成"].year == 2026
    assert result.history_datetimes["作成"].month == 9
    assert result.history_datetimes["作成"].day == 7
    assert result.history_datetimes["作成"].hour == 9
    assert result.history_datetimes["作成"].minute == 17


def test_history_datetime_not_split_by_comment_still_works(normal_html):
    """
    コメントで分断されていない従来形式 ("作成2026年8月22日 17:42" が
    単一のテキストノード) でも、引き続き正しく取得できること
    (get_text()ベースの実装への切り替えによる回帰がないことの確認)。
    """
    result = parse_detail_page(normal_html)
    assert result.history_datetimes.get("作成") is not None


def test_prefecture_extracted_when_category_has_extra_group_level(comment_split_html):
    """
    「靴/バッグ」カテゴリのように、BreadcrumbListの階層に
    「カテゴリグループ」が1段多く挟まる場合でも、都道府県名が
    正しく抽出できること (末尾からの相対位置判定への変更の回帰テスト)。

    階層: ジモティー/売ります・あげます/靴・バッグ/靴/ブーツ/
          福岡県のブーツ/北九州市のブーツ/(投稿タイトル)
    修正前は position==5 (実際には「ブーツ」というカテゴリ名) を
    都道府県として解釈しようとして prefecture が None になっていた。
    """
    result = parse_detail_page(comment_split_html)
    assert result.prefecture == "福岡県"
    assert result.category_name == "ブーツ"


def test_prefecture_extraction_unaffected_for_normal_category_depth(normal_html, closed_html):
    """
    従来通りの階層の深さ (カテゴリグループを挟まない) のカテゴリでも、
    末尾からの相対位置判定に変更した後も引き続き正しく都道府県・
    カテゴリ名が取れること。
    """
    r1 = parse_detail_page(normal_html)
    assert r1.prefecture == "福岡県"
    assert r1.category_name == "OA用品"

    r2 = parse_detail_page(closed_html)
    assert r2.prefecture == "福岡県"
    assert r2.category_name == "鍋、グリル"


def test_rating_zero_without_count_parenthesis(comment_split_html):
    """
    評価が1件も付いていない出品者は「0.0」単体 (件数の括弧書きなし) で
    表示されるため、rating=0.0, rating_count=0 として明示的に
    取得できること。修正前はこのパターンに一致せず、rating・
    rating_countともにNoneのままだった。
    """
    result = parse_detail_page(comment_split_html)
    assert result.seller is not None
    assert result.seller.rating == 0.0
    assert result.seller.rating_count == 0


def test_rating_with_count_still_works(normal_html):
    """
    件数付きの通常表示 ("5.0 (548)" 等) が、0.0単体パターンの
    フォールバック追加によって壊れていないことの確認。
    """
    result = parse_detail_page(normal_html)
    assert result.seller is not None
    assert result.seller.rating is not None
    assert result.seller.rating_count is not None
    assert result.seller.rating_count > 0
