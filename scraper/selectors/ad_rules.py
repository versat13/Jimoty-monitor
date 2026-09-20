"""
広告(提携求人)判定ロジック。

確定仕様 (仕様書 v1.0 4-3、HTML解析仕様確定版 16):
    「URLに alliance- がある」OR「p-item-alliance-tag が存在する」→ 広告

重要: 判定は価格解析より前に実施する。
      広告の価格表記(例: 時給1,060円)は通常の商品価格と形式が異なり、
      価格パーサーに先に通すと例外や誤変換の原因になるため。
"""

from bs4 import Tag

from scraper.selectors.url_patterns import is_alliance_url


def is_ad(item: Tag) -> bool:
    """
    p-articles-list-item 要素が広告(提携求人)かどうかを判定する。

    Args:
        item: <li class="p-articles-list-item"> のBeautifulSoup Tag

    Returns:
        True: 広告として除外すべき
        False: 通常投稿として処理を継続

    実データ検証で判明した注意点 (2026-08-22):
        PR枠投稿 (?from=pr) は
            <div class="p-item-title p-item-title-pr">
              <a class="p-item-pr-icon" href="https://jmty.jp/my/payments/new">
              <a href=".../article-xxxx?from=pr">本来のタイトルリンク</a>
            </div>
        のように <a> が2つ存在し、1つ目は広告判定と無関係な決済ページへの
        リンクである。item.select_one() で最初の1件だけを見ると、
        本来のタイトルリンクを見落とす。
        alliance-広告のURLは title 内リンクに限らず画像リンク
        (.p-item-image-link) にも同一URLが付与されているため、
        li内の全<a>を確認して1つでもalliance-を含めば広告と判定する。
    """
    # 条件1: li内のいずれかのリンクURLに alliance- を含むか
    for link in item.select("a"):
        href = link.get("href", "")
        if isinstance(href, str) and is_alliance_url(href):
            return True

    # 条件2: 提携サイトタグの存在
    if item.select_one(".p-item-alliance-tag") is not None:
        return True

    return False
