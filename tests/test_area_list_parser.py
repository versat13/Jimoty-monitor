"""
scraper/area_list_parser.py のユニットテスト。

tests/fixtures/area_list_fukuoka_sale.html は、2026-09-12に
ユーザーが実機で https://jmty.jp/fukuoka/sale (福岡県の
売ります・あげます) から保存した実データ。
"""

from pathlib import Path

from scraper.area_list_parser import parse_area_list_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_area_list_page_returns_all_municipalities():
    """
    福岡県の実データから、41件の市区町村(市・郡)が抽出できること。
    北九州市 (area_id=731, area_name=kitakyushu) が含まれることを
    確認する (repository.scan_settings_repositoryの北九州デフォルト
    値と一致するかの回帰確認を兼ねる)。
    """
    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    options = parse_area_list_page(html)

    assert len(options) == 41

    kitakyushu = next((o for o in options if o.area_id == "731"), None)
    assert kitakyushu is not None
    assert kitakyushu.area_name == "kitakyushu"
    assert kitakyushu.display_name == "北九州市"


def test_parse_area_list_page_preserves_display_order():
    """ページ上の表示順 (福岡市が最初) を維持すること。"""
    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    options = parse_area_list_page(html)

    assert options[0].area_id == "730"
    assert options[0].display_name == "福岡市"
    assert options[1].area_id == "731"
    assert options[1].display_name == "北九州市"


def test_parse_area_list_page_excludes_current_selection_span():
    """
    「市区郡」ブロックの最初の<li>は現在選択中の都道府県全域を示す
    <span>(リンクではない)であり、これは選択肢として含まれないこと。
    """
    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    options = parse_area_list_page(html)

    names = [o.display_name for o in options]
    assert "福岡県の売ります・あげます" not in names


def test_parse_area_list_page_only_uses_municipality_block():
    """
    ページ内の他の場所 (人気キーワードの市区町村リンク等、実データに
    sale-food/sale-kid等の別カテゴリのエリアリンクが混在していた) を
    誤って拾わないこと。市区郡ブロック内は必ず /sale-all/g-all/ の
    URLパターンだが、それ以外の場所には他カテゴリのURLも存在するため、
    ブロック限定で抽出できていることを間接的に確認する
    (全件が重複なく41件に収まっていることで検証済みだが、念のため
    郡部の存在も確認しておく)。
    """
    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    options = parse_area_list_page(html)

    gun_names = [o.display_name for o in options if o.display_name.endswith("郡")]
    assert len(gun_names) == 12
    # 朝倉郡・築上郡・筑紫郡・嘉穂郡・糟屋郡・鞍手郡・三井郡・京都郡・三潴郡・遠賀郡・田川郡・八女郡


def test_parse_area_list_page_no_duplicates():
    """area_idの重複が無いこと。"""
    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    options = parse_area_list_page(html)

    area_ids = [o.area_id for o in options]
    assert len(area_ids) == len(set(area_ids))


def test_parse_area_list_page_returns_empty_when_block_not_found():
    """「市区郡」ブロック自体が無いページでは、エラーにせず空リストを返すこと。"""
    html = "<html><body><p>no municipality block here</p></body></html>"
    options = parse_area_list_page(html)

    assert options == []
