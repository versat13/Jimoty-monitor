"""
一覧ページパーサー。

フィルタリング処理フロー (仕様書 v1.0 6章) のうち、①〜⑦を担当する。
    ① 一覧ページ取得 (この関数の呼び出し元の責務)
    ② p-articles-list-item を固定件数分すべて列挙   ← parse_list_page()
    ③ 広告除外 (alliance- または p-item-alliance-tag) ← ad_rules.is_ad()
    ④ article_id抽出
    ⑤ 地域判定
    ⑥ カテゴリ判定 (一覧段階のURL構造から。詳細ページ不要)
    ⑦ NGワード判定 (タイトル＋一覧説明文)          ← filters/keyword_filter.py (別モジュール)
    ⑧以降 (DB照合・詳細ページ取得) は repository / scheduler の責務。

重要な設計制約 (仕様書 v1.0 5-4):
    NGユーザー登録があっても投稿データそのものの取得・保存は必ず行う。
    このパーサーの時点ではNGユーザー判定を行わない (表示層の責務)。
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from scraper.normalize import normalize_favorite_count, normalize_history_date, normalize_price
from scraper.selectors import list_selectors as sel
from scraper.selectors.ad_rules import is_ad
from scraper.selectors.url_patterns import (
    extract_area,
    extract_article_id,
    extract_category_id,
    extract_station_id,
    is_category_slug_url,
    is_pr_slot_url,
    to_absolute_url,
)


@dataclass
class ListArticle:
    """一覧ページから取得できる範囲の投稿データ (仕様書 v1.0 4-4 に対応)。"""

    article_id: str
    url: str
    list_title: str
    price: int | None
    prefecture: str | None
    area_id: str | None
    area_name: str | None
    station_id: str | None
    station_name: str | None
    category_id: str | None
    category_name: str | None
    tags: list[str] = field(default_factory=list)
    description_short: str | None = None
    updated_date_raw: str | None = None
    created_date_raw: str | None = None
    favorite_count: int | None = None
    thumbnail_url: str | None = None
    is_pr_slot: bool = False  # from=pr パターン。未確定仕様のため要検討フラグとして保持



def _classify_supplementary_links(item: Tag) -> dict:
    """
    .p-item-supplementary-info 内のリンクを、URL構造 (a-/s-/g-/sale-XXX) で
    「市区町村」「駅」「カテゴリ」「タグ」に仕分ける。

    根拠: HTML解析仕様確定版 7
        「.p-item-supplementary-info a を全部取ってはいけない」
        市区町村・駅・カテゴリが同一ブロック内に並列で存在するため、
        リンク先URLのパターンで用途を判別する必要がある。

    実データ検証で追加判明 (2026-08-22):
        カテゴリは常に g-{数字} を持つとは限らない。
        「その他」カテゴリ等は https://jmty.jp/all/sale-oth のように
        g-数字を伴わないURLで表現される (is_category_slug_url 参照)。
        これを見逃すと、カテゴリ名がタグ配列に誤混入する。
    """
    result = {
        "area_id": None,
        "area_name": None,
        "station_id": None,
        "station_name": None,
        "category_id": None,
        "category_name": None,
        "tags": [],
    }

    for block in item.select(sel.SUPPLEMENTARY_INFO_BLOCKS):
        for a in block.select("a"):
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            text = a.get_text(strip=True)

            area = extract_area(href)
            station_id = extract_station_id(href)
            category_id = extract_category_id(href)

            if area is not None:
                result["area_id"], result["area_name"] = area[0], text
            elif station_id is not None:
                result["station_id"], result["station_name"] = station_id, text
            elif category_id is not None:
                result["category_id"], result["category_name"] = category_id, text
            elif is_category_slug_url(href):
                # g-数字を持たないカテゴリ (例: /all/sale-oth → 「その他」)
                # category_id は g-数字体系と別物のため、スラッグ自体を入れておく
                slug_match = re.search(r"/all/sale-([a-z]+)/?$", href.split("?")[0])
                result["category_id"] = slug_match.group(1) if slug_match else None
                result["category_name"] = text
            else:
                # 上記いずれのパターンにも一致しない場合はキーワードタグとして扱う
                # (HTML解析仕様確定版 11: post_tags)
                result["tags"].append(text)

    return result


def parse_list_item(item: Tag, current_year: int) -> ListArticle | None:
    """
    p-articles-list-item 単体をパースする。

    広告と判定された場合は None を返す (呼び出し元で除外)。
    """
    # ③ 広告除外は最優先・価格解析より前に実施
    if is_ad(item):
        return None

    # PR枠 (?from=pr) は .p-item-title 内に <a> が2つ存在し、
    # 1つ目 (.p-item-pr-icon) は /my/payments/new への決済導線リンクで
    # article_idを含まない。select_one で最初の1件だけを見ると
    # 本来のタイトルリンクを取り逃すため、.p-item-title 内の全リンクから
    # article- を含むものを優先して選ぶ (実データ検証 2026-08-22 で確認)。
    title_block = item.select_one(".p-item-title")
    if title_block is None:
        return None
    candidate_links = title_block.select("a")
    title_link = next(
        (a for a in candidate_links if isinstance(a.get("href"), str) and "/article-" in a.get("href")),
        candidate_links[0] if candidate_links else None,
    )
    if title_link is None:
        return None
    href = title_link.get("href", "")
    if not isinstance(href, str) or not href:
        return None

    # ④ article_id抽出
    article_id = extract_article_id(href)
    if article_id is None:
        return None

    url = to_absolute_url(href)
    list_title = title_link.get_text(strip=True)

    price_el = item.select_one(sel.PRICE)
    price = normalize_price(price_el.get_text(strip=True)) if price_el else None

    prefecture_el = item.select_one(sel.PREFECTURE_LINK)
    prefecture = prefecture_el.get_text(strip=True) if prefecture_el else None

    # ⑤⑥ 地域判定・カテゴリ判定 (URL構造から)
    classified = _classify_supplementary_links(item)

    desc_el = item.select_one(sel.DESCRIPTION_SHORT)
    description_short = desc_el.get_text(strip=True) if desc_el else None

    history_dates = item.select(sel.HISTORY_DATES)
    updated_raw, created_raw = None, None
    for h in history_dates:
        text = h.get_text(strip=True)
        kind, _ = normalize_history_date(text, current_year)
        if kind == "更新":
            updated_raw = text
        elif kind == "作成":
            created_raw = text

    fav_el = item.select_one(sel.FAVORITE_COUNT)
    fav_raw = fav_el.get_text(strip=True) if fav_el else None
    favorite_count = normalize_favorite_count(fav_raw, current_year)

    thumb_el = item.select_one(sel.THUMBNAIL_IMG)
    thumbnail_url = thumb_el.get("src") if thumb_el else None

    return ListArticle(
        article_id=article_id,
        url=url,
        list_title=list_title,
        price=price,
        prefecture=prefecture,
        area_id=classified["area_id"],
        area_name=classified["area_name"],
        station_id=classified["station_id"],
        station_name=classified["station_name"],
        category_id=classified["category_id"],
        category_name=classified["category_name"],
        tags=classified["tags"],
        description_short=description_short,
        updated_date_raw=updated_raw,
        created_date_raw=created_raw,
        favorite_count=favorite_count,
        thumbnail_url=thumbnail_url,
        is_pr_slot=is_pr_slot_url(href),
    )


def parse_list_page(html: str, current_year: int) -> list[ListArticle]:
    """
    一覧ページHTML全体をパースし、広告を除外した投稿一覧を返す。

    ② p-articles-list-item を固定件数分すべて列挙 に対応。
    件数の絞り込み(先頭N件)は呼び出し元 (scheduler/job.py) の責務とする。
    """
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(sel.LIST_ITEM)

    articles = []
    for item in items:
        parsed = parse_list_item(item, current_year)
        if parsed is not None:
            articles.append(parsed)
    return articles


def extract_total_count(html: str) -> int | None:
    """
    一覧ページ最下部の「全242690件中 1-50件表示」相当のテキストから、
    総件数 (この例では242690) を抽出する (2026-09-14新設)。

    用途: 更新中の進捗バー (scheduler.scan_runner) で、
    scan_range_mode="days" のとき (総ページ数が事前に分からない
    モード) でも「全体件数のうちどれくらい確認したか」という概算の
    進捗を出すために使う。あくまで概算であり、実際には取得範囲・
    NGフィルタ等により、この件数に到達する前に巡回が終わることが
    多い。

    要素が見つからない・数値を抽出できない場合はNoneを返す
    (ページ構造の変化に対して壊れにくくするため。取得できなくても
    進捗バーが不定形表示にフォールバックするだけで、巡回処理自体には
    影響しない設計)。
    """
    soup = BeautifulSoup(html, "lxml")
    navi = soup.select_one(sel.PAGINATE_NAVI)
    if navi is None:
        return None

    text = navi.get_text()
    match = re.search(r"全([\d,]+)件", text)
    if match is None:
        return None

    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None
