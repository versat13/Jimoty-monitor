"""
都道府県ページから市区町村 (area_id/area_name) の選択肢一覧を取得する
パーサー (2026-09-12新設)。

=== 背景 ===

これまで監視対象の市区町村 (area_id/area_name) は、設定画面
「地域」タブでユーザーが自由テキストで入力する方式だった
(repository.scan_settings_repository.update_monitored_target参照)。
これをプルダウン選択式にするため、都道府県を選ぶと実際にジモティー
から市区町村候補を取得してDBにキャッシュできるようにする。

=== 取得元ページの構造について (2026-09-12 実機HTML確認済み) ===

都道府県トップページ (例: https://jmty.jp/fukuoka) 自体には市区町村
選択メニューが無い。カテゴリページ (例: https://jmty.jp/fukuoka/sale
「売ります・あげます」) に入って初めて、ページ上部の検索条件エリアに
「市区郡」という見出しの市区町村リンク一覧が現れる
(ユーザーからの実機確認情報)。

このリンク一覧は以下のようなHTML構造を持つ
(福岡県 https://jmty.jp/fukuoka/sale で実機確認済み):

    <dl class="c-definition-list c-definition-list-horizontal">
      <dt class="c-definition-list-title ...">市区郡<span ...>：</span></dt>
      <dd class="c-definition-list-description ...">
        <ul>
          <li class="c-definition-list-item-horizontal">
            <span class="c-definition-list-item-current">福岡県の...</span>
          </li>
          <li class="c-definition-list-item-horizontal">
            <a href="https://jmty.jp/fukuoka/sale-all/g-all/a-730-fukuoka">福岡市</a>
          </li>
          <li class="c-definition-list-item-horizontal">
            <a href="https://jmty.jp/fukuoka/sale-all/g-all/a-731-kitakyushu">北九州市</a>
          </li>
          ...
        </ul>
      </dd>
    </dl>

最初の<li>は「現在の選択状態 (都道府県全域)」を示す<span>であり、
リンクではないため対象外。2番目以降の<a>タグがそれぞれ1つの市区町村
(または郡) に対応する。リンク先URLの "a-{id}-{slug}" 部分から
area_id/area_nameを抽出する
(scraper.selectors.url_patterns.extract_area()を再利用)。

都道府県によって市区町村の数は異なる (福岡県で41件確認)。カテゴリ
スラッグ (sale-all等) やグループ (g-all) の値は市区町村一覧の
取得においては本質的でない (どのカテゴリページを見ても同じ市区町村
一覧が出るはずだが、確実性のため "sale" 固定で取得する)。
"""

from dataclasses import dataclass

from bs4 import BeautifulSoup

from scraper.selectors.url_patterns import extract_area


@dataclass
class AreaOption:
    """市区町村の選択肢1件分。"""

    area_id: str
    area_name: str  # ローマ字スラッグ (例: "kitakyushu")
    display_name: str  # 表示名 (例: "北九州市")


def parse_area_list_page(html: str) -> list[AreaOption]:
    """
    都道府県のカテゴリページ (例: https://jmty.jp/fukuoka/sale) から
    市区町村の選択肢一覧を抽出する。

    「市区郡」という見出しの<dl>ブロックの中の<a>タグだけを対象にする
    (ページ内の他の場所にも偶然area_idを含むリンクが存在する可能性を
    考慮し、誤って無関係なリンクまで拾わないようにするため)。

    Args:
        html: 取得したページのHTML全体

    Returns:
        AreaOptionのリスト。ページ上での表示順を維持する。
        「市区郡」ブロック自体が見つからない場合は空リストを返す
        (エラーにはしない。都道府県によっては市区町村分けが無い
        可能性や、ページ構造が将来変わる可能性を考慮し、
        呼び出し元 (api層) が「0件でした」を扱えるようにするため)。
    """
    soup = BeautifulSoup(html, "lxml")

    target_dl = None
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).startswith("市区郡"):
            target_dl = dt.find_parent("dl")
            break

    if target_dl is None:
        return []

    options: list[AreaOption] = []
    seen_area_ids: set[str] = set()
    for a in target_dl.find_all("a"):
        href = a.get("href", "")
        if not isinstance(href, str) or not href:
            continue
        area = extract_area(href)
        if area is None:
            continue
        area_id, area_name = area
        if area_id in seen_area_ids:
            # 2026-09-12: 実機確認したページでは同じ市区町村が複数回
            # 出現することは無かったが、将来のページ構造変化に備えて
            # 重複除去しておく (最初に出現したものを採用)。
            continue
        seen_area_ids.add(area_id)

        display_name = a.get_text(strip=True)
        if not display_name:
            continue

        options.append(AreaOption(area_id=area_id, area_name=area_name, display_name=display_name))

    return options
