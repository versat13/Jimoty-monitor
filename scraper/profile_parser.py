"""
プロフィールページ (/profiles/{seller_id}) パーサー。

根拠: docs/HTML解析仕様_v1.1_追補版.md 追補3
実データ全面書き換え: 2026-08-22
    実物HTML (ユーザー提供の実サンプル
    「広告ブロックしてる、ユーザーページサンプル（終了済み含む）.html」) を
    検証した結果、当初想定していたクラス名 (p-profile-*) は一切存在しないと
    判明した。プロフィールページは大部分がハッシュ化クラスだが、
    一覧セクションの投稿リンクにのみ意味のあるクラス名 (portal_list_link)
    が残っている。統計情報は <dt>/<dd> の定義リスト構造で表現されている。

位置づけ: 仕様書 v1.0 の当初設計にはこのページ種別への直接アクセスは
なかったが、追補調査により「良い出品者の他投稿を見る」導線 (仕様書 5-4)
や出品者統計を、詳細ページ経由より少ないアクセス回数で実現できると
判明したため新設する。

=== 実データ検証で判明した制約 ===

1. 評価内訳 (良い/普通/悪い) はテキストラベルを持たず、
   画像アイコン(base64)と数値が交互に並ぶ構造になっている:
       <dd><img.../> 10 <img.../> 0 <img.../> 0</dd>
   アイコン画像のハッシュ判別は行わず、出現順が
   「良い→普通→悪い」で固定という仕様書の記述を信頼して位置で割り当てる。
   (画像自体の判別ロジックを持たない設計判断: バッジ画像のBase64が
   将来変わる可能性があり、位置ベースの方が堅牢)

2. 評価コメント本文は、少なくとも1ページ目のHTMLには含まれておらず
   「評価一覧」リンクは #evaluations というページ内アンカーのみで、
   実データは別途JS等で動的取得されている可能性が高い。
   このため評価コメントのパース (欠損パターン対応含む) は
   本モジュールでは実装せず、取得できたらNoneのまま返す。
   実際に評価コメント一覧ページ(別URL)のHTMLが手に入った時点で
   別途対応する。

3. 投稿一覧の各アイテムは a.portal_list_link 直下に、
   区分/タイトル/価格/地域/説明抜粋/更新日 の6テキストノードが
   固定順で並ぶ。この1ページのサンプルには「受付終了」等の
   状態ラベルは出現しなかった (全10件が「売ります」のみ)。
   受付終了状態の見た目は個別ページ側 (detail_parser.is_closed) の
   判定に委ね、本モジュールでは投稿一覧のステータス判定を
   持たせない設計とする。
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString

from scraper.normalize import normalize_price
from scraper.selectors.url_patterns import extract_article_id, to_absolute_url


@dataclass
class EvaluationComment:
    """
    評価コメント1件。

    現時点 (2026-08-22) では実データに評価コメント本文を含むページを
    未入手のため、このデータクラスの構造は追補版v1.1時点の設計を
    暫定的に維持する。欠損パターン(削除済み投稿/退会済みユーザー)への
    対応は、実データ入手後に再検証する。
    """

    rating_label: str | None
    evaluator_name: str | None
    evaluator_profile_url: str | None
    evaluator_withdrawn: bool
    target_article_title: str | None
    target_article_url: str | None
    target_article_deleted: bool
    date_raw: str | None
    comment: str | None


@dataclass
class ProfileArticleSummary:
    """プロフィールページの投稿一覧1件分 (仕様書5-4の「他の投稿」導線に対応)。"""

    article_id: str | None
    url: str | None
    listing_type: str | None  # 「売ります」「あげます」等の区分
    title: str | None
    price: int | None
    location: str | None
    description_short: str | None
    updated_date_raw: str | None  # 「08/22」のようなMM/DD表記


@dataclass
class ProfileInfo:
    """プロフィールページから取得できる出品者統計 (追補版 v1.1 追補3)。"""

    seller_name: str | None  # ニックネーム
    post_count: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    rating_good: int | None = None
    rating_normal: int | None = None
    rating_bad: int | None = None
    registration_date_raw: str | None = None
    residential_area: str | None = None
    occupation: str | None = None
    gender: str | None = None
    identity_verified: bool = False
    phone_verified: bool = False
    description: str | None = None
    evaluations: list[EvaluationComment] = field(default_factory=list)
    other_articles: list[ProfileArticleSummary] = field(default_factory=list)
    other_article_urls: list[str] = field(default_factory=list)  # 後方互換用
    # 2026-09-04 追加: 投稿一覧のページネーション関連。
    # プロフィールページの投稿一覧は「受付中」「受付終了」の大区分の中で
    # 最終更新日順に並び、11件以上ある場合は複数ページに分かれる
    # (?page=2, ?page=3, ... / 末尾に <a rel=next id="btn_next"> がある)。
    #
    # 2026-09-04 同日中に方針転換: 当初は呼び出し元 (scheduler/job.py の
    # fetch_seller_profile_on_demand) が next_page_url を辿って全ページを
    # 合算する設計だったが、恒常的に大量出品する出品者では「更新」1回
    # あたりのアクセス数が無視できなくなるため撤回した。現在
    # next_page_url は呼び出し元では使われておらず、1ページ目のみを
    # 取得・保存する。パース結果としては引き続き保持しておく
    # (画面上で「次ページへのリンク」を出す等、将来UIで使う可能性は
    # 残るため)。
    other_articles_total_count: int | None = None  # 「全30件中 1-10件表示」の30
    next_page_url: str | None = None  # 次ページが無ければNone (2026-09-04時点で未使用)


def _parse_dt_dd_stats(soup: BeautifulSoup) -> dict:
    """
    <dt>ラベル<font>：</font></dt><dd>値</dd> の並びを解析する。

    実データで確認したラベル一覧:
        ニックネーム / 認証 / 評価 / 性別 / 登録日時 / 居住区 / 職業
    ページによって存在しない項目もありうるため、辞書のget等で
    欠損を許容する。
    """
    result: dict = {}
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).rstrip("：:")
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        result[label] = dd

    return result


def _parse_rating_breakdown(dd) -> tuple[int | None, int | None, int | None]:
    """
    評価dd内の数値を出現順に (良い, 普通, 悪い) として取り出す。

    テキストラベルがなく画像アイコンと数値が交互に並ぶ構造のため、
    数値の出現順のみを頼りに割り当てる (実データ検証 2026-08-22)。
    """
    text = dd.get_text(" ", strip=True)
    numbers = re.findall(r"\d+", text)
    values = [int(n) for n in numbers[:3]]
    while len(values) < 3:
        values.append(None)
    return values[0], values[1], values[2]


def _parse_verification(dd) -> tuple[bool, bool]:
    text = dd.get_text(" ", strip=True)
    return "身分証" in text, "電話番号" in text


def _parse_article_item(link) -> ProfileArticleSummary:
    """
    a.portal_list_link 1件をパースする。

    実データ確認済みの固定順テキストノード:
        [0] 区分 (売ります/あげます等)
        [1] タイトル
        [2] 価格 (例: "800円")
        [3] 地域
        [4] 説明抜粋
        [5] 更新日 (MM/DD形式)
    """
    texts = [t.strip() for t in link.find_all(string=True) if isinstance(t, NavigableString) and t.strip()]

    href = to_absolute_url(link.get("href"))
    article_id = extract_article_id(href) if isinstance(href, str) else None

    listing_type = texts[0] if len(texts) > 0 else None
    title = texts[1] if len(texts) > 1 else None
    price = normalize_price(texts[2]) if len(texts) > 2 else None
    location = texts[3] if len(texts) > 3 else None
    description_short = texts[4] if len(texts) > 4 else None
    updated_date_raw = texts[5] if len(texts) > 5 else None

    return ProfileArticleSummary(
        article_id=article_id,
        url=href,
        listing_type=listing_type,
        title=title,
        price=price,
        location=location,
        description_short=description_short,
        updated_date_raw=updated_date_raw,
    )


def parse_profile_page(html: str) -> ProfileInfo:
    """プロフィールページHTML全体をパースする。"""
    soup = BeautifulSoup(html, "lxml")

    stats = _parse_dt_dd_stats(soup)

    seller_name = stats["ニックネーム"].get_text(strip=True) if "ニックネーム" in stats else None

    identity_verified, phone_verified = (
        _parse_verification(stats["認証"]) if "認証" in stats else (False, False)
    )

    rating_good = rating_normal = rating_bad = None
    if "評価" in stats:
        rating_good, rating_normal, rating_bad = _parse_rating_breakdown(stats["評価"])

    gender = stats["性別"].get_text(strip=True) if "性別" in stats else None
    registration_date_raw = (
        stats["登録日時"].get_text(strip=True) if "登録日時" in stats else None
    )
    residential_area = stats["居住区"].get_text(strip=True) if "居住区" in stats else None
    occupation = stats["職業"].get_text(strip=True) if "職業" in stats else None

    # 自己紹介文: 実データ検証で判明した専用クラス構造を使う。
    #   <div class="profil_ball_text">
    #     <p class="color-placeholder">自己紹介文が入力されていません。</p>  (未設定時)
    #   </div>
    # "color-placeholder" クラスの有無で未設定/設定済みを判別する
    # (プレースホルダー文言そのものでの判定は、ユーザーが偶然同じ文言を
    # 入力した場合に誤判定しうるため、専用クラスを優先する)。
    description = None
    intro_block = soup.select_one(".profil_ball_text")
    if intro_block is not None:
        placeholder = intro_block.select_one(".color-placeholder")
        if placeholder is None:
            text = intro_block.get_text(strip=True)
            description = text if text else None

    # 投稿一覧
    other_articles = [
        _parse_article_item(link) for link in soup.select("a.portal_list_link")
    ]
    other_article_urls = [a.url for a in other_articles if a.url]

    # 投稿一覧の総件数: 「全30件中 1-10件表示」というテキストから抽出する
    # (2026-09-04 追加。実データ (profile_closed_real.html) で存在を確認)。
    other_articles_total_count = None
    total_count_text = soup.find(string=re.compile(r"全\d+件中"))
    if total_count_text:
        m = re.search(r"全(\d+)件中", total_count_text)
        if m:
            other_articles_total_count = int(m.group(1))

    # 次ページURL: <a rel=next id="btn_next" href="...?page=N">次へ</a>
    # (2026-09-04 追加)。「受付中」「受付終了」の区分をまたいで最終更新日順
    # に並んでいるため、1ページ分だけでは投稿一覧が中途半端な件数で
    # 切れてしまう。全ページを辿って合算する処理は呼び出し元の責務とする
    # (このパーサーはHTML1枚のパースに専念する)。
    next_page_url = None
    # id="btn_next" が確実な目印 (単なる rel=next はページ番号リンク
    # 2, 3, ... 全てに付与されており、これだけでは「次へ」を一意に
    # 特定できないため使わない)
    next_link = soup.select_one("a#btn_next")
    if next_link is not None:
        href = next_link.get("href")
        if href:
            next_page_url = to_absolute_url(href)

    # rating / rating_count は一覧ページ・詳細ページのような合算値表示が
    # このページには見当たらなかったため、評価内訳の合計から算出する
    rating_count = None
    if rating_good is not None and rating_normal is not None and rating_bad is not None:
        rating_count = rating_good + rating_normal + rating_bad

    return ProfileInfo(
        seller_name=seller_name,
        post_count=other_articles_total_count,  # 「全◯件中」の件数を採用 (2026-09-04)
        rating=None,  # 5段階評価等の平均値表示は本サンプルに存在しない
        rating_count=rating_count,
        rating_good=rating_good,
        rating_normal=rating_normal,
        rating_bad=rating_bad,
        registration_date_raw=registration_date_raw,
        residential_area=residential_area,
        occupation=occupation,
        gender=gender,
        identity_verified=identity_verified,
        phone_verified=phone_verified,
        description=description,
        evaluations=[],  # 実データ未入手のため空リスト (上記docstring参照)
        other_articles=other_articles,
        other_article_urls=other_article_urls,
        other_articles_total_count=other_articles_total_count,
        next_page_url=next_page_url,
    )
