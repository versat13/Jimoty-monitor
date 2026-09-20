"""
fetch.py のユニットテスト。

注意: このチャット環境 (Claude.aiのbash_tool) はネットワーク設定で
jmty.jpへのアクセスがブロックされている (x-deny-reason: host_not_allowed)。
このため実HTTPリクエストを伴うテスト (fetch_html, fetch_area_portal) は
このファイルには含めていない。ユーザーの実行環境であれば
tests/test_fetch_integration.py (別途用意、下記参照) で実アクセスの
動作確認が可能。

ここでは、実HTTPアクセスを伴わない部分 (URL組み立て、CSRFトークン抽出)
のみを検証する。CSRF抽出は実データ (list_real.html) を使って検証しており、
これは実際にjmty.jpから取得したHTMLに対するテストである。
"""

from pathlib import Path

import pytest

from scraper.fetch import build_list_url, extract_csrf_token

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "list_real.html"


def test_build_url_full():
    """カテゴリ・地域とも指定した場合、実データで確認した形式と一致すること。"""
    url = build_list_url(
        "fukuoka", "sale-pcp", category_id="1205", area_id="731", area_name="kitakyushu"
    )
    assert url == "https://jmty.jp/fukuoka/sale-pcp/g-1205/a-731-kitakyushu"


def test_build_url_category_only():
    url = build_list_url("fukuoka", "sale-pcp", category_id="1205")
    assert url == "https://jmty.jp/fukuoka/sale-pcp/g-1205"


def test_build_url_area_only():
    url = build_list_url("fukuoka", "sale-pcp", area_id="731", area_name="kitakyushu")
    assert url == "https://jmty.jp/fukuoka/sale-pcp/a-731-kitakyushu"


def test_build_url_no_category_no_area():
    url = build_list_url("fukuoka", "sale-pcp")
    assert url == "https://jmty.jp/fukuoka/sale-pcp"


def test_build_url_with_page():
    """
    2ページ目以降は /p-N が付与されること。1ページ目は付与されないこと。

    2026-09-07 修正: 実データ (list_real.html の <link rel=next>、および
    ユーザーが実機で2ページ目を保存したHTMLの canonical) で確認した
    正しい形式である "/p-N" (パスセグメント) に合わせて修正。
    旧テストは誤った "?p-N" (クエリパラメータ) を正としてしまっていた。
    """
    url_p1 = build_list_url("fukuoka", "sale-pcp", category_id="1199", page=1)
    assert "/p-" not in url_p1

    url_p2 = build_list_url("fukuoka", "sale-pcp", category_id="1199", page=2)
    assert url_p2.endswith("/p-2")

    url_p6 = build_list_url("fukuoka", "sale-pcp", category_id="1199", page=6)
    assert url_p6.endswith("/p-6")


def test_extract_csrf_token_from_real_html():
    """
    実データ (list_real.html) からCSRFトークンが抽出できること。
    実際にジモティーのページに存在した meta要素形式:
        <meta name="csrf-param" content="authenticity_token"/>
        <meta name="csrf-token" content="..."/>
    """
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    csrf = extract_csrf_token(html)
    assert csrf is not None
    assert csrf.param_name == "authenticity_token"
    assert len(csrf.token_value) > 20  # トークンはある程度の長さを持つランダム文字列


def test_extract_csrf_token_missing():
    """CSRFのmeta要素が存在しないHTMLではNoneを返すこと。"""
    html = "<html><head></head><body>no csrf here</body></html>"
    csrf = extract_csrf_token(html)
    assert csrf is None


def test_area_portal_invalid_distance_raises():
    """distanceが仕様書の5段階固定(1/2/5/10/30)以外だとValueErrorになること。"""
    from scraper.fetch import fetch_area_portal, build_client

    with build_client() as client:
        with pytest.raises(ValueError):
            fetch_area_portal(client, "1015117", distance=15, category_group_ids=[1])
