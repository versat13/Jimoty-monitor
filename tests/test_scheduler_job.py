"""
scheduler/job.py のユニットテスト。

このチャット環境からは実際のjmty.jpへのHTTPアクセスができないため、
scraper.fetch.fetch_html をモック化し、実データ (list_real.html,
detail_real.html等) を返すようにして一連の巡回フローを検証する。
実HTTPアクセスそのものは scripts/manual_e2e_check.py (ユーザーの
実行環境向け) で別途確認済み。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repository.article_repository import get_connection, upsert_from_list_article
from scheduler.job import run_scan
from scraper.list_parser import parse_list_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def list_html():
    return (FIXTURES / "list_real.html").read_text(encoding="utf-8")


@pytest.fixture
def list_articles(list_html):
    """
    2026-09-11新設。「終了」タブ再設計 (missing_kind分類・自動確認・
    保存期間削除) の統合テストで、実データ由来のListArticleを複数件
    使い回すためのフィクスチャ (tests/test_article_repository.py の
    同名フィクスチャと同じもの)。
    """
    return parse_list_page(list_html, current_year=2026)


@pytest.fixture
def detail_html():
    return (FIXTURES / "detail_real.html").read_text(encoding="utf-8")


@pytest.fixture
def closed_detail_html():
    return (FIXTURES / "detail_closed_real.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html2():
    """
    2026-09-06追加: 実機で「投稿日・最終更新日が表示されない」という
    報告を受けて調査した際にユーザーから提供された実物HTML
    (article_id=1pkz0e、「更新」「作成」両方の表記を持つ)。
    """
    return (FIXTURES / "detail_real2.html").read_text(encoding="utf-8")


def test_fetch_and_store_detail_extracts_created_and_updated(conn, detail_html2):
    """
    2026-09-06: detail_real2.html (実機提供) から作成・更新日時が
    正しく抽出・保存されること。調査の結果パーサー自体は正常に
    動作することが分かっており、この投稿を回帰テストとして固定する。
    """
    from scheduler.job import _fetch_and_store_detail
    from repository.article_repository import upsert_from_list_article
    from scraper.list_parser import ListArticle

    fake_list_article = ListArticle(
        article_id="1pkz0e",
        url="https://jmty.jp/fukuoka/sale-bic/article-1pkz0e",
        list_title="20インチホイールセット",
        price=1000,
        prefecture="fukuoka",
        area_id="731",
        area_name="北九州市",
        station_id=None,
        station_name=None,
        category_id="bic",
        category_name="自転車",
    )
    upsert_from_list_article(conn, fake_list_article)
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html", return_value=detail_html2):
        _fetch_and_store_detail(conn, MagicMock(), fake_list_article.url, "1pkz0e")

    row = conn.execute(
        "SELECT created_datetime, updated_datetime, detail_fetched_at "
        "FROM active_articles WHERE article_id = '1pkz0e'"
    ).fetchone()
    assert row["created_datetime"] == "2026-09-06T13:41:00"
    assert row["updated_datetime"] == "2026-09-06T15:10:00"
    assert row["detail_fetched_at"] is not None


def test_run_scan_basic_flow(conn, list_html, detail_html):
    """
    一覧取得(モック)→パース→DB照合→新規投稿は個別ページ取得(モック)、
    という一連の流れが例外なく通ること。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        # 一覧取得は list_html、それ以降の個別ページ取得は全て detail_html を返す
        mock_fetch.side_effect = [list_html] + [detail_html] * 100

        result = run_scan(conn, MagicMock(), "https://jmty.jp/fukuoka/sale-all/g-all/a-731-kitakyushu")

    assert result.total_seen == 52  # 広告除外後の実データ件数
    assert result.new_articles == 52  # 初回巡回なので全て新規

    count = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    assert count == 52


def test_run_scan_second_time_no_new_articles(conn, list_html, detail_html):
    """2回目の巡回で同じ一覧を渡すと、新規投稿は0件になること。"""
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = list_html
        result = run_scan(conn, MagicMock(), "url")

    assert result.new_articles == 0
    assert result.total_seen == 52


def test_run_scan_continues_when_one_detail_page_fails(conn, list_html, detail_html, caplog):
    """
    2026-09-06 重要バグ修正の検証: 個別ページの取得・パース中に
    (FetchError以外の) 予期しない例外が発生しても、run_scan()全体は
    中断せず、残りの投稿の処理を継続すること。

    以前はfetch_html以降の処理 (parse_detail_page, upsert_seller,
    upsert_from_detail_article) を一切例外処理していなかったため、
    1件でも例外が起きると run_scan() 自体が例外で落ち、それ以降の
    投稿が一覧由来のデータすら保存されないまま終わっていた。
    """
    call_count = {"n": 0}

    def flaky_fetch(client, url):
        if url == "url":
            return list_html
        call_count["n"] += 1
        if call_count["n"] <= 3:
            # 最初の3件の個別ページ取得だけ、予期しない例外を発生させる
            raise ValueError("想定外のパースエラー (テスト用)")
        return detail_html

    with patch("scheduler.scan_runner.fetch_html", side_effect=flaky_fetch):
        result = run_scan(conn, MagicMock(), "url")

    # 一覧由来のデータは、個別ページの成否に関わらず52件全て保存される
    assert result.total_seen == 52
    assert result.new_articles == 52
    count = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    assert count == 52


def test_fetch_and_store_detail_logs_article_id_mismatch(conn, detail_html, caplog):
    """
    2026-09-06新設: 一覧側のarticle_idと詳細ページ側でパースした
    article_idが食い違う場合、警告ログを出すこと (静かに更新が
    スキップされる不具合の早期発見のため)。
    """
    from scheduler.job import _fetch_and_store_detail
    from repository.article_repository import upsert_from_list_article
    from scraper.list_parser import ListArticle

    # 一覧側で 'different-id' として登録しておく
    fake_list_article = ListArticle(
        article_id="different-id",
        url="https://jmty.jp/fukuoka/sale-pcp/article-different-id",
        list_title="テスト投稿",
        price=100,
        prefecture="fukuoka",
        area_id="731",
        area_name="Area1",
        station_id=None,
        station_name=None,
        category_id="c1",
        category_name="Cat1",
    )
    upsert_from_list_article(conn, fake_list_article)
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html", return_value=detail_html):
        with caplog.at_level("WARNING"):
            _fetch_and_store_detail(
                conn, MagicMock(), fake_list_article.url, "different-id"
            )

    assert any("一致しません" in message for message in caplog.messages)


def test_run_scan_notifies_only_new_non_hidden_articles(conn, list_html, detail_html):
    """
    フロー⑬: 新規かつNG判定されていない投稿のみ通知対象になること。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    assert len(result.notified) == result.new_articles  # NGワード未登録なので全件通知対象

    # 通知済みが記録されていること
    row = conn.execute(
        "SELECT last_notified_at FROM active_articles WHERE article_id = ?",
        (result.notified[0],),
    ).fetchone()
    assert row["last_notified_at"] is not None


def test_run_scan_respects_ng_keyword(conn, list_html, detail_html):
    """
    NGワード登録済みの投稿は、取得・保存はされるが通知対象からは
    除外されること (仕様書5-4の取得漏れゼロ原則の確認)。
    """
    conn.execute("INSERT INTO ng_keywords (keyword) VALUES ('SSD')")
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    # SSDを含む投稿はDBには保存されているが、通知対象ではないこと
    hidden_rows = conn.execute(
        "SELECT article_id FROM active_articles WHERE is_hidden_by_keyword = 1"
    ).fetchall()
    assert len(hidden_rows) > 0  # 実データにSSDを含む投稿が存在する (前回セッションで確認済み)

    hidden_ids = {r["article_id"] for r in hidden_rows}
    assert not (hidden_ids & set(result.notified))  # NG該当は通知に含まれない


def test_run_scan_respects_ng_category(conn, list_html, detail_html):
    """NGカテゴリ登録済みの投稿も、保存はされるが通知対象からは除外されること。"""
    conn.execute("INSERT INTO ng_categories (category_id) VALUES ('oth')")
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    hidden_rows = conn.execute(
        "SELECT article_id FROM active_articles WHERE is_hidden_by_category = 1"
    ).fetchall()
    assert len(hidden_rows) > 0

    hidden_ids = {r["article_id"] for r in hidden_rows}
    assert not (hidden_ids & set(result.notified))


def test_run_scan_respects_ng_category_mid_on_first_scan(conn, list_html, closed_detail_html):
    """
    2026-09-07 バグ修正の回帰テスト: 中間カテゴリ (category_mid_id) を
    NG登録している場合、新規投稿の初回巡回時点でNGカテゴリ判定に
    反映されること。

    category_mid_id は個別ページ取得後にしか判明しないため、
    修正前は「一覧取得直後・個別ページ取得より前」にNGカテゴリ判定を
    行っており、新規投稿の初回巡回では category_mid_id が常に未確定
    (None) のまま判定されてしまい、中間カテゴリ単位のNG登録が
    初回巡回に限って効かないという不具合があった。

    closed_detail_html (detail_closed_real.html) は
    category_mid_id="1354" (調理器具) を持つ。これを全ての新規投稿の
    詳細ページ取得結果として返すようモックし、"1354" をNGカテゴリ
    登録した上で、初回巡回の時点で全件が is_hidden_by_category=1 に
    なり、通知対象が0件になることを確認する。
    """
    conn.execute(
        "INSERT INTO ng_categories (category_id, category_level) VALUES ('1354', 'mid')"
    )
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [closed_detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    assert result.new_articles > 0  # 初回巡回なので新規投稿が存在する

    rows = conn.execute(
        "SELECT article_id, category_mid_id, is_hidden_by_category FROM active_articles"
    ).fetchall()
    assert len(rows) == result.new_articles
    for row in rows:
        assert row["category_mid_id"] == "1354"
        assert row["is_hidden_by_category"] == 1

    # 中間カテゴリNGにより、初回巡回であっても通知対象は0件のはず
    assert result.notified == []


def test_run_scan_ng_seller_does_not_block_storage(conn, list_html, detail_html):
    """
    NGユーザー登録済みの出品者の投稿も、取得・保存自体は必ず行われること
    (仕様書5-4「取りに行かない判断は一切行わない」の確認)。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    # 実際に登録された出品者を1人取得し、NGユーザーとして登録する
    seller_row = conn.execute(
        "SELECT seller_id FROM active_articles WHERE seller_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert seller_row is not None
    seller_id = seller_row["seller_id"]

    conn.execute(
        "INSERT INTO seller_rules (seller_id, rule_type) VALUES (?, 'ng')", (seller_id,)
    )
    conn.commit()

    # 再度巡回しても、そのユーザーの投稿はDBから消えないこと
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    row = conn.execute(
        "SELECT is_hidden_by_seller_rule FROM active_articles WHERE seller_id = ?", (seller_id,)
    ).fetchone()
    assert row is not None  # データは存在する (削除されていない)
    assert row["is_hidden_by_seller_rule"] == 1  # フラグは立っている


def test_run_scan_price_change_detected_across_scans(conn, list_html, detail_html):
    """
    2回の巡回間で価格が変わった場合、price_changedとしてカウントされること。
    (list_htmlをそのまま複製して価格だけ書き換えるのは大掛かりなため、
    ここではDBの値を直接変更して2回目の巡回との差分を作る)
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    # 1件だけ価格をDB上で意図的に変更 (次回巡回時の一覧価格と差が出るようにする)
    row = conn.execute("SELECT article_id, price FROM active_articles LIMIT 1").fetchone()
    conn.execute(
        "UPDATE active_articles SET price = ? WHERE article_id = ?",
        ((row["price"] or 0) + 9999, row["article_id"]),
    )
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = list_html
        result = run_scan(conn, MagicMock(), "url")

    assert result.price_changed >= 1


def test_confirm_single_missing_article_restores_still_active_article(conn, list_html, detail_html):
    """
    missing状態の投稿1件が、個別ページ確認の結果まだ受付中だった場合
    activeに復帰すること (2026-09-04: run_missing_checkのバルク処理を
    廃止し、1件単位のconfirm_single_missing_articleに置き換えた)。
    """
    from scheduler.job import confirm_single_missing_article

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    # 全件をmissingにする (2回目の巡回で一覧が空だったと仮定)
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = "<html><body><ul></ul></body></html>"
        run_scan(conn, MagicMock(), "url")

    missing_rows = conn.execute(
        "SELECT article_id FROM active_articles WHERE article_status = 'missing'"
    ).fetchall()
    assert len(missing_rows) == 52
    target_id = missing_rows[0]["article_id"]

    # 1件だけ確認: detail_html(is_closed=False)が返る -> 復帰するはず
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = detail_html
        result = confirm_single_missing_article(conn, MagicMock(), target_id)

    assert result == "restored"

    row = conn.execute(
        "SELECT article_status FROM active_articles WHERE article_id = ?", (target_id,)
    ).fetchone()
    assert row["article_status"] == "active"

    # 確認していない他のmissing投稿はそのまま (アクセス数を最小限にする設計)
    other_missing_count = conn.execute(
        "SELECT COUNT(*) FROM active_articles WHERE article_status = 'missing'"
    ).fetchone()[0]
    assert other_missing_count == 51


def test_confirm_single_missing_article_closes_without_deleting(conn, list_html, detail_html, closed_detail_html):
    """
    2026-09-11変更: missing状態の投稿1件が、個別ページでis_closed=True
    と判定されても、以前のように削除されず missing_kind=
    'confirmed_closed' のまま一覧に残ること (「終了」タブ再設計)。
    """
    from scheduler.job import confirm_single_missing_article

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = "<html><body><ul></ul></body></html>"
        run_scan(conn, MagicMock(), "url")

    missing_rows = conn.execute(
        "SELECT article_id FROM active_articles WHERE article_status = 'missing'"
    ).fetchall()
    target_id = missing_rows[0]["article_id"]

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = closed_detail_html  # 「受付終了」と判定される
        result = confirm_single_missing_article(conn, MagicMock(), target_id)

    assert result == "closed"

    row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?", (target_id,)
    ).fetchone()
    assert row is not None  # 削除されていない
    assert row["article_status"] == "missing"
    assert row["missing_kind"] == "confirmed_closed"


def test_confirm_single_missing_article_closes_on_404(conn, list_html, detail_html):
    """
    2026-09-11変更: 個別ページアクセス自体が失敗(404相当)した場合も、
    削除せず missing_kind='confirmed_closed' のまま残ること。
    """
    from scraper.fetch import FetchError
    from scheduler.job import confirm_single_missing_article

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = "<html><body><ul></ul></body></html>"
        run_scan(conn, MagicMock(), "url")

    missing_rows = conn.execute(
        "SELECT article_id FROM active_articles WHERE article_status = 'missing'"
    ).fetchall()
    target_id = missing_rows[0]["article_id"]

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = FetchError("404 Not Found")
        result = confirm_single_missing_article(conn, MagicMock(), target_id)

    assert result == "closed"

    row = conn.execute(
        "SELECT missing_kind FROM active_articles WHERE article_id = ?", (target_id,)
    ).fetchone()
    assert row is not None
    assert row["missing_kind"] == "confirmed_closed"


def test_confirm_single_missing_article_returns_none_when_not_missing(conn, list_html, detail_html):
    """対象がmissing状態でない(active)場合はNoneを返し、何もしないこと。"""
    from scheduler.job import confirm_single_missing_article

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    active_row = conn.execute(
        "SELECT article_id FROM active_articles WHERE article_status = 'active' LIMIT 1"
    ).fetchone()

    result = confirm_single_missing_article(conn, MagicMock(), active_row["article_id"])

    assert result is None


def test_run_scan_purges_expired_missing_articles(conn, list_html, detail_html):
    """
    2026-09-04 新設: missingになってから3週間(既定)経過した投稿が、
    run_scan()の一環として自動的に削除されること。アクセスを伴わない
    DB内処理であることも確認する (fetch_htmlの追加呼び出しが発生しない)。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        run_scan(conn, MagicMock(), "url")

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = "<html><body><ul></ul></body></html>"
        run_scan(conn, MagicMock(), "url")

    missing_count = conn.execute(
        "SELECT COUNT(*) FROM active_articles WHERE article_status = 'missing'"
    ).fetchone()[0]
    assert missing_count == 52

    # missing_since を3週間以上前に巻き戻す (保持期限切れを模す)
    conn.execute(
        "UPDATE active_articles SET missing_since = datetime('now', '-22 days')"
        " WHERE article_status = 'missing'"
    )
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = "<html><body><ul></ul></body></html>"
        result = run_scan(conn, MagicMock(), "url")

    assert result.purged_count == 52
    assert mock_fetch.call_count == 1  # 一覧取得1回のみ (個別ページへのアクセスなし)

    remaining = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    assert remaining == 0


# --- fetch_seller_profile_on_demand (2026-08-30 「見るまでは取らない」設計) ---


@pytest.fixture
def profile_html():
    return (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")


def test_run_scan_does_not_fetch_seller_profile_automatically(conn, list_html, detail_html):
    """
    run_scan() は新規投稿を見つけても、プロフィールページへの追加アクセスを
    一切行わないこと (2026-08-30 設計変更: 巡回時の自動プロフィール取得を撤回)。
    fetch_html への呼び出し回数が「一覧1回 + 新規投稿の個別ページ分」ちょうどに
    収まっていれば、プロフィールページ分の余計な呼び出しが無いと確認できる。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan(conn, MagicMock(), "url")

    # 呼び出し回数 = 一覧取得1回 + 新規投稿数分の個別ページ取得
    # (プロフィールページ取得が紛れ込んでいれば、この回数を超える)
    assert mock_fetch.call_count == 1 + result.new_articles


def test_fetch_seller_profile_on_demand_updates_db(conn, detail_html, profile_html):
    """
    出品者が既にDBに存在する状態で呼ぶと、プロフィールページを取得して
    sellersテーブルを更新し、profile_fetched_atが記録されること。
    """
    from scheduler.job import fetch_seller_profile_on_demand
    from scraper.detail_parser import parse_detail_page
    from repository.seller_repository import get_seller, upsert_seller

    seller = parse_detail_page(detail_html).seller
    upsert_seller(conn, seller)
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = profile_html
        ok = fetch_seller_profile_on_demand(conn, MagicMock(), seller.seller_id)

    assert ok is True
    row = get_seller(conn, seller.seller_id)
    assert row["profile_fetched_at"] is not None


def test_fetch_seller_profile_on_demand_returns_false_when_seller_not_found(conn):
    """DBに存在しない出品者IDを渡すとFalseを返し、何もしないこと。"""
    from scheduler.job import fetch_seller_profile_on_demand

    ok = fetch_seller_profile_on_demand(conn, MagicMock(), "存在しないID")

    assert ok is False


def test_fetch_seller_profile_on_demand_returns_false_on_fetch_error(conn, detail_html):
    """プロフィールページ取得がFetchErrorで失敗した場合Falseを返すこと。"""
    from scheduler.job import fetch_seller_profile_on_demand
    from scraper.detail_parser import parse_detail_page
    from scraper.fetch import FetchError
    from repository.seller_repository import upsert_seller

    seller = parse_detail_page(detail_html).seller
    upsert_seller(conn, seller)
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = FetchError("404 Not Found")
        ok = fetch_seller_profile_on_demand(conn, MagicMock(), seller.seller_id)

    assert ok is False


def test_fetch_seller_profile_on_demand_fetches_only_first_page(conn, detail_html, profile_html):
    """
    2026-09-04 方針転換の検証: プロフィールページの投稿一覧が複数ページに
    分かれていても、next_page_url は辿らず1ページ目のみ取得すること。

    当初はnext_page_urlを辿って全件合算する実装だったが、恒常的に
    大量出品しているユーザーでは「更新」1回につき多数のアクセスが
    発生し、低頻度アクセスの原則 (出品者1人につき追加1アクセスに
    留める) に反すると判断し撤回した。合計出品数は1ページ目の
    「全◯件中」という表記 (other_articles_total_count) から取得済み
    なので、ページを辿らなくても総数自体は正確に分かる。

    profile_html (1ページ目) は「全30件中 1-10件表示」でnext_page_url
    を持つが、fetch_htmlは1回しか呼ばれないことを確認する。
    """
    from scheduler.job import fetch_seller_profile_on_demand
    from scraper.detail_parser import parse_detail_page
    from repository.seller_repository import upsert_seller, get_seller

    seller = parse_detail_page(detail_html).seller
    upsert_seller(conn, seller)
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = profile_html
        ok = fetch_seller_profile_on_demand(conn, MagicMock(), seller.seller_id)

    assert ok is True
    assert mock_fetch.call_count == 1  # 1ページ目のみ、追加ページは取得しない

    # 合計出品数 (post_count) は1ページ目の表記から正しく取れていること
    row = get_seller(conn, seller.seller_id)
    assert row["post_count"] == 30


# ---------------------------------------------------------------------
# 取得範囲設定 (ページ数 / 過去n日) 2026-09-07 追加
# ---------------------------------------------------------------------

EMPTY_LIST_HTML = "<html><body></body></html>"


def test_run_scan_with_range_default_is_single_page(conn, list_html, detail_html):
    """
    scan_range_mode="pages", scan_range_value=1 (デフォルト) のとき、
    従来の run_scan() (1ページ目のみ) と同じ挙動になること。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    # 1ページ目のURL (page指定なし) だけが要求されること
    first_call_url = mock_fetch.call_args_list[0].args[1]
    assert "/p-" not in first_call_url
    assert result.total_seen == 52  # list_real.html の全件数


def test_run_scan_with_range_pages_mode_multiple_pages(conn, list_html, detail_html):
    """
    scan_range_mode="pages", scan_range_value=2 のとき、1ページ目・
    2ページ目の両方を取得しにいくこと (2ページ目は投稿0件のダミー
    レスポンスとし、そこで正しく打ち切られることも確認する)。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep") as mock_sleep:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=2,
        )

    # 1ページ目の一覧 + 新規投稿分の個別ページ + 2ページ目の一覧、が
    # 呼ばれていること (2ページ目のリクエストが最後に行われたこと)
    second_list_call_urls = [c.args[1] for c in mock_fetch.call_args_list if "/p-2" in c.args[1]]
    assert len(second_list_call_urls) == 1
    assert result.total_seen == 52  # 2ページ目は0件なので合計は変わらない
    mock_sleep.assert_called_once()  # ページ間で1回だけ間隔を空けている


def test_run_scan_with_range_updates_last_scanned_at_when_row_exists(conn, list_html):
    """
    2026-09-09新設。自動更新 (サーバー側定期実行) が「前回いつ実行
    したか」を判定するため、scan_state.last_scanned_at /
    last_scan_item_count を巡回完了時に更新するようにした。
    scan_stateに既存行がある場合、その行が更新されることを確認する。
    """
    from scheduler.job import run_scan_with_range

    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, category_id, area_id, area_name) "
        "VALUES ('fukuoka', 'sale-all', 'all', '731', 'kitakyushu')"
    )
    conn.commit()

    with patch("scheduler.scan_runner.fetch_html", return_value=list_html), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    row = conn.execute("SELECT last_scanned_at, last_scan_item_count FROM scan_state").fetchone()
    assert row["last_scanned_at"] is not None
    assert row["last_scan_item_count"] == 52


def test_run_scan_with_range_does_not_crash_when_scan_state_row_missing(conn, list_html):
    """
    scan_stateにまだ行が無い状態でも、last_scanned_at更新用のUPDATE文
    (サブクエリがNULLを返す) がエラーにならず、巡回自体は正常に完了
    すること。行が存在しないケースの安全性を確認する回帰テスト
    (get_monitored_target側で行を保証しているため、実運用では
    このケースには通常到達しないが、run_scan_with_range単体の
    防御的な振る舞いとして確認しておく)。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html", return_value=list_html), \
         patch("scheduler.scan_runner.polite_sleep"):
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    assert result.total_seen == 52  # エラーにならず巡回が完了すること


def test_run_scan_with_range_display_order_continues_across_pages(conn, list_html, detail_html):
    """
    2026-09-07 バグ修正の回帰テスト。

    display_order はこれまで各ページ内で 0 から採番し直していたため、
    2ページ目以降の投稿も1ページ目と同じ 0〜49 の範囲の値で上書き
    保存され、複数ページ巡回時に公式サイトの並び順を再現できていな
    かった。ここでは同一の一覧HTML (52件) を1ページ目・2ページ目の
    両方として与え、2ページ目としてupsertされた後のdisplay_orderが
    1ページ目のときの値 (0〜) ではなく、ARTICLES_PER_PAGE (50) を
    オフセットとした値 (50〜) になっていることを直接DBで確認する。
    """
    from scheduler.job import run_scan_with_range

    call_count = {"n": 0}

    def fake_fetch(client, url):
        call_count["n"] += 1
        # 1回目 (1ページ目) と "/p-2" (2ページ目) は同一の list_html を返す。
        # それ以外は個別ページアクセスとみなし detail_html を返す。
        # 側_effectの固定リストだと個別ページアクセス回数の見積もりが
        # 少しでもずれた場合に2ページ目へ渡るレスポンスがずれてしまう
        # ため、URLで判定する方式にしている。
        if call_count["n"] == 1 or url.endswith("/p-2"):
            return list_html
        return detail_html

    with patch("scheduler.scan_runner.fetch_html", side_effect=fake_fetch), \
         patch("scheduler.scan_runner.polite_sleep"):
        # 1ページ目: 52件すべて新規のため個別ページアクセスが発生する。
        # 2ページ目: 同一HTML (同じarticle_id群) を再度与えるため、
        # 全件が既存記事として扱われ、個別ページへの追加アクセスは
        # 発生しない (upsert_from_list_article が既存分岐に入るため)。
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=2,
        )

    rows = conn.execute(
        "SELECT display_order FROM active_articles ORDER BY display_order"
    ).fetchall()
    display_orders = [row["display_order"] for row in rows]

    # 同一HTMLを2ページ目として再upsertした後なので、最終的な
    # display_order は 1ページ目由来の値 (0〜51) ではなく、
    # (page-1)*50 を加えたオフセット済みの値 (50〜) になっているはず。
    assert min(display_orders) >= 50
    assert max(display_orders) < 50 + 52


def test_run_scan_with_range_pages_mode_stops_without_sleep_when_page1_empty(conn):
    """
    1ページ目自体が0件 (指定条件に該当する投稿が無い) 場合、
    2ページ目のリクエスト自体を行わないこと (無駄なアクセスをしない)。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.return_value = EMPTY_LIST_HTML
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=3,
        )

    assert mock_fetch.call_count == 1
    assert result.total_seen == 0


def test_run_scan_with_range_days_mode_stops_when_older_than_cutoff(conn, list_html, detail_html):
    """
    scan_range_mode="days" のとき、1ページ目の時点で最も古い投稿の
    基準日 (list_real.html は最も古いもので「作成8月18日」等、
    現在日付から見て十分に古い) が範囲を下回れば、2ページ目を
    リクエストせずに打ち切ること。

    list_real.html の日付は年表記が無い月日のみ (現在年で解釈される)
    ため、このテストでは「1日」という極端に短い範囲を指定し、
    「今日以外の日付を含む一覧は必ず打ち切られる」ことを確認する
    (実データの具体的な日付に依存しない、頑健なテストにするため)。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="days", scan_range_value=1,
        )

    # 一覧ページのリクエストが1回だけであること (2ページ目に進んでいない)
    list_call_urls = [
        c.args[1] for c in mock_fetch.call_args_list if "jmty.jp/fukuoka/sale-all" in c.args[1]
    ]
    assert len(list_call_urls) == 1
    assert result.total_seen == 52


def test_run_scan_with_range_days_mode_ignores_pr_slot_for_cutoff(conn, list_html, detail_html):
    """
    2026-09-08 バグ修正の回帰テスト。

    list_real.html にはPR枠 (is_pr_slot=True) が2件含まれており、
    通常投稿がすべて「作成8月22日」であるのに対し、PR枠だけが
    「作成8月18日」「作成8月20日」というより古い日付を持つ
    (実データそのままの構成)。

    修正前は、この2件のPR枠を含めて「そのページ内の最古値」を
    計算していたため、通常投稿がまだ範囲内であってもPR枠の古さに
    引きずられて即座に巡回を打ち切ってしまっていた (実機で
    ユーザーが確認: 3日前までの設定なのに1ページ目だけで打ち切られ、
    原因はPR枠として表示されていた古い投稿だった)。

    このテストでは、PR枠 (8月18日/8月20日) を含めれば打ち切られる
    はずの範囲だが、通常投稿の日付 (8月22日) はまだ範囲内、という
    範囲を指定し、2ページ目まで正しく進むことを確認する。
    """
    from datetime import date
    from scheduler.job import run_scan_with_range

    # 2026-09-08 (今日) から「作成8月22日」までの日数を、実行環境の
    # 「今日」に依存せず動的に計算する (フィクスチャの日付が将来
    # 固定値のままでもテストが腐らないようにするため)。
    today = date.today()
    non_pr_date = date(today.year, 8, 22)
    pr_oldest_date = date(today.year, 8, 18)
    days_to_non_pr = (today - non_pr_date).days
    days_to_pr_oldest = (today - pr_oldest_date).days

    if not (days_to_non_pr < days_to_pr_oldest):
        pytest.skip("フィクスチャの日付と実行日の関係が前提と異なるため、このテストはスキップします")

    # 通常投稿(8月22日)は範囲内、PR枠最古(8月18日)は範囲外、という
    # ちょうど中間の日数を指定する。
    scan_range_value = days_to_non_pr + 1

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="days", scan_range_value=scan_range_value,
        )

    # PR枠を正しく除外していれば、通常投稿(8月22日)は範囲内のため
    # 2ページ目のリクエストまで進むはず。
    second_list_call_urls = [c.args[1] for c in mock_fetch.call_args_list if "/p-2" in c.args[1]]
    assert len(second_list_call_urls) == 1, (
        "PR枠の古い日付に引きずられて2ページ目に進めていません "
        "(is_pr_slotの投稿を最古値の計算から除外できているか確認してください)"
    )
    assert result.total_seen == 52


def test_run_scan_with_range_days_mode_continues_when_within_cutoff(conn, list_html, detail_html):
    """
    scan_range_mode="days" で、十分に大きい日数 (例えば3650日=約10年)
    を指定した場合、1ページ目の投稿はすべて範囲内に収まるため、
    2ページ目のリクエストへ進むこと。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="days", scan_range_value=3650,
        )

    second_list_call_urls = [c.args[1] for c in mock_fetch.call_args_list if "/p-2" in c.args[1]]
    assert len(second_list_call_urls) == 1
    assert result.total_seen == 52


def test_run_scan_with_range_missing_computed_across_all_pages(conn, list_html, detail_html):
    """
    複数ページ巡回のとき、missing化の判定が「全ページで見たIDの
    合計集合」に対して行われること。

    2026-09-07 バグ修正の回帰テスト: 修正前の実装 (run_scan() を
    単純に複数回呼ぶ想定) では、ページごとに独立して
    mark_missing_articles() が呼ばれてしまい、1ページ目にしか
    出現しない投稿が2ページ目の処理時に誤ってmissing化される
    おそれがあった。run_scan_with_range() は全ページの取得が
    終わってから1回だけ missing化を行うため、1ページ目由来の
    投稿がmissing化されないことを確認する。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=2,
        )

    # list_real.html由来の投稿 (52件) が誤ってmissing化されていないこと
    missing_count = conn.execute(
        "SELECT COUNT(*) AS c FROM active_articles WHERE article_status = 'missing'"
    ).fetchone()["c"]
    assert missing_count == 0


def test_run_scan_with_range_invalid_mode_raises():
    from scheduler.job import run_scan_with_range

    with pytest.raises(ValueError):
        run_scan_with_range(
            MagicMock(), MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            scan_range_mode="weeks", scan_range_value=1,
        )


def test_run_scan_with_range_invalid_value_raises():
    from scheduler.job import run_scan_with_range

    with pytest.raises(ValueError):
        run_scan_with_range(
            MagicMock(), MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            scan_range_mode="pages", scan_range_value=0,
        )


def test_run_scan_with_range_days_mode_stops_at_safety_limit_on_fallback_pages(conn, list_html, detail_html):
    """
    2026-09-13新設。無限ループ対策の回帰テスト。

    scan_range_mode="days" のとき、ジモティー側が実在しないページ番号に
    対して0件ではなく毎回同じ一覧 (フォールバックページ) を200 OKで
    返し続けるケースを想定する。list_html (list_real.html) には
    「今日」より古い日付の投稿しか含まれないため、本来なら1ページ目で
    cutoff_dateを下回って打ち切られるはずだが、ここでは
    scan_range_value を十分に大きくすることで
    「cutoff_dateを一切下回らない (=ページ送りが自然には終わらない)」
    状況を作り、fetch_htmlが常に同じlist_htmlを返し続けても
    MAX_PAGES_SAFETY_LIMIT ページで確実に打ち切られることを確認する。

    修正前 (2026-09-13より前) は MAX_PAGES_SAFETY_LIMIT が定義されて
    いるだけでwhileループ内で一度も参照されておらず、この条件では
    無限ループになっていた。
    """
    from scheduler.job import MAX_PAGES_SAFETY_LIMIT, run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html", return_value=list_html), \
         patch("scheduler.scan_runner.polite_sleep"):
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            # 十分に大きい日数を指定し、list_htmlの投稿日がcutoff_dateを
            # 下回らないようにする (=自然には終了しない状況を作る)。
            scan_range_mode="days", scan_range_value=3650,
        )

    # MAX_PAGES_SAFETY_LIMIT ページちょうどで打ち切られていること
    # (無限ループにならず、有限回で必ず戻ってくること自体がこの
    # テストの主眼)。
    assert result.total_seen == 52 * MAX_PAGES_SAFETY_LIMIT


def test_run_scan_with_range_commits_after_each_page(conn, list_html, detail_html):
    """
    2026-09-10新設 (トランザクション分割の回帰テスト)。

    以前は全ページの取得・処理が終わるまで1本のトランザクションを
    保持しており、その間他の接続からの書き込みがロック待ちになる
    問題があった。修正後は、1ページ処理するたびにcommit()が呼ばれ、
    2ページ目の一覧を取得する時点では、1ページ目分のトランザクションは
    既にcommit済み (conn.in_transaction が False) になっていることを
    確認する (全ページ分をまとめて1本のトランザクションで保持する
    従来の実装のままなら、ここでTrueのままになってしまう)。
    """
    from scheduler.job import run_scan_with_range

    in_transaction_at_page2: list[bool] = []
    values = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]

    def fetch_side_effect(client, url, *args, **kwargs):
        if "/p-2" in url:
            in_transaction_at_page2.append(conn.in_transaction)
        return values.pop(0)

    with patch("scheduler.scan_runner.fetch_html", side_effect=fetch_side_effect), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=2,
        )

    assert in_transaction_at_page2 == [False]


def test_run_scan_with_range_page1_visible_to_other_connection_before_page2(
    conn, list_html, detail_html
):
    """
    ページ単位commitにより、2ページ目に着手する前の時点で、1ページ目分の
    変更が既に他の接続からも見えている (=ロックが解放されている) ことを
    別のDB接続を使って確認する。:memory:は接続間で共有されないため、
    一時ファイルDBを使う。

    2ページ目の一覧取得は、1ページ目の一覧取得(1回目の呼び出し)の後、
    1ページ目由来の新規投稿すべての個別ページ取得が終わった後に
    行われる (URLに "/p-2" が含まれる呼び出しとして判定する)。
    """
    import os
    import tempfile

    from repository.article_repository import get_connection
    from scheduler.job import run_scan_with_range

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        main_conn = get_connection(path)
        watcher_conn = get_connection(path)
        seen_before_page2: list[int] = []

        values = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]

        def fetch_side_effect(client, url, *args, **kwargs):
            if "/p-2" in url:
                # 2ページ目の一覧取得に入る直前の時点で、1ページ目分が
                # watcher_connから見えているはず。
                count = watcher_conn.execute(
                    "SELECT COUNT(*) AS c FROM active_articles"
                ).fetchone()["c"]
                seen_before_page2.append(count)
            return values.pop(0)

        with patch("scheduler.scan_runner.fetch_html", side_effect=fetch_side_effect), \
             patch("scheduler.scan_runner.polite_sleep"):
            run_scan_with_range(
                main_conn, MagicMock(),
                prefecture="fukuoka", category_slug="sale-all",
                category_id="all", area_id="731", area_name="kitakyushu",
                scan_range_mode="pages", scan_range_value=2,
            )

        assert seen_before_page2 == [52]

        main_conn.close()
        watcher_conn.close()
    finally:
        os.remove(path)
        for ext in ("-wal", "-shm"):
            p = path + ext
            if os.path.exists(p):
                os.remove(p)


def test_run_scan_with_range_stops_when_cancel_requested(conn, list_html, detail_html):
    """
    2026-09-10新設。scheduler.scan_state_tracker.is_cancel_requested()が
    Trueを返すと、次のページに着手する前に巡回を打ち切ること。
    ScanResult.cancelled が True になり、missing化がスキップされる
    ことも確認する。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"), \
         patch("scheduler.scan_runner.is_cancel_requested") as mock_cancel:
        # 1ページ目は通常通り取得させ、2ページ目に着手する前の
        # チェックでキャンセル要求ありとして扱う
        mock_cancel.side_effect = [False, True]
        mock_fetch.side_effect = [list_html] + [detail_html] * 100

        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=5,
        )

    assert result.cancelled is True
    assert result.total_seen == 52  # 1ページ目分は反映されている

    # 1ページ目で見つかった投稿はcommit済みのはず
    count = conn.execute("SELECT COUNT(*) AS c FROM active_articles").fetchone()["c"]
    assert count == 52

    # 緊急停止時はmissing化を行わないこと (まだ見ていない後続ページの
    # 投稿を誤ってmissing扱いしないための安全対策)
    missing_count = conn.execute(
        "SELECT COUNT(*) AS c FROM active_articles WHERE article_status = 'missing'"
    ).fetchone()["c"]
    assert missing_count == 0


def test_run_scan_with_range_cancel_before_first_page_seen_zero(conn):
    """
    1ページ目に着手する前から既にキャンセル要求が出ていた場合、
    1件も取得せずに cancelled=True で終了すること。
    """
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"), \
         patch("scheduler.scan_runner.is_cancel_requested", return_value=True):
        result = run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=5,
        )

    assert result.cancelled is True
    assert result.total_seen == 0
    mock_fetch.assert_not_called()


# --- 巡回進捗の記録 (2026-09-10新設。BottomNav付近の進捗表示用) ---


def _read_progress(conn):
    row = conn.execute(
        "SELECT scan_progress_current_page, scan_progress_max_page, "
        "scan_progress_seen_count FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    return (
        row["scan_progress_current_page"],
        row["scan_progress_max_page"],
        row["scan_progress_seen_count"],
    )


def test_run_scan_with_range_records_progress_during_scan(conn, list_html, detail_html):
    """
    'pages'モードでの巡回中、ページ着手のたびにscan_progress_*列が
    更新されること (2ページ目の一覧取得直前の時点で、1ページ目分の
    進捗が既にcommit済みとして見えているかを確認する)。
    """
    from scheduler.job import run_scan_with_range

    progress_before_page2 = None
    values = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]

    def fetch_side_effect(client, url, *args, **kwargs):
        nonlocal progress_before_page2
        if "/p-2" in url:
            progress_before_page2 = _read_progress(conn)
        return values.pop(0)

    with patch("scheduler.scan_runner.fetch_html", side_effect=fetch_side_effect), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=3,
        )

    current_page, max_page, seen_count = progress_before_page2
    assert current_page == 1
    assert max_page == 3
    assert seen_count == 52


def test_run_scan_with_range_clears_progress_after_completion(conn, list_html, detail_html):
    """巡回完了後、進捗列は全てNULLに戻ること。"""
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=3,
        )

    assert _read_progress(conn) == (None, None, None)


def test_run_scan_with_range_clears_progress_after_cancel(conn, list_html, detail_html):
    """緊急停止で途中終了した場合も、進捗列はNULLに戻ること。"""
    from scheduler.job import run_scan_with_range

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"), \
         patch("scheduler.scan_runner.is_cancel_requested") as mock_cancel:
        mock_cancel.side_effect = [False, True]
        mock_fetch.side_effect = [list_html] + [detail_html] * 100

        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=5,
        )

    assert _read_progress(conn) == (None, None, None)


def test_run_scan_with_range_days_mode_has_no_max_page_before_first_page(conn, list_html, detail_html):
    """
    'days'モードでは、1ページ目を取得するまでは何ページで終わるか
    分からないため、scan_progress_max_pageは巡回開始直後・1ページ目
    fetch_html呼び出し時点ではNoneのままであること。

    2026-09-14変更: 以前はdaysモードだと巡回全体を通してずっと
    scan_progress_max_pageがNoneのままだったが、進捗バーの概算表示
    機能 (test_run_scan_with_range_days_mode_sets_estimated_max_page_
    from_total_count参照) の追加に伴い、1ページ目取得後は総件数
    ヒントから概算値がセットされるようになった。このテストは
    「1ページ目取得より前 (=概算値がまだ計算されていない段階)」
    でのNone確認に限定するよう名前・検証内容を変更した。
    """
    from scheduler.job import run_scan_with_range

    max_page_before_first_fetch = "not_set"
    values = [list_html] + [detail_html] * 100 + [EMPTY_LIST_HTML]

    def fetch_side_effect(client, url, *args, **kwargs):
        nonlocal max_page_before_first_fetch
        if max_page_before_first_fetch == "not_set":
            _, max_page_before_first_fetch, _ = _read_progress(conn)
        return values.pop(0)

    with patch("scheduler.scan_runner.fetch_html", side_effect=fetch_side_effect), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="days", scan_range_value=7,
        )

    assert max_page_before_first_fetch is None
    assert _read_progress(conn) == (None, None, None)  # 完了後はクリアされる


def test_run_scan_with_range_days_mode_sets_estimated_max_page_from_total_count(
    conn, list_html, detail_html
):
    """
    2026-09-14新設。'days'モードでも、1ページ目取得後は一覧ページの
    総件数表示 (list_real.htmlの「全242690件中」相当) から概算の
    scan_progress_max_pageがセットされ、進捗バーに概算表示ができる
    ようになること。

    list_html (list_real.html) の総件数は242690件、1ページあたり
    ARTICLES_PER_PAGE(50)件なので、素の概算値は242690/50=4853.8→
    4854ページになるが、MAX_PAGES_SAFETY_LIMIT(30)で頭打ちになる
    はず (どのみちそれ以上は巡回を続けないため、無意味に大きい
    上限を進捗バーに出す意味がない)。

    検証方法: すべてのページでlist_htmlを返す (=cutoff_dateを
    一切下回らない、無限ループ対策テストと同じ状況) ことで、
    MAX_PAGES_SAFETY_LIMITに達するまで巡回し続けさせ、そのときの
    scan_progress_max_pageを確認する。polite_sleep() は2ページ目
    以降の取得前にのみ呼ばれるため、その呼び出しタイミングで
    進捗を読み取れば「1ページ目の処理が完了した直後」の状態を
    確実に捉えられる。
    """
    from scheduler.job import MAX_PAGES_SAFETY_LIMIT, run_scan_with_range

    max_page_before_second_page = "not_set"

    def sleep_side_effect(*args, **kwargs):
        nonlocal max_page_before_second_page
        if max_page_before_second_page == "not_set":
            _, max_page_before_second_page, _ = _read_progress(conn)

    with patch("scheduler.scan_runner.fetch_html", return_value=list_html), \
         patch("scheduler.scan_runner.polite_sleep", side_effect=sleep_side_effect):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            # 十分に大きい日数を指定し、cutoff_dateを一切下回らない
            # 状況を作る (test_run_scan_with_range_days_mode_stops_at_
            # safety_limit_on_fallback_pagesと同じ考え方)。
            scan_range_mode="days", scan_range_value=3650,
        )

    assert max_page_before_second_page == MAX_PAGES_SAFETY_LIMIT


# --- 「終了」タブ再設計 (2026-09-11新設): run_scan_with_range統合テスト ---


def _make_page_result(seen_ids, max_display_order):
    """テスト用にPageScanResultを組み立てるヘルパー。"""
    from scheduler.scan_types import PageScanResult

    return PageScanResult(
        seen_ids=seen_ids,
        total_seen=len(seen_ids),
        new_articles=0,
        price_changed=0,
        notified=[],
        oldest_reference_dt=None,
        title_changed=0,
        max_display_order=max_display_order,
    )


def test_run_scan_with_range_auto_confirms_confirmed_closed_candidates(conn, list_articles, closed_detail_html):
    """
    2026-09-11新設。今回の巡回でconfirmed_closed候補に分類された投稿を、
    run_scan_with_range() が自動で個別ページ確認し、実際に終了して
    いれば missing_kind='confirmed_closed' のまま確定させること
    (range_uncertain候補には自動アクセスしないことも合わせて確認)。
    """
    from scheduler.job import run_scan_with_range

    a, b, c, d = list_articles[0], list_articles[1], list_articles[2], list_articles[3]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=1)  # a,cに挟まれて消える想定 (confirmed_closed候補)
    upsert_from_list_article(conn, c, display_order=2)
    upsert_from_list_article(conn, d, display_order=10)  # 取得範囲の末尾より後ろにいた想定
    conn.commit()

    # 今回の巡回ではa, cが出現 (b, dが消える)。見えた最大display_orderは
    # 2。bの旧display_order(1)は範囲内(<=2)=confirmed_closed候補、
    # dの旧display_order(10)は範囲外(>2)=range_uncertain候補になる。
    page_result = _make_page_result({a.article_id, c.article_id}, max_display_order=2)

    with patch("scheduler.scan_runner._scan_one_page", return_value=page_result), \
         patch("scheduler.scan_runner.fetch_html", return_value=closed_detail_html), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    b_row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?",
        (b.article_id,),
    ).fetchone()
    assert b_row["article_status"] == "missing"
    assert b_row["missing_kind"] == "confirmed_closed"  # 自動確認の結果も同じ分類のまま

    d_row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?",
        (d.article_id,),
    ).fetchone()
    assert d_row["article_status"] == "missing"
    assert d_row["missing_kind"] == "range_uncertain"  # 自動アクセスされない


def test_run_scan_with_range_auto_confirm_restores_when_still_active(conn, list_articles, detail_html):
    """
    確定終了候補を自動確認した結果、実は受付中だった場合は
    activeに復帰すること (ユーザーとの合意事項)。
    """
    from scheduler.job import run_scan_with_range

    a, b, c = list_articles[0], list_articles[1], list_articles[2]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=1)  # a,cに挟まれて消える想定 (confirmed_closed候補)
    upsert_from_list_article(conn, c, display_order=2)
    conn.commit()

    page_result = _make_page_result({a.article_id, c.article_id}, max_display_order=2)

    with patch("scheduler.scan_runner._scan_one_page", return_value=page_result), \
         patch("scheduler.scan_runner.fetch_html", return_value=detail_html), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    b_row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?",
        (b.article_id,),
    ).fetchone()
    assert b_row["article_status"] == "active"
    assert b_row["missing_kind"] is None


def test_run_scan_with_range_only_auto_confirms_newly_missing(conn, list_articles, closed_detail_html):
    """
    自動確認は「今回の巡回で新たにconfirmed_closed候補になった投稿」
    だけを対象とし、過去の巡回で既に候補になったまま未確認の投稿を
    毎回再アクセスしないこと (アクセス数の際限ない増加を防ぐための
    回帰テスト)。
    """
    from scheduler.job import run_scan_with_range

    a, b = list_articles[0], list_articles[1]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=1)
    conn.commit()
    # bは「前回以前の巡回で既にconfirmed_closed候補になっていた」
    # 状態を模する (今回のnewly_missingには含まれない)。
    conn.execute(
        "UPDATE active_articles SET article_status = 'missing', "
        "missing_since = datetime('now', '-1 day'), missing_kind = 'confirmed_closed' "
        "WHERE article_id = ?",
        (b.article_id,),
    )
    conn.commit()

    page_result = _make_page_result({a.article_id}, max_display_order=0)

    with patch("scheduler.scan_runner._scan_one_page", return_value=page_result), \
         patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    # 今回newly_missingになったのは0件 (aのみ出現、bは既にmissing)
    # なので、bへの個別ページアクセスは一切発生しないはず。
    mock_fetch.assert_not_called()


def test_run_scan_with_range_respects_retention_settings_disabled(conn, list_articles):
    """
    scan_state.retention_enabled=Falseのとき、保存期間削除処理自体が
    行われないこと (期限切れのactive投稿もmissing投稿も削除されない)。
    """
    from repository.scan_settings_repository import update_retention_settings
    from scheduler.job import run_scan_with_range

    update_retention_settings(conn, enabled=False, retention_days=7)

    article = list_articles[0]
    upsert_from_list_article(conn, article, display_order=0)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-30 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )
    conn.commit()

    page_result = _make_page_result(set(), max_display_order=None)

    with patch("scheduler.scan_runner._scan_one_page", return_value=page_result), \
         patch("scheduler.scan_runner.polite_sleep"):
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None  # retention_enabled=Falseなので削除されない


def test_run_scan_with_range_respects_custom_retention_days(conn, list_articles):
    """scan_state.retention_daysで設定した日数が実際に使われること。"""
    from repository.scan_settings_repository import update_retention_settings
    from scheduler.job import run_scan_with_range

    update_retention_settings(conn, enabled=True, retention_days=3)

    article = list_articles[0]
    upsert_from_list_article(conn, article, display_order=0)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-5 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )
    conn.commit()

    # 今回の巡回でも出現させる (article_status='active'のまま)。
    # last_seen_atはupsert_from_list_article内でdatetime('now')に
    # 更新されてしまうため、意図した「5日前に確認したきり」の状態を
    # 保つには、upsert後に改めて過去の日時へ書き換える必要がある。
    page_result = _make_page_result({article.article_id}, max_display_order=0)

    with patch("scheduler.scan_runner._scan_one_page", return_value=page_result), \
         patch("scheduler.scan_runner.polite_sleep"):
        # _scan_one_pageをモックしているため実際のupsertは発生せず、
        # last_seen_atは上で設定した「5日前」のまま保たれる。
        run_scan_with_range(
            conn, MagicMock(),
            prefecture="fukuoka", category_slug="sale-all",
            category_id="all", area_id="731", area_name="kitakyushu",
            scan_range_mode="pages", scan_range_value=1,
        )

    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is None  # 5日前 > 保存期間3日なので削除される

