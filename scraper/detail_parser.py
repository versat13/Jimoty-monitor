"""
個別(記事詳細)ページパーサー。

フィルタリング処理フロー (仕様書 v1.0 6章) の⑨⑩を担当する。
    ⑨ 個別ページ取得 (新規投稿のみ) ← 呼び出し元の責務
    ⑩ 出品者情報・全文説明・正式カテゴリ取得 ← このモジュール

=== 重要: 設計方針の転換について ===

当初 (v1.1追補まで) は "p-article-detail-table" 等の意味のあるCSSクラス名を
前提にセレクタを組んでいた。しかし実物HTML (2026-08-22、ユーザー提供の
実サンプル「広告ブロックしてる、商品個別サンプル.html」) を検証した結果、
個別ページは styled-components 由来のハッシュ化クラス名
(例: "sc-a7f3bb80-0 djDmIn") のみで構成されており、
意味のあるクラス名は一切存在しないことが判明した。

このため個別ページのみ、一覧ページとは異なる解析方針を採る:
    - クラス名には依存しない
    - 「商品価格」「ジャンル」「受け渡し場所」等の見出し語(テキスト)を
      起点に、同じ<tr>内の隣接<td>から値を取る
    - 出品者ブロックは「投稿者」という単独テキストを持つ要素を見出しとして
      特定し、そのブロック全体をスコープにして内部を解析する
    - 本文説明はページ内の<p>要素のうち、最も長いテキストを持つものを
      本文とみなす (評価コメントやパンくず等の短文<p>と区別するため)
    - カテゴリ・地域の親階層はBreadcrumbList (JSON-LD) から取得する
      (これはハッシュ化されておらず、当初の想定通り安定して機能する)

根拠:
- 仕様書 v1.0 4-5
- HTML解析仕様確定版 17〜30 (投稿者欄、BreadcrumbList、構造化テーブル)
- 追補版 v1.1 追補2 (時刻付き日時)
- 実データ検証 2026-08-22 (本モジュールのセレクタ全面書き換えの根拠)
"""

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from scraper.normalize import normalize_history_datetime, normalize_price
from scraper.selectors.url_patterns import (
    extract_area,
    extract_article_id,
    extract_category_id,
    extract_seller_id,
    extract_station_id,
    to_absolute_url,
)


@dataclass
class SellerInfo:
    """個別ページの投稿者欄から取得できる出品者情報 (仕様書 v1.0 4-5)。"""

    seller_id: str | None
    seller_name: str | None
    seller_profile_url: str | None
    gender: str | None = None
    post_count: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    identity_verified: bool = False
    phone_verified: bool = False
    description: str | None = None


@dataclass
class DetailArticle:
    """個別ページから取得できる投稿データ (仕様書 v1.0 4-5)。"""

    article_id: str | None
    url: str | None
    full_title: str | None
    description_full: str | None
    price: int | None = None
    category_id: str | None = None
    category_name: str | None = None
    category_mid_id: str | None = None
    category_mid_name: str | None = None
    category_parent_id: str | None = None
    category_parent_name: str | None = None
    prefecture: str | None = None
    city: str | None = None
    ward: str | None = None
    town: str | None = None
    area_id: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    railway_line: str | None = None
    thumbnail_url: str | None = None
    seller: SellerInfo | None = None
    history_datetimes: dict = field(default_factory=dict)  # {"更新": datetime, "作成": datetime}
    is_closed: bool = False  # 「お問い合わせの受付は終了いたしました。」が表示されている状態


_PREFECTURE_SUFFIX_RE = re.compile(r"^(.+?[都道府県])の")


def _parse_breadcrumb_json_ld(soup: BeautifulSoup) -> dict:
    """
    BreadcrumbList (JSON-LD) からカテゴリ階層 (大カテゴリ・ジャンル・
    サブジャンル)・県名を抽出する。

    このJSON-LDはハッシュ化クラス名の影響を受けないため、
    個別ページの中で最も安定した情報源として位置づける。

    2026-09-07 バグ修正 (階層ズレ、第1版): 当初は position 番号を
    固定で決め打ちしていた (position==3を親カテゴリ、position==5を
    県名、という具合)。しかし実データ検証の結果、カテゴリによって
    BreadcrumbListの階層数そのものが異なることが判明し、
    「末尾からの相対位置」で判定する方式に変更した。

    2026-09-08 バグ修正 (階層ズレ、第2版・カテゴリの意味の取り違え):
    第1版の「末尾から4番目を親カテゴリとする」という方式は、実は
    正しくなかった。ジモティーのカテゴリ階層は以下の3パターンが
    あり、大カテゴリ・ジャンル・サブジャンルのうち出品者がどこまで
    指定したかによって、パンくずの段数自体が変わる
    (ユーザーへのヒアリングで判明):

        大カテゴリのみ (ジャンル・サブジャンル未指定):
            ジモティー/売ります・あげます/服・ファッション/
            福岡県の服・ファッション/北九州市の服・ファッション/
            (投稿タイトル)
        大カテゴリ+ジャンル (サブジャンル未指定):
            ジモティー/売ります・あげます/服・ファッション/コート/
            福岡県のコート/北九州市のコート/(投稿タイトル)
        大カテゴリ+ジャンル+サブジャンル:
            ジモティー/売ります・あげます/服・ファッション/コート/
            レディース/福岡県のレディース/北九州市のレディース/
            (投稿タイトル)

    「末尾から4番目」は、大カテゴリのみのケースでは大カテゴリそのもの
    だが、ジャンル+サブジャンルまで指定されたケースでは実際には
    「ジャンル」の値になってしまい、本来の大カテゴリ
    (「服・ファッション」) は一切取得されずに失われていた。

    正しい判定方法: 「ジモティー」「売ります・あげます」の固定の
    先頭2エントリと、「{都道府県}の{カテゴリ名}」「{市区町村}の
    {カテゴリ名}」の末尾2エントリを除いた「残りのカテゴリ部分」の
    個数によって、どこまで指定されているかが一意に決まる。
        残り1個 → 大カテゴリのみ
        残り2個 → 大カテゴリ + ジャンル
        残り3個 → 大カテゴリ + ジャンル + サブジャンル
    これを利用し、先頭から数える方式に変更した。

    TODO (将来の拡張、2026-09-08時点では未対応):
    「売ります・あげます」を固定の先頭2番目として扱っているのは、
    現時点でこのツールが「売ります・あげます」カテゴリ配下のみを
    監視対象としているため。ジモティーには同じ階層に「助け合い」
    「中古車」「不動産」等の別ジャンルも存在し、将来これらを監視
    対象に含める場合は、この「先頭2エントリ固定」という前提の
    見直しが必要になる (ユーザーとの会話で明示された今後の課題)。
    """
    result: dict = {
        "category_parent_name": None,
        "category_parent_id": None,
        "category_mid_name": None,
        "category_mid_id": None,
        "category_name": None,
        "category_id": None,
        "prefecture": None,
    }

    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") != "BreadcrumbList":
            continue

        items = data.get("itemListElement", [])

        # 投稿タイトル自体のエントリ (@id/itemを持たず、末端の position のみ)
        # は地域・カテゴリ階層に含まれないため除外してから数える。
        entries = []
        for entry in items:
            thing = entry.get("item")
            if isinstance(thing, dict):
                name = thing.get("name", "")
                item_id = thing.get("@id", "")
            elif isinstance(thing, str):
                # 稀に旧形式 (itemが文字列URL、nameが直下) の場合に備える
                name = entry.get("name", "")
                item_id = thing
            else:
                # thingが存在しない (投稿タイトル自体のエントリ) は
                # 地域・カテゴリ階層ではないため除外する。
                continue
            entries.append((name, item_id))

        # 末尾2つ (都道府県・市区町村相当) を判定する (詳細はdocstring参照)。
        def _from_end(offset: int) -> tuple[str, str] | None:
            idx = len(entries) - offset
            return entries[idx] if 0 <= idx < len(entries) else None

        city_entry = _from_end(1)
        prefecture_entry = _from_end(2)

        if prefecture_entry is not None:
            m = _PREFECTURE_SUFFIX_RE.match(prefecture_entry[0])
            if m:
                result["prefecture"] = m.group(1)

        # 先頭2エントリ (ジモティー/売ります・あげます) と、末尾2エントリ
        # (都道府県・市区町村) を除いた「カテゴリ部分」を取り出す。
        # 先頭2つに満たない・末尾2つと重複するような極端に短い
        # BreadcrumbListは想定外のデータとみなし、カテゴリ部分は
        # 空リストとして扱う (誤った値を拾うよりは、None のままの方が
        # 安全なため)。
        _FIXED_HEAD_LENGTH = 2  # 「ジモティー」「売ります・あげます」
        category_part_end = len(entries) - 2  # 末尾2つ (都道府県・市区町村) の手前まで
        if category_part_end > _FIXED_HEAD_LENGTH:
            category_entries = entries[_FIXED_HEAD_LENGTH:category_part_end]
        else:
            category_entries = []

        if len(category_entries) == 1:
            # 大カテゴリのみ指定
            name, item_id = category_entries[0]
            result["category_parent_name"] = name
            result["category_parent_id"] = _extract_parent_category_id(item_id)
            # category_id/category_nameには、ジャンル・サブジャンル
            # 未指定でも「今分かっている最も詳細なカテゴリ」として
            # 大カテゴリの値を入れておく (ジャンルNGルール等が
            # category_idだけを見ても大カテゴリ相当の判定ができる
            # ようにするため。filters/category_filter.pyのmid判定
            # ロジックと組み合わせて使う想定)。
            result["category_name"] = name
            cid = extract_category_id(item_id)
            result["category_id"] = cid if cid else result["category_parent_id"]
        elif len(category_entries) == 2:
            # 大カテゴリ + ジャンル
            parent_name, parent_item_id = category_entries[0]
            mid_name, mid_item_id = category_entries[1]
            result["category_parent_name"] = parent_name
            result["category_parent_id"] = _extract_parent_category_id(parent_item_id)
            result["category_name"] = mid_name
            cid = extract_category_id(mid_item_id)
            result["category_id"] = cid
        elif len(category_entries) >= 3:
            # 大カテゴリ + ジャンル + サブジャンル
            # (3個を超えるケースは現状未確認だが、末尾側=より詳細な
            # 側を優先してサブジャンル・ジャンルに割り当てる)
            parent_name, parent_item_id = category_entries[0]
            mid_name, mid_item_id = category_entries[1]
            leaf_name, leaf_item_id = category_entries[-1]
            result["category_parent_name"] = parent_name
            result["category_parent_id"] = _extract_parent_category_id(parent_item_id)
            result["category_mid_name"] = mid_name
            mid_cid = extract_category_id(mid_item_id)
            result["category_mid_id"] = mid_cid
            result["category_name"] = leaf_name
            leaf_cid = extract_category_id(leaf_item_id)
            result["category_id"] = leaf_cid

        # city_entry (末尾から1番目) は現状 detail_parser の他の箇所
        # (受け渡し場所テーブル) から取得済みのため、ここでは
        # 位置合わせの計算にのみ使い、値そのものは補完用途にも
        # 使わない (元の設計方針を踏襲)。
        del city_entry

        break  # BreadcrumbListは通常1つのみ

    return result


def _extract_parent_category_id(item_id: str) -> str | None:
    """
    大カテゴリのURL (例: https://jmty.jp/all/sale-clo) から
    "sale-clo" のようなスラッグを抽出する。

    ジャンル・サブジャンル (g-数字) とは異なるURL形式のため、
    extract_category_id() とは別の抽出ロジックを使う。
    """
    m = re.search(r"/([a-z0-9\-]+)$", item_id)
    return m.group(1) if m else None


def _parse_detail_table(soup: BeautifulSoup) -> dict:
    """
    構造化テーブルを、見出し語(th/tdの1列目テキスト)をキーにして解析する。

    実データ検証で判明した構造:
        <tr><td>商品価格</td><td>240円</td></tr>
        <tr><td>ジャンル</td><td><a href=".../g-1205">OA用品</a></td></tr>
        <tr><td>受け渡し場所</td><td>
            <a href=".../a-731-kitakyushu">北九州市</a>
            <span>- 小倉北区</span><span>- 東城野町</span>
            <span>JR日豊本線(...) -</span><a href=".../s-1190607">城野駅</a>
        </td></tr>

    「最寄駅」という独立行は存在せず、駅情報は「受け渡し場所」の値に
    同居している点に注意 (旧セレクタ設計からの主要な変更点)。
    """
    result: dict = {
        "price": None,
        "category_name": None,
        "category_id": None,
        "category_mid_name": None,
        "category_mid_id": None,
        "prefecture": None,  # 受け渡し場所テーブルには県名が含まれないため常にNone
        "city": None,
        "ward": None,
        "town": None,
        "area_id": None,
        "station_id": None,
        "station_name": None,
        "railway_line": None,
    }

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 2:
            continue
        label = tds[0].get_text(strip=True)
        value_td = tds[1]

        if label == "商品価格":
            result["price"] = normalize_price(value_td.get_text(strip=True))

        elif label == "ジャンル":
            # 実データ検証で判明: 2階層になる場合がある
            # (例: <a>調理器具</a> <span>&gt;</span> <a>鍋、グリル</a>)
            # 末尾のリンクが最も詳細なカテゴリであるため、それを採用する。
            genre_links = value_td.find_all("a")
            if genre_links:
                deepest = genre_links[-1]
                result["category_name"] = deepest.get_text(strip=True)
                href = deepest.get("href", "")
                if isinstance(href, str):
                    result["category_id"] = extract_category_id(href)
                if len(genre_links) > 1:
                    mid = genre_links[0]
                    result["category_mid_name"] = mid.get_text(strip=True)
                    mid_href = mid.get("href", "")
                    if isinstance(mid_href, str):
                        result["category_mid_id"] = extract_category_id(mid_href)

        elif label == "受け渡し場所":
            links = value_td.find_all("a")
            city_link = next(
                (a for a in links if extract_area(a.get("href", "")) is not None), None
            )
            station_link = next(
                (a for a in links if extract_station_id(a.get("href", "")) is not None), None
            )

            if city_link is not None:
                area = extract_area(city_link.get("href", ""))
                result["area_id"] = area[0] if area else None
                result["city"] = city_link.get_text(strip=True)

            if station_link is not None:
                result["station_id"] = extract_station_id(station_link.get("href", ""))
                result["station_name"] = station_link.get_text(strip=True)

            # span要素: 区・町名、路線名 (「- 」区切りのテキスト)
            spans = [s.get_text(strip=True).lstrip("- ").rstrip(" -") for s in value_td.find_all("span")]
            # 区・町名系(市区町村を含まない語)と路線名を区別する簡易ヒューリスティック:
            # 「区」「町」「村」で終わるものを住所、「線」「鉄道」を含むものを路線名とする
            for s in spans:
                if not s:
                    continue
                if re.search(r"[区町村]$", s):
                    if result["ward"] is None:
                        result["ward"] = s
                    else:
                        result["town"] = s
                elif "線" in s or "鉄道" in s:
                    result["railway_line"] = s

    return result


def _find_seller_block(soup: BeautifulSoup):
    """
    「投稿者」という単独テキストを見出しとする出品者ブロックを特定する。

    実データ検証: 「投稿者」というテキストのみを直接の子として持つ要素を
    基準に、
        el          : 「投稿者」の文字だけ
        el.parent   : 出品者名・性別・投稿数・評価 まで (身分証等は含まない)
        el.parent.parent : 身分証/電話番号/紹介文まで含む一まとまりのブロック
    という3段階のネストになっている。身分証・紹介文まで取得するため
    el.parent.parent をスコープとして採用する
    (それ以上遡ると商品価格テーブルまで含んでしまい、
    紹介文<p>の抽出が本文と混同するリスクが増えるため避ける)。
    """
    for el in soup.find_all(["div", "section"]):
        direct_texts = [c for c in el.children if isinstance(c, NavigableString)]
        if any(t.strip() == "投稿者" for t in direct_texts):
            block = el
            for _ in range(2):
                if block.parent is not None:
                    block = block.parent
            return block
    return None


def _parse_seller_info(soup: BeautifulSoup):
    """出品者ブロックから出品者情報を抽出する。"""
    block = _find_seller_block(soup)
    if block is None:
        return None

    # ブロック内で最初に出現する /profiles/{id} リンク (クエリなし) が出品者本人。
    # 評価コメントの評価者リンクや「評価をもっと見る」リンクより先に現れる前提
    # (実データ検証で確認済み)。
    profile_links = block.select("a[href*='/profiles/']")
    seller_link = next(
        (a for a in profile_links if "?" not in a.get("href", "")), None
    )
    if seller_link is None:
        return None

    seller_profile_url = to_absolute_url(seller_link.get("href"))
    seller_name = seller_link.get_text(strip=True)
    seller_id = extract_seller_id(seller_profile_url) if isinstance(seller_profile_url, str) else None

    block_text = block.get_text(" ", strip=True)

    gender = None
    for g in ("男性", "女性"):
        if g in block_text:
            gender = g
            break

    post_count = None
    m = re.search(r"投稿[：:]\s*(\d+)", block_text)
    if m:
        post_count = int(m.group(1))

    # 2026-09-07 バグ修正: 評価が1件も付いていない出品者は
    # 「5.0 (548)」のような件数付き表示ではなく「0.0」単体で表示され、
    # 括弧内の件数表記自体が存在しないことが実データ検証で判明した
    # (通常表示の正規表現 (\d\.\d)\s*\((\d+)\) はこの形に一致しない
    # ため、評価0件の出品者は rating/rating_count が常に None になり、
    # 「未評価」なのか「取得に失敗した」のか区別できなくなっていた)。
    # まず通常の件数付きパターンを試し、一致しなければ「0.0」単体
    # (評価0件を意味する) のパターンを試す。件数付きパターンでの
    # 誤検出を避けるため、フォールバックは "0.0" という値に限定する
    # (他の小数点数値との偶然の一致を避けるため)。
    rating = None
    rating_count = None
    m = re.search(r"(\d\.\d)\s*\((\d+)\)", block_text)
    if m:
        rating = float(m.group(1))
        rating_count = int(m.group(2))
    elif re.search(r"(?<!\d)0\.0(?!\d)", block_text):
        rating = 0.0
        rating_count = 0

    identity_verified = "身分証" in block_text
    phone_verified = "電話番号" in block_text

    # 紹介文: block内で「直接の子テキスト」としてある程度の長さの文章を
    # 持つ要素のうち、出品者統計(性別/投稿数)の直後に現れる最初の1件を候補とする。
    # 実データでは以下の順で並ぶ:
    #   投稿者 -> 性別 -> 投稿：N -> [紹介文 or "自己紹介文が設定されていません"] -> 評価コメント...
    # 「自己紹介文が設定されていません」はプレースホルダーであり、
    # これに一致した場合は次の要素(=評価コメント)を拾わないよう、
    # その時点でNone確定として走査を打ち切る。
    #
    # 2026-08-28 バグ修正: 当初は direct_texts[0] (要素直下の最初の
    # テキストノードのみ) を紹介文として採用していたが、紹介文が
    # <br> 等で複数行に分かれ複数のテキストノードに分割されている場合、
    # 最初の1文だけを拾って残りを切り捨ててしまう不具合があった
    # (「続きを読む」を押しても全文が表示されない、というユーザー報告)。
    # 候補要素が見つかった時点で、その要素の get_text(全テキスト結合、
    # 改行はseparatorで保持) を紹介文として採用するよう修正した。
    _label_words = {"身分証", "電話番号", "認証とは", "投稿者", "男性", "女性"}
    _empty_description_marker = "自己紹介文が設定されていません"
    description = None
    for el in block.find_all(["p", "div"]):
        direct_texts = [c.strip() for c in el.children if isinstance(c, NavigableString) and c.strip()]
        if not direct_texts:
            continue
        first_text = direct_texts[0]
        if first_text == _empty_description_marker:
            description = None
            break
        if len(first_text) > 5 and first_text not in _label_words and not re.match(r"^投稿[：:]\s*\d+$", first_text):
            full_text = el.get_text(separator="\n", strip=True)
            description = full_text if full_text else first_text
            break

    return SellerInfo(
        seller_id=seller_id,
        seller_name=seller_name,
        seller_profile_url=seller_profile_url if isinstance(seller_profile_url, str) else None,
        gender=gender,
        post_count=post_count,
        rating=rating,
        rating_count=rating_count,
        identity_verified=identity_verified,
        phone_verified=phone_verified,
        description=description,
    )


def _find_history_datetimes(soup: BeautifulSoup) -> dict:
    r"""
    個別ページ本文の「更新」「作成」日時表示を (種別 -> datetime) の
    辞書として抽出する。

    2026-09-07 バグ修正: 当初は
        soup.find_all(string=re.compile(r"(更新|作成)\d{4}年"))
    のように、正規表現をテキストノード単体に直接一致させていた。
    しかし実データ (ユーザー提供の巡回取得HTML) には

        <div>作成<!-- -->2026年9月7日 09:17</div>

    のように、React由来のハイドレーション用コメント (中身は空)
    が「作成」と日付本体の間に挟まるケースが存在することが判明した。
    BeautifulSoupの Comment は NavigableString のサブクラスだが、
    find_all(string=...) は個々のテキストノードに対して独立に
    正規表現を評価するため、「作成」だけのノードと「2026年...」だけの
    ノードに分断されてしまい、どちらの断片も単独ではパターンに
    一致しなくなる。この結果 history_datetimes が常に空になり、
    「投稿日・最終更新日が表示されない」不具合の直接の原因になっていた
    (ユーザー報告・実データ調査により特定)。

    根本原因は「テキストノード単体」を判定単位にしていたことにある。
    そこで、まず「更新」または「作成」という文字列をどこかに含む
    要素をテキストノード単位で見つけたうえで、その"直接の親要素"の
    get_text() (子孫のコメントノードは自動的に無視され、複数の
    テキストノードは連結される) に対して正規表現を適用する方式に
    変更する。get_text()ベースであれば、コメントで分断されている
    場合 ("作成<!-- -->2026年...") も、分断されていない場合
    ("作成2026年..."、既存テストフィクスチャの形) も同様に扱える。

    同じ親要素を持つノードを重複して処理しないよう、訪問済みの
    親要素はスキップする。
    """
    history_datetimes: dict = {}
    seen_parents = set()

    for node in soup.find_all(string=re.compile(r"更新|作成")):
        parent = node.parent
        if parent is None or id(parent) in seen_parents:
            continue
        seen_parents.add(id(parent))

        parent_text = parent.get_text(strip=True)
        for kind, dt in normalize_history_datetime(parent_text):
            # 同じ種別が複数箇所で見つかった場合は最初に見つかった方を
            # 優先する (通常は1箇所にしか存在しないはずだが、
            # 万一の重複時に後勝ちで上書きし続けるのを避けるため)。
            history_datetimes.setdefault(kind, dt)

    return history_datetimes


def _find_description_full(soup: BeautifulSoup) -> str | None:
    """
    本文説明を特定する。

    実データ検証 (2026-08-22、2件のサンプルで確認):
        本文は h1(タイトル) と 構造化テーブル(商品価格...) の間、
        「いいね！」という単独テキストの直後に位置する1つのテキストノードとして
        存在する。

    当初「ページ内で最も長い<p>」というヒューリスティックを使っていたが、
    「関連投稿一覧」セクションの見出し文
    (例:「マイヤー 電子レンジ用圧力鍋 福岡 中古あげます・譲りますを
    見ている人は、こちらの記事も見ています。」) の方が本文より長い場合があり、
    誤って関連セクションの文言を本文として拾ってしまう不具合があった。
    「いいね！」直後という位置的制約に変更することで解消する。

    本文が実質空 (タイトルの繰り返し程度) の投稿も実データに存在するため、
    その場合は短い文字列がそのまま返る (Noneにはしない。
    「本文が薄い投稿だった」という情報自体に意味があるため)。
    """
    like_node = soup.find(string=lambda t: t and t.strip() == "いいね！")
    if like_node is None:
        return None

    all_strings = list(soup.body.strings) if soup.body is not None else list(soup.strings)
    try:
        idx = all_strings.index(like_node)
    except ValueError:
        return None

    if idx + 1 >= len(all_strings):
        return None

    text = all_strings[idx + 1].strip()
    return text if text else None


def parse_detail_page(html: str) -> DetailArticle:
    """個別ページHTML全体をパースする。"""
    soup = BeautifulSoup(html, "lxml")

    canonical_el = soup.select_one("link[rel='canonical']")
    url = to_absolute_url(canonical_el.get("href")) if canonical_el is not None else None
    article_id = extract_article_id(url) if isinstance(url, str) else None

    h1 = soup.find("h1")
    if h1 is not None:
        # 実データでは h1 に「（投稿ID : xxxx）」という接尾辞が付くため除去する
        full_title = re.sub(r"（投稿ID\s*[:：].*?）\s*$", "", h1.get_text(strip=True)).strip()
    else:
        og_title = soup.select_one("meta[property='og:title']")
        full_title = og_title.get("content") if og_title is not None else None

    description_full = _find_description_full(soup)

    table_data = _parse_detail_table(soup)
    breadcrumb_data = _parse_breadcrumb_json_ld(soup)

    # 2026-09-08: カテゴリ階層 (大カテゴリ・ジャンル・サブジャンル) は
    # breadcrumb_data (JSON-LD BreadcrumbList) を優先する。
    #
    # 理由: table_data (テーブルの「ジャンル」欄) は、そのテーブルの
    # 表示ロジック上「ジャンル欄にリンクが2つあれば中間カテゴリと
    # 詳細カテゴリの2階層」としか判定できず、大カテゴリ自体は
    # 一切取得できない。一方breadcrumb_dataは、パンくずの階層数
    # (大カテゴリのみ/大カテゴリ+ジャンル/大カテゴリ+ジャンル+
    # サブジャンルの3パターン) を正しく判別できるよう2026-09-08に
    # 修正済みのため、より正確な情報源として優先する
    # (ユーザーへのヒアリングで判明した仕様に基づく)。
    # table_dataは、何らかの理由でBreadcrumbList自体が取得できな
    # かった場合のフォールバックとしてのみ使う。
    category_name = breadcrumb_data["category_name"] or table_data["category_name"]
    category_id = breadcrumb_data["category_id"] or table_data["category_id"]
    category_mid_name = breadcrumb_data["category_mid_name"] or table_data["category_mid_name"]
    category_mid_id = breadcrumb_data["category_mid_id"] or table_data["category_mid_id"]
    prefecture = table_data["prefecture"] or breadcrumb_data["prefecture"]

    og_image = soup.select_one("meta[property='og:image']")
    thumbnail_url = og_image.get("content") if og_image is not None else None

    seller = _parse_seller_info(soup)

    # 追補仕様v1.1で発見した「受付終了」ブロックとは別に、個別ページ自体にも
    # 終了状態を示す表現が存在する: 「お問い合わせの受付は終了いたしました。」
    # (実データ検証 2026-08-22)。一覧ページの「受付終了」ラベルとは
    # 文言が異なる点に注意 (一覧: "受付終了" / 個別ページ: "お問い合わせの受付は終了いたしました。")。
    is_closed = "お問い合わせの受付は" in soup.get_text() and "終了いたしました" in soup.get_text()

    history_datetimes = _find_history_datetimes(soup)

    return DetailArticle(
        article_id=article_id,
        url=url if isinstance(url, str) else None,
        full_title=full_title,
        description_full=description_full,
        price=table_data["price"],
        category_id=category_id,
        category_name=category_name,
        category_mid_id=category_mid_id,
        category_mid_name=category_mid_name,
        category_parent_id=breadcrumb_data["category_parent_id"],
        category_parent_name=breadcrumb_data["category_parent_name"],
        prefecture=prefecture,
        city=table_data["city"],
        ward=table_data["ward"],
        town=table_data["town"],
        area_id=table_data["area_id"],
        station_id=table_data["station_id"],
        station_name=table_data["station_name"],
        railway_line=table_data["railway_line"],
        thumbnail_url=thumbnail_url if isinstance(thumbnail_url, str) else None,
        seller=seller,
        history_datetimes=history_datetimes,
        is_closed=is_closed,
    )
