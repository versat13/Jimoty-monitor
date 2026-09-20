"""
api/main.py のユニットテスト。

実データ (list_real.html, detail_real.html) を使ってDBを構築し、
FastAPIのTestClientで主要エンドポイントを検証する。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as main_module
from repository.article_repository import (
    get_connection,
    upsert_from_detail_article,
    upsert_from_list_article,
)
from repository.seller_repository import upsert_seller
from scraper.detail_parser import parse_detail_page
from scraper.list_parser import parse_list_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_path(tmp_path):
    """テスト用の一時DBファイルパスを返す。"""
    return str(tmp_path / "test_api.db")


@pytest.fixture(autouse=True)
def _reset_scan_state_tracker():
    """
    2026-09-10新設。scheduler.scan_state_tracker はプロセス内
    グローバルな状態 (現在スキャン中か等) を持つため、あるテストで
    「巡回中」のまま終わると、後続のテストにまで影響してしまう
    (例: 前のテストが例外で中断し mark_scan_finished() が呼ばれない
    まま終わった場合)。全テストの前後で強制的にリセットする。
    """
    from scheduler.scan_state_tracker import mark_scan_finished

    mark_scan_finished()
    yield
    mark_scan_finished()


@pytest.fixture
def client(db_path, monkeypatch):
    """
    実データでDBを構築し、api.main.DB_PATHをテスト用DBに差し替えた
    TestClientを返す。
    """
    monkeypatch.setattr(main_module, "DB_PATH", db_path)

    conn = get_connection(db_path)

    list_html = (FIXTURES / "list_real.html").read_text(encoding="utf-8")
    articles = parse_list_page(list_html, current_year=2026)
    for a in articles:
        upsert_from_list_article(conn, a)

    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)
    upsert_seller(conn, detail.seller)
    upsert_from_detail_article(conn, detail, seller_id=detail.seller.seller_id)

    conn.commit()
    conn.close()

    return TestClient(main_module.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_articles_returns_all_visible_by_default(client):
    """visibility指定なしの既定値は'visible'で、NG未設定なら全件返ること。"""
    r = client.get("/api/articles")
    assert r.status_code == 200
    assert len(r.json()) == 52  # list_real.htmlの広告除外後の件数


def test_list_articles_all_status(client):
    r = client.get("/api/articles?status=all")
    assert r.status_code == 200
    assert len(r.json()) == 52


def test_list_articles_includes_price_change_count(client):
    """
    2026-09-10新設。一覧APIのレスポンスにprice_change_countが含まれ、
    まだ値変更が無い投稿では0であること。
    """
    r = client.get("/api/articles")
    assert r.status_code == 200
    articles = r.json()
    assert len(articles) > 0
    for a in articles:
        assert "price_change_count" in a
        assert a["price_change_count"] == 0


def test_list_articles_includes_missing_kind(client):
    """
    2026-09-11新設。一覧APIのレスポンスにmissing_kindが含まれ、
    active状態の投稿では常にnullであること。missing状態の投稿での
    実際の値はrepository層のテストで検証済み。
    """
    r = client.get("/api/articles?status=active")
    assert r.status_code == 200
    articles = r.json()
    assert len(articles) > 0
    for a in articles:
        assert "missing_kind" in a
        assert a["missing_kind"] is None


def test_get_article_detail_includes_full_title(client):
    """個別ページ由来のfull_titleが返ること (upsert_from_detail_articleが反映されている確認)。"""
    r = client.get("/api/articles/1jntvx")
    assert r.status_code == 200
    body = r.json()
    assert body["full_title"] == "【PCセット割】ELECOM Apple Pencil 交換ペン先 3個"
    assert body["seller_name"] == "テスト出品者A"


def test_get_article_404(client):
    r = client.get("/api/articles/存在しないID")
    assert r.status_code == 404


def test_get_seller(client):
    r = client.get("/api/sellers/dummy00000000000000000002")
    assert r.status_code == 200
    body = r.json()
    assert body["seller_name"] == "テスト出品者A"
    assert body["rating"] == 5.0
    assert body["identity_verified"] is True


def test_get_seller_404(client):
    r = client.get("/api/sellers/存在しないID")
    assert r.status_code == 404


def test_get_seller_articles(client):
    r = client.get("/api/sellers/dummy00000000000000000002/articles")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["article_id"] == "1jntvx"


# --- フィルタフラグの即時反映 (2026-09-05新設) ---
# NGワード・NGカテゴリ・NGユーザーの登録/削除/切替が、次の巡回を
# 待たずに既存のDB内投稿へ即座に反映されることを確認する。
# 以前はscheduler/job.pyのrun_scan()内でしか再計算されておらず、
# 「NGユーザー登録した直後に一覧に反映されない」という報告があった。

def test_ng_keyword_registration_reflects_immediately(client):
    r0 = client.get("/api/articles?visibility=visible")
    ids_before = {a["article_id"] for a in r0.json()}
    assert "1jntvx" in ids_before

    # 1jntvxのタイトルに含まれる語でNGワード登録
    title = next(a["list_title"] for a in r0.json() if a["article_id"] == "1jntvx")
    keyword = title[:4]  # タイトル先頭の数文字を使えば必ずヒットする
    r = client.post("/api/ng-keywords", json={"keyword": keyword})
    assert r.status_code == 201

    r1 = client.get("/api/articles?visibility=visible")
    ids_after = {a["article_id"] for a in r1.json()}
    assert "1jntvx" not in ids_after  # 巡回を挟まず即座にvisibleから消える

    r2 = client.get("/api/articles?visibility=hidden")
    ids_hidden = {a["article_id"] for a in r2.json()}
    assert "1jntvx" in ids_hidden  # 即座にhiddenに現れる


def test_ng_keyword_deletion_reflects_immediately(client):
    r0 = client.get("/api/articles?visibility=visible")
    title = next(a["list_title"] for a in r0.json() if a["article_id"] == "1jntvx")
    keyword = title[:4]

    r = client.post("/api/ng-keywords", json={"keyword": keyword})
    kw_id = r.json()["id"]
    hidden_before = {a["article_id"] for a in client.get("/api/articles?visibility=hidden").json()}
    assert "1jntvx" in hidden_before

    client.delete(f"/api/ng-keywords/{kw_id}")

    hidden_after = {a["article_id"] for a in client.get("/api/articles?visibility=hidden").json()}
    assert "1jntvx" not in hidden_after  # 削除後は即座にhiddenから外れる


def test_ng_category_registration_reflects_immediately(client):
    r0 = client.get("/api/articles?visibility=visible")
    category_id = next(
        a["category_id"] for a in r0.json() if a["article_id"] == "1jntvx" and a["category_id"]
    )

    r = client.post("/api/ng-categories", json={"category_id": category_id})
    assert r.status_code == 201

    ids_after = {a["article_id"] for a in client.get("/api/articles?visibility=visible").json()}
    assert "1jntvx" not in ids_after


def test_seller_ng_registration_reflects_immediately(client):
    """
    2026-09-05: NGユーザー登録直後、その出品者の投稿が即座に
    「NG」タブに移動し「フィルタ」タブから消えること。以前はここが
    次の巡回まで反映されず、「NGタブと監視タブが同じ表示に見える」
    (実際はNG判定がまだ効いていないだけ) という報告につながっていた。
    """
    seller_id = next(
        a["seller_id"]
        for a in client.get("/api/articles?visibility=visible").json()
        if a["article_id"] == "1jntvx"
    )

    r = client.post("/api/seller-rules", json={"seller_id": seller_id, "rule_type": "ng"})
    assert r.status_code == 201

    ids_visible = {a["article_id"] for a in client.get("/api/articles?visibility=visible").json()}
    assert "1jntvx" not in ids_visible

    ids_hidden = {a["article_id"] for a in client.get("/api/articles?visibility=hidden").json()}
    assert "1jntvx" in ids_hidden


def test_seller_watch_registration_does_not_hide(client):
    """監視ユーザー登録 (rule_type='watch') はNG判定に影響しないこと。"""
    seller_id = next(
        a["seller_id"]
        for a in client.get("/api/articles?visibility=visible").json()
        if a["article_id"] == "1jntvx"
    )

    r = client.post("/api/seller-rules", json={"seller_id": seller_id, "rule_type": "watch"})
    assert r.status_code == 201

    ids_visible = {a["article_id"] for a in client.get("/api/articles?visibility=visible").json()}
    assert "1jntvx" in ids_visible  # 監視登録だけではNG扱いにならない


# --- NGワード ---

def test_create_and_list_ng_keyword(client):
    r = client.post("/api/ng-keywords", json={"keyword": "ジャンク"})
    assert r.status_code == 201
    assert r.json()["keyword"] == "ジャンク"
    assert r.json()["is_active"] is True

    r = client.get("/api/ng-keywords")
    assert len(r.json()) == 1


def test_toggle_ng_keyword(client):
    r = client.post("/api/ng-keywords", json={"keyword": "テスト"})
    kw_id = r.json()["id"]

    r = client.patch(f"/api/ng-keywords/{kw_id}/toggle")
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = client.patch(f"/api/ng-keywords/{kw_id}/toggle")
    assert r.json()["is_active"] is True


def test_delete_ng_keyword(client):
    r = client.post("/api/ng-keywords", json={"keyword": "削除対象"})
    kw_id = r.json()["id"]

    r = client.delete(f"/api/ng-keywords/{kw_id}")
    assert r.status_code == 204

    r = client.get("/api/ng-keywords")
    assert len(r.json()) == 0


# --- NGカテゴリ ---

def test_create_and_list_ng_category(client):
    r = client.post("/api/ng-categories", json={"category_id": "oth", "category_name": "その他"})
    assert r.status_code == 201

    r = client.get("/api/ng-categories")
    assert len(r.json()) == 1
    assert r.json()[0]["category_id"] == "oth"


def test_delete_ng_category(client):
    r = client.post("/api/ng-categories", json={"category_id": "food"})
    row_id = r.json()["id"]

    r = client.delete(f"/api/ng-categories/{row_id}")
    assert r.status_code == 204


# --- NGユーザー／監視ユーザー ---

def test_create_seller_rule(client):
    r = client.post(
        "/api/seller-rules",
        json={"seller_id": "abc123", "seller_name": "テストユーザー", "rule_type": "ng", "memo": "理由"},
    )
    assert r.status_code == 201
    assert r.json()["rule_type"] == "ng"


def test_create_duplicate_seller_rule_conflicts(client):
    """同一seller_idの重複登録は409になること (UNIQUE制約)。"""
    payload = {"seller_id": "dup1", "rule_type": "watch"}
    r1 = client.post("/api/seller-rules", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/api/seller-rules", json=payload)
    assert r2.status_code == 409


def test_filter_seller_rules_by_type(client):
    client.post("/api/seller-rules", json={"seller_id": "ng1", "rule_type": "ng"})
    client.post("/api/seller-rules", json={"seller_id": "watch1", "rule_type": "watch"})

    r = client.get("/api/seller-rules?rule_type=ng")
    assert len(r.json()) == 1
    assert r.json()[0]["rule_type"] == "ng"

    r = client.get("/api/seller-rules?rule_type=all")
    assert len(r.json()) == 2


def test_list_all_seller_rules_groups_ng_before_watch(client):
    """
    2026-09-05: rule_type='all'は登録順を無視し、常に「NGユーザー全員
    (その中で登録順) → 監視ユーザー全員 (その中で登録順)」の順になる
    こと。登録順のまま混在して見づらいという指摘への対応。
    """
    # あえて監視→NG→監視→NGの順に登録する (登録順のままなら混在する)
    client.post("/api/seller-rules", json={"seller_id": "w1", "rule_type": "watch"})
    client.post("/api/seller-rules", json={"seller_id": "n1", "rule_type": "ng"})
    client.post("/api/seller-rules", json={"seller_id": "w2", "rule_type": "watch"})
    client.post("/api/seller-rules", json={"seller_id": "n2", "rule_type": "ng"})

    r = client.get("/api/seller-rules?rule_type=all")
    rule_types = [item["rule_type"] for item in r.json()]
    assert rule_types == ["ng", "ng", "watch", "watch"]
    # 各グループ内は登録が新しい順 (id DESC) のままであること
    ng_ids = [item["seller_id"] for item in r.json() if item["rule_type"] == "ng"]
    assert ng_ids == ["n2", "n1"]
    watch_ids = [item["seller_id"] for item in r.json() if item["rule_type"] == "watch"]
    assert watch_ids == ["w2", "w1"]


def test_delete_seller_rule(client):
    r = client.post("/api/seller-rules", json={"seller_id": "del1", "rule_type": "ng"})
    rule_id = r.json()["id"]

    r = client.delete(f"/api/seller-rules/{rule_id}")
    assert r.status_code == 204


def test_get_seller_rule_returns_null_when_unregistered(client):
    """2026-09-04新設: 未登録の出品者はnullが返ること。"""
    r = client.get("/api/sellers/no-such-seller/rule")
    assert r.status_code == 200
    assert r.json() is None


def test_get_seller_rule_returns_registered_rule(client):
    """2026-09-04新設: 登録済みの出品者はそのレコードが返ること。"""
    client.post(
        "/api/seller-rules",
        json={"seller_id": "watchme1", "seller_name": "監視対象", "rule_type": "watch"},
    )

    r = client.get("/api/sellers/watchme1/rule")
    assert r.status_code == 200
    body = r.json()
    assert body["seller_id"] == "watchme1"
    assert body["rule_type"] == "watch"
    assert body["seller_name"] == "監視対象"


# --- ウォッチリスト (2026-08-24 新設) ---

def test_watch_article(client):
    r = client.put("/api/articles/1jntvx/watch")
    assert r.status_code == 204

    r = client.get("/api/articles/1jntvx")
    assert r.json()["is_watched"] is True


def test_unwatch_article(client):
    client.put("/api/articles/1jntvx/watch")
    r = client.delete("/api/articles/1jntvx/watch")
    assert r.status_code == 204

    r = client.get("/api/articles/1jntvx")
    assert r.json()["is_watched"] is False


def test_watch_with_memo(client):
    r = client.put("/api/articles/1jntvx/watch", json={"memo": "値下げ交渉中"})
    assert r.status_code == 204


def test_list_articles_visibility_watched(client):
    """visibility=watchedはウォッチリストに入れた投稿のみ返すこと。"""
    client.put("/api/articles/1jntvx/watch")

    r = client.get("/api/articles?visibility=watched")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["article_id"] == "1jntvx"
    assert body[0]["is_watched"] is True


def test_list_articles_watched_empty_when_none_watched(client):
    r = client.get("/api/articles?visibility=watched")
    assert r.json() == []


def test_watched_article_shown_even_if_ng_matched(client):
    """
    2026-08-24 合意事項: ウォッチリストはNG判定より優先して必ず表示する。
    NGワードでヒットする投稿でも visibility=watched では表示されること。
    """
    # is_hidden_by_keyword フラグは本来 scheduler.job.run_scan() 実行時に
    # NGワード判定によって立てられるが、この開発環境では実際のjmty.jpへの
    # HTTPアクセスができないため、フラグを直接セットして検証する。
    import sqlite3
    conn = sqlite3.connect(main_module.DB_PATH)
    conn.execute(
        "UPDATE active_articles SET is_hidden_by_keyword = 1 WHERE article_id = '1jntvx'"
    )
    conn.commit()
    conn.close()

    client.put("/api/articles/1jntvx/watch")

    r = client.get("/api/articles?visibility=watched")
    ids = [a["article_id"] for a in r.json()]
    assert "1jntvx" in ids  # NG判定されていても watched では表示される


def test_clear_watches_all(client):
    client.put("/api/articles/1jntvx/watch")
    client.put("/api/articles/1r9zer/watch")

    r = client.post("/api/watches/clear")
    assert r.status_code == 200
    assert r.json()["cleared_count"] == 2

    r = client.get("/api/articles?visibility=watched")
    assert r.json() == []


def test_clear_watches_partial(client):
    client.put("/api/articles/1jntvx/watch")
    client.put("/api/articles/1r9zer/watch")

    r = client.post("/api/watches/clear", json={"article_ids": ["1jntvx"]})
    assert r.json()["cleared_count"] == 1

    r = client.get("/api/articles?visibility=watched")
    ids = [a["article_id"] for a in r.json()]
    assert ids == ["1r9zer"]


def test_list_articles_visibility_watched_sellers(client):
    """visibility=watched_sellersは監視ユーザー(rule_type=watch)の投稿のみ返すこと。"""
    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)
    seller_id = detail.seller.seller_id

    client.post(
        "/api/seller-rules",
        json={"seller_id": seller_id, "rule_type": "watch"},
    )

    r = client.get("/api/articles?visibility=watched_sellers")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["seller_id"] == seller_id


def test_watched_sellers_empty_when_none_registered(client):
    r = client.get("/api/articles?visibility=watched_sellers")
    assert r.json() == []


def test_list_articles_visibility_watched_all_combines_both(client):
    """
    2026-09-04新設: visibility=watched_allは投稿単位の監視(watched)と
    監視ユーザー(watched_sellers)のORで返すこと。
    """
    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)
    watched_seller_id = detail.seller.seller_id

    # 監視ユーザー登録 (この出品者の投稿である1jntvxが含まれるはず)
    client.post(
        "/api/seller-rules",
        json={"seller_id": watched_seller_id, "rule_type": "watch"},
    )
    # 別の投稿を投稿単位で監視登録 (監視ユーザーとは無関係の投稿)
    client.put("/api/articles/1r9zer/watch")

    r = client.get("/api/articles?visibility=watched_all")
    assert r.status_code == 200
    ids = {a["article_id"] for a in r.json()}
    assert "1jntvx" in ids  # 監視ユーザー由来
    assert "1r9zer" in ids  # 投稿単位の監視由来


def test_list_articles_visibility_watched_all_empty_when_none(client):
    r = client.get("/api/articles?visibility=watched_all")
    assert r.json() == []


def test_used_categories_returns_distinct_category_ids(client):
    """2026-09-04新設: DBに実在するcategory_id/category_mid_idの一覧が返ること。"""
    r = client.get("/api/categories/used")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # list_real.html/detail_real.html由来の投稿には必ず何らかの
    # category_idが付与されているはず
    assert len(body) > 0
    for item in body:
        assert "category_id" in item
        assert "category_name" in item


def test_ng_seller_and_watch_seller_conflict_shows_as_watched(client):
    """
    2026-08-24 合意事項: NGユーザーと監視ユーザーが競合しても
    監視ユーザーとして扱われ、watched_sellersタブでは表示されること。
    """
    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)
    seller_id = detail.seller.seller_id

    # 監視ユーザーとして登録 (rule_typeはUNIQUE制約により1人1レコードなので、
    # ng/watch同時登録は不可。ここではwatch優先の仕様を反映し、watchのみ登録する
    # 想定で検証する)
    client.post("/api/seller-rules", json={"seller_id": seller_id, "rule_type": "watch"})

    r = client.get("/api/articles?visibility=watched_sellers")
    ids = [a["seller_id"] for a in r.json()]
    assert seller_id in ids


# --- display_orderによるデフォルトソート (2026-08-24 新設) ---

def test_list_articles_default_sort_is_display_order(client):
    """
    2026-08-24 新設: デフォルトの並び順は display_order
    (一覧取得順、公式順に近い) であること。
    """
    import sqlite3
    conn = sqlite3.connect(main_module.DB_PATH)
    # テストfixtureは52件を一括登録しているためdisplay_orderは全てNULL。
    # 明示的に3件だけ順序を設定して検証する。
    conn.execute("UPDATE active_articles SET display_order = 2 WHERE article_id = '1r9zer'")
    conn.execute("UPDATE active_articles SET display_order = 0 WHERE article_id = '1r8jq4'")
    conn.execute("UPDATE active_articles SET display_order = 1 WHERE article_id = '1rbpzt'")
    conn.commit()
    conn.close()

    r = client.get("/api/articles?visibility=all")
    ids = [a["article_id"] for a in r.json()]
    # display_orderが設定されている3件は、その順序で先頭に来ること
    ordered_subset = [aid for aid in ids if aid in ("1r8jq4", "1rbpzt", "1r9zer")]
    assert ordered_subset == ["1r8jq4", "1rbpzt", "1r9zer"]


# --- 価格履歴 (2026-08-25 新設) ---

def test_price_history_empty_when_no_change(client):
    r = client.get("/api/articles/1jntvx/price-history")
    assert r.status_code == 200
    assert r.json() == []


def test_price_history_records_changes(client):
    """価格が変化すると履歴に反映されること。"""
    import sqlite3
    conn = sqlite3.connect(main_module.DB_PATH)
    conn.execute(
        "INSERT INTO price_history (article_id, old_price, new_price) VALUES (?, ?, ?)",
        ("1jntvx", 240, 200),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/articles/1jntvx/price-history")
    body = r.json()
    assert len(body) == 1
    assert body[0]["old_price"] == 240
    assert body[0]["new_price"] == 200


def test_price_history_ordered_chronologically(client):
    """複数回の価格変化が古い順で返ること。"""
    import sqlite3
    conn = sqlite3.connect(main_module.DB_PATH)
    conn.execute(
        "INSERT INTO price_history (article_id, old_price, new_price, changed_at)"
        " VALUES (?, ?, ?, '2026-08-01 10:00:00')",
        ("1jntvx", 300, 250),
    )
    conn.execute(
        "INSERT INTO price_history (article_id, old_price, new_price, changed_at)"
        " VALUES (?, ?, ?, '2026-08-10 10:00:00')",
        ("1jntvx", 250, 240),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/articles/1jntvx/price-history")
    body = r.json()
    assert len(body) == 2
    assert body[0]["new_price"] == 250  # 古い方が先
    assert body[1]["new_price"] == 240


def test_deleted_articles_log_empty_when_no_deletion(client):
    """削除履歴が未発生の状態では空配列が返ること。"""
    r = client.get("/api/articles-deleted-log")
    assert r.status_code == 200
    assert r.json() == []


def test_deleted_articles_log_returns_snapshot(client):
    """
    削除履歴一覧に、削除時点のタイトル・価格等のスナップショットが
    含まれること (2026-09-14新設)。
    """
    import sqlite3
    conn = sqlite3.connect(main_module.DB_PATH)
    conn.execute(
        """
        INSERT INTO deleted_articles_log (
            article_id, url, list_title, price, prefecture, area_name,
            category_name, thumbnail_url, article_status,
            first_seen_at, last_seen_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "1abc23", "https://jmty.jp/fukuoka/sale-all/1abc23",
            "テスト用の削除済み投稿", 1000, "fukuoka", "北九州市",
            "家電", "https://example.com/thumb.jpg", "active",
            "2026-09-01 10:00:00", "2026-09-05 10:00:00", "2026-09-13 10:00:00",
        ),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/articles-deleted-log")
    body = r.json()
    assert len(body) == 1
    assert body[0]["article_id"] == "1abc23"
    assert body[0]["list_title"] == "テスト用の削除済み投稿"
    assert body[0]["price"] == 1000
    assert body[0]["article_status"] == "active"


# --- POST /api/scan (2026-09-09: scan_state からの監視対象読み込み) ---


def test_trigger_scan_uses_monitored_target_from_db_when_no_args(client, db_path, monkeypatch):
    """
    2026-09-09 バグ修正の回帰テスト。

    従来、POST /api/scan は引数を省略すると常にエンドポイントの
    デフォルト引数 (prefecture="fukuoka" 等、ハードコード) で実行
    されており、scan_state テーブルに保存された監視対象は一切
    参照していなかった。修正後は、引数省略時にDBの内容
    (get_monitored_target) を使うようになったことを確認する。
    """
    import sqlite3
    from unittest.mock import MagicMock

    import api.main as main_module

    # scan_stateに、デフォルト値とは異なる監視対象を直接書き込む。
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, category_id, area_id, area_name, "
        "scan_range_mode, scan_range_value) VALUES ('osaka', 'sale-fur', '1245', '999', "
        "'sample_area', 'pages', 1)"
    )
    conn.commit()
    conn.close()

    list_html = (FIXTURES / "list_real.html").read_text(encoding="utf-8")
    fetch_mock = MagicMock(return_value=list_html)
    monkeypatch.setattr(main_module, "get_db", main_module.get_db)  # 明示は不要だが意図を残す

    import scheduler.scan_runner as job_module

    monkeypatch.setattr(job_module, "fetch_html", fetch_mock)

    r = client.post("/api/scan")
    assert r.status_code == 200

    # fetch_htmlに実際に渡されたURLが、DBに保存した監視対象
    # (osaka/sale-fur/1245/999/sample_area) に基づいていること。
    called_url = fetch_mock.call_args_list[0].args[1]
    assert "osaka" in called_url
    assert "sale-fur" in called_url


def test_trigger_scan_explicit_args_override_db(client, db_path, monkeypatch):
    """
    リクエストに引数が明示的に渡された場合は、DBの内容より
    優先されること (後方互換のため)。
    """
    import sqlite3
    from unittest.mock import MagicMock

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, category_id, area_id, area_name, "
        "scan_range_mode, scan_range_value) VALUES ('osaka', 'sale-fur', '1245', '999', "
        "'sample_area', 'pages', 1)"
    )
    conn.commit()
    conn.close()

    list_html = (FIXTURES / "list_real.html").read_text(encoding="utf-8")
    fetch_mock = MagicMock(return_value=list_html)

    import scheduler.scan_runner as job_module

    monkeypatch.setattr(job_module, "fetch_html", fetch_mock)

    r = client.post(
        "/api/scan",
        params={
            "prefecture": "fukuoka", "category_slug": "sale-all",
            "category_id": "all", "area_id": "731", "area_name": "kitakyushu",
        },
    )
    assert r.status_code == 200

    called_url = fetch_mock.call_args_list[0].args[1]
    assert "fukuoka" in called_url
    assert "sale-all" in called_url


# --- GET /api/scan-status, POST /api/scan/cancel, 多重起動防止 (2026-09-10新設) ---


def test_scan_status_when_idle(client):
    """
    巡回中でないときのGET /api/scan-status。is_scanning=False、
    last_scanned_atは未実行ならNullであること。
    """
    r = client.get("/api/scan-status")
    assert r.status_code == 200
    body = r.json()
    assert body["is_scanning"] is False
    assert body["last_scanned_at"] is None
    assert body["next_scan_estimated_at"] is None


def test_scan_status_reports_last_scanned_and_next_estimated(client, db_path):
    """
    last_scanned_atとauto_scan_interval_minutesが設定済みなら、
    next_scan_estimated_atがその和として算出されること。
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, last_scanned_at, "
        "auto_scan_interval_minutes) VALUES ('fukuoka', 'sale-all', '2026-09-10 07:00:00', 30)"
    )
    conn.commit()
    conn.close()

    r = client.get("/api/scan-status")
    assert r.status_code == 200
    body = r.json()
    assert body["last_scanned_at"] == "2026-09-10 07:00:00"
    assert body["auto_scan_interval_minutes"] == 30
    assert body["next_scan_estimated_at"] == "2026-09-10 07:30:00"


def test_scan_status_no_next_estimated_when_auto_refresh_disabled(client, db_path):
    """
    自動更新が未設定 (interval=None) なら、next_scan_estimated_atも
    Nullのままであること。

    2026-09-13変更: db/schema.sqlのauto_scan_interval_minutesの
    デフォルト値を30分に変更したため、このテストが検証したい
    「未設定 (NULL)」の状態を作るには、INSERT文で明示的にNULLを
    指定する必要がある (指定を省略すると新しいデフォルト値である
    30が入ってしまうため)。
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, last_scanned_at, auto_scan_interval_minutes) "
        "VALUES ('fukuoka', 'sale-all', '2026-09-10 07:00:00', NULL)"
    )
    conn.commit()
    conn.close()

    r = client.get("/api/scan-status")
    body = r.json()
    assert body["next_scan_estimated_at"] is None


def test_scan_status_reflects_is_scanning_true(client):
    """
    scan_state_tracker.try_start_scan() で「実行中」にした状態のとき、
    GET /api/scan-status がis_scanning=Trueを返すこと。
    """
    from scheduler.scan_state_tracker import mark_scan_finished, try_start_scan

    assert try_start_scan() is True
    try:
        r = client.get("/api/scan-status")
        assert r.json()["is_scanning"] is True
    finally:
        mark_scan_finished()


def test_scan_status_progress_fields_default_to_null(client):
    """巡回中でなければ、進捗フィールドは全てNullであること。"""
    r = client.get("/api/scan-status")
    body = r.json()
    assert body["progress_current_page"] is None
    assert body["progress_max_page"] is None
    assert body["progress_seen_count"] is None


def test_scan_status_reflects_progress_fields(client, db_path):
    """
    scan_state.scan_progress_* 列に値が入っていれば、
    GET /api/scan-status がそのまま反映すること (2026-09-10新設)。
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_state (prefecture, category_slug, "
        "scan_progress_current_page, scan_progress_max_page, "
        "scan_progress_seen_count) VALUES ('fukuoka', 'sale-all', 2, 5, 128)"
    )
    conn.commit()
    conn.close()

    r = client.get("/api/scan-status")
    body = r.json()
    assert body["progress_current_page"] == 2
    assert body["progress_max_page"] == 5
    assert body["progress_seen_count"] == 128


def test_scan_status_notified_articles_default_empty(client):
    """
    2026-09-15新設。まだ一度もpickup_search条件マッチの巡回が
    行われていなければ、notified_articles・notified_atは
    それぞれ空リスト・Nullであること。
    """
    r = client.get("/api/scan-status")
    body = r.json()
    assert body["notified_articles"] == []
    assert body["notified_at"] is None


def test_scan_status_reflects_notified_articles(client, db_path):
    """
    2026-09-15新設。トースト通知・ブラウザ通知向けに、直近の巡回で
    pickup_search条件にヒットした新規投稿の簡易情報がGET
    /api/scan-status に反映されること。実際の記事情報は
    active_articlesテーブルからarticle_id経由で引かれる。
    """
    from repository.article_repository import get_connection
    from repository.scan_settings_repository import update_last_notified_articles

    conn = get_connection(db_path)
    # このfixtureのclientは実データ(list_real.html)を既に読み込んで
    # いるため、そこに含まれる実在のarticle_idを1つ使う。
    row = conn.execute("SELECT article_id, list_title FROM active_articles LIMIT 1").fetchone()
    assert row is not None
    target_id = row["article_id"]
    target_title = row["list_title"]

    update_last_notified_articles(conn, [target_id])
    conn.close()

    r = client.get("/api/scan-status")
    body = r.json()
    assert len(body["notified_articles"]) == 1
    assert body["notified_articles"][0]["article_id"] == target_id
    assert body["notified_articles"][0]["list_title"] == target_title
    assert body["notified_at"] is not None


def test_scan_status_notified_articles_ignores_unknown_ids(client, db_path):
    """
    2026-09-15新設。last_notified_article_idsにactive_articlesへ
    既に存在しないarticle_id (巡回後に削除された等) が含まれていても、
    GET /api/scan-status がエラーにならず、該当分を除いた結果を
    返すこと (article_repository.purge_missing_articles等で削除
    された投稿が、通知対象一覧に古いIDとして残っているケースを想定)。
    """
    from repository.article_repository import get_connection
    from repository.scan_settings_repository import update_last_notified_articles

    conn = get_connection(db_path)
    update_last_notified_articles(conn, ["does-not-exist-12345"])
    conn.close()

    r = client.get("/api/scan-status")
    assert r.status_code == 200
    body = r.json()
    assert body["notified_articles"] == []
    # notified_atはarticle_idsの中身に関わらず巡回完了時刻として残る
    assert body["notified_at"] is not None


def test_trigger_scan_returns_409_when_already_scanning(client):
    """
    2026-09-10新設 (多重起動防止)。既に巡回中の状態でPOST /api/scanを
    呼ぶと、新たな巡回を開始せず409を返すこと。
    """
    from scheduler.scan_state_tracker import mark_scan_finished, try_start_scan

    assert try_start_scan() is True
    try:
        r = client.post("/api/scan")
        assert r.status_code == 409
    finally:
        mark_scan_finished()


def test_trigger_scan_clears_is_scanning_after_completion(client, monkeypatch):
    """
    POST /api/scanが完了すると、scan_state_tracker.is_scanning()が
    Falseに戻ること (次のリクエストが正常に受け付けられることも確認)。
    """
    from unittest.mock import MagicMock

    from scheduler.scan_state_tracker import is_scanning

    list_html = (FIXTURES / "list_real.html").read_text(encoding="utf-8")
    fetch_mock = MagicMock(return_value=list_html)

    import scheduler.scan_runner as job_module

    monkeypatch.setattr(job_module, "fetch_html", fetch_mock)

    r = client.post("/api/scan")
    assert r.status_code == 200
    assert is_scanning() is False

    # フラグが正しく解除されていれば、続けてもう一度呼んでも409にならない
    r2 = client.post("/api/scan")
    assert r2.status_code == 200


def test_trigger_scan_clears_is_scanning_even_on_error(client, monkeypatch):
    """
    巡回処理中に例外が起きても、finally節でis_scanningフラグが
    確実に解除されること (フラグが立ちっぱなしになって以後
    永久に409が返り続ける事故を防ぐための回帰テスト)。

    FastAPIのTestClientはデフォルトで未処理例外をそのまま再送出する
    (raise_server_exceptions=True) ため、ここではpytest.raisesで
    例外自体を捕捉した上で、フラグの解除だけを確認する。
    """
    from scheduler.scan_state_tracker import is_scanning

    import scheduler.scan_runner as job_module

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(job_module, "fetch_html", boom)

    with pytest.raises(RuntimeError):
        client.post("/api/scan")

    assert is_scanning() is False


def test_trigger_scan_clears_progress_even_on_error(client, monkeypatch):
    """
    2026-09-10新設。巡回処理中に例外が起きても、finally節の
    clear_scan_progress()で進捗フィールドが確実にNULLへ戻ること
    (進捗が残ったままになって、次にis_scanning=Falseなのに古い
    「更新中… 2/5ページ」表示が残ってしまう事故を防ぐための回帰テスト)。
    """
    import scheduler.scan_runner as job_module

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(job_module, "fetch_html", boom)

    with pytest.raises(RuntimeError):
        client.post("/api/scan")

    r = client.get("/api/scan-status")
    body = r.json()
    assert body["progress_current_page"] is None
    assert body["progress_max_page"] is None
    assert body["progress_seen_count"] is None


def test_cancel_scan_returns_false_when_not_scanning(client):
    """巡回中でないときにPOST /api/scan/cancelを呼んでも、cancelled=Falseで何も起きないこと。"""
    r = client.post("/api/scan/cancel")
    assert r.status_code == 200
    assert r.json()["cancelled"] is False


def test_cancel_scan_returns_true_when_scanning(client):
    """巡回中にPOST /api/scan/cancelを呼ぶと、停止要求が伝わりcancelled=Trueが返ること。"""
    from scheduler.scan_state_tracker import (
        is_cancel_requested,
        mark_scan_finished,
        try_start_scan,
    )

    assert try_start_scan() is True
    try:
        r = client.post("/api/scan/cancel")
        assert r.status_code == 200
        assert r.json()["cancelled"] is True
        assert is_cancel_requested() is True
    finally:
        mark_scan_finished()


# --- POST /api/sellers/{seller_id}/fetch-profile (2026-08-30 「見るまでは取らない」設計) ---


def test_fetch_seller_profile_updates_seller(client, monkeypatch):
    """
    プロフィールページ取得が成功したら、更新後のSellerOutが返り、
    profile_fetched_atが記録されること。
    """
    from unittest.mock import MagicMock
    import scheduler.scan_runner as job_module

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    # 申し送り書の注意点の通り、scraper.fetch.fetch_html ではなく
    # scheduler.job.fetch_html (fetch_seller_profile_on_demand内で参照される名前空間)
    # をパッチしないと効かない。
    monkeypatch.setattr(job_module, "fetch_html", MagicMock(return_value=profile_html))

    r = client.post("/api/sellers/dummy00000000000000000002/fetch-profile")

    assert r.status_code == 200
    body = r.json()
    assert body["profile_fetched_at"] is not None


def test_fetch_seller_profile_404_when_seller_not_found(client):
    """DBに存在しない出品者IDを指定すると404になること。"""
    r = client.post("/api/sellers/存在しないID/fetch-profile")
    assert r.status_code == 404


def test_fetch_seller_profile_502_on_fetch_failure(client, monkeypatch):
    """プロフィールページの取得自体が失敗した場合502になること。"""
    from unittest.mock import MagicMock
    import scheduler.scan_runner as job_module
    from scraper.fetch import FetchError

    monkeypatch.setattr(
        job_module, "fetch_html", MagicMock(side_effect=FetchError("404 Not Found"))
    )

    r = client.post("/api/sellers/dummy00000000000000000002/fetch-profile")

    assert r.status_code == 502


def test_seller_profile_fetched_at_null_before_fetch(client):
    """fetch-profileを呼ぶ前は、profile_fetched_atがnullであること。"""
    r = client.get("/api/sellers/dummy00000000000000000002")
    assert r.status_code == 200
    assert r.json()["profile_fetched_at"] is None


# --- GET /api/sellers/{seller_id}/other-articles (2026-09-04 新設) ---


def test_get_seller_other_articles_empty_before_fetch(client):
    """プロフィール未取得の出品者では空配列が返ること。"""
    r = client.get("/api/sellers/dummy00000000000000000002/other-articles")
    assert r.status_code == 200
    assert r.json() == []


def test_get_seller_other_articles_after_fetch_profile(client, monkeypatch):
    """
    fetch-profile成功後、公式プロフィールページの投稿一覧が
    other-articles経由で取得できること。
    """
    from unittest.mock import MagicMock
    import scheduler.scan_runner as job_module

    profile_html = (FIXTURES / "profile_closed_real.html").read_text(encoding="utf-8")
    monkeypatch.setattr(job_module, "fetch_html", MagicMock(return_value=profile_html))

    r = client.post("/api/sellers/dummy00000000000000000002/fetch-profile")
    assert r.status_code == 200

    r2 = client.get("/api/sellers/dummy00000000000000000002/other-articles")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 10  # profile_closed_real.htmlの1ページ目相当
    assert body[0]["article_id"] is not None


# --- POST /api/articles/{article_id}/confirm-status (2026-09-04 新設) ---


def test_confirm_article_status_restores(client, monkeypatch, db_path):
    """
    missing状態の投稿を確認し、まだ受付中(restored)だった場合、
    article_statusがactiveに戻ること (2026-09-04合意事項)。
    """
    from unittest.mock import MagicMock
    import scheduler.scan_runner as job_module
    from repository.article_repository import get_connection

    conn = get_connection(db_path)
    row = conn.execute("SELECT article_id FROM active_articles LIMIT 1").fetchone()
    target_id = row["article_id"]
    conn.execute(
        "UPDATE active_articles SET article_status = 'missing', missing_since = datetime('now')"
        " WHERE article_id = ?",
        (target_id,),
    )
    conn.commit()
    conn.close()

    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    monkeypatch.setattr(job_module, "fetch_html", MagicMock(return_value=detail_html))

    r = client.post(f"/api/articles/{target_id}/confirm-status")

    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "restored"
    assert body["article"]["article_id"] == target_id
    assert body["article"]["article_status"] == "active"


def test_confirm_article_status_closes_without_deleting(client, monkeypatch, db_path):
    """
    2026-09-11変更: 個別ページで受付終了と判定された場合、以前は投稿が
    削除されていたが、削除せず一覧に残り missing_kind='confirmed_closed'
    になること (「終了」タブ再設計、ユーザーとの合意事項)。
    """
    from unittest.mock import MagicMock
    import scheduler.scan_runner as job_module
    from repository.article_repository import get_connection

    conn = get_connection(db_path)
    row = conn.execute("SELECT article_id FROM active_articles LIMIT 1").fetchone()
    target_id = row["article_id"]
    conn.execute(
        "UPDATE active_articles SET article_status = 'missing', missing_since = datetime('now')"
        " WHERE article_id = ?",
        (target_id,),
    )
    conn.commit()
    conn.close()

    closed_html = (FIXTURES / "detail_closed_real.html").read_text(encoding="utf-8")
    monkeypatch.setattr(job_module, "fetch_html", MagicMock(return_value=closed_html))

    r = client.post(f"/api/articles/{target_id}/confirm-status")

    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "closed"
    assert body["article"] is not None
    assert body["article"]["article_id"] == target_id

    r2 = client.get(f"/api/articles/{target_id}")
    assert r2.status_code == 200  # 削除されていない


def test_confirm_article_status_404_when_not_missing(client):
    """対象がmissing状態でない(active)場合は404になること。"""
    r = client.get("/api/articles")
    active_id = r.json()[0]["article_id"]

    r2 = client.post(f"/api/articles/{active_id}/confirm-status")
    assert r2.status_code == 404


def test_confirm_article_status_404_when_article_not_found(client):
    """存在しないarticle_idを指定すると404になること。"""
    r = client.post("/api/articles/存在しないID/confirm-status")
    assert r.status_code == 404


def test_list_articles_status_missing_filter(client, db_path):
    """
    status='missing' を指定すると、「公開終了」状態の投稿だけが
    返ること (フロントの「公開終了」タブが使う想定)。
    """
    from repository.article_repository import get_connection

    conn = get_connection(db_path)
    rows = conn.execute("SELECT article_id FROM active_articles LIMIT 3").fetchall()
    target_ids = [row["article_id"] for row in rows]
    for aid in target_ids:
        conn.execute(
            "UPDATE active_articles SET article_status = 'missing', missing_since = datetime('now')"
            " WHERE article_id = ?",
            (aid,),
        )
    conn.commit()
    conn.close()

    r = client.get("/api/articles", params={"status": "missing", "visibility": "all"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert {a["article_id"] for a in body} == set(target_ids)


# ---------------------------------------------------------------------
# 取得範囲設定 (2026-09-07 新設)
# ---------------------------------------------------------------------

def test_get_scan_range_settings_default(client):
    """設定が未保存の状態では、デフォルト値 (pages, 1, 自動更新30分) が返ること。

    2026-09-13変更: auto_scan_interval_minutesのデフォルトを
    Noneから30分に変更 (ユーザーとの合意事項)。
    """
    r = client.get("/api/settings/scan-range")
    assert r.status_code == 200
    body = r.json()
    assert body["scan_range_mode"] == "pages"
    assert body["scan_range_value"] == 1
    assert body["auto_scan_interval_minutes"] == 30


def test_update_and_get_scan_range_settings(client):
    """設定を更新した後、GETで同じ値が読み出せること。"""
    r = client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "days", "scan_range_value": 14},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scan_range_mode"] == "days"
    assert body["scan_range_value"] == 14

    r2 = client.get("/api/settings/scan-range")
    assert r2.json()["scan_range_mode"] == "days"
    assert r2.json()["scan_range_value"] == 14


def test_update_scan_range_settings_invalid_mode_returns_422(client):
    r = client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "weeks", "scan_range_value": 1},
    )
    # Literal["pages", "days"] のPydantic検証で422になる想定
    assert r.status_code == 422


def test_update_scan_range_settings_invalid_value_returns_422(client):
    r = client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "pages", "scan_range_value": 0},
    )
    assert r.status_code == 422


def test_update_auto_scan_interval_placeholder(client):
    """
    自動更新頻度は2026-09-08時点では設定項目の器のみ。値の保存・
    読み出し自体はできることを確認する (実際の自動実行は別途)。

    2026-09-08: 「取得範囲」タブと「自動更新」タブを別々の画面/端末
    から編集しても互いの値を上書きしないよう、専用エンドポイント
    (PUT /api/settings/auto-scan-interval) に分離した (旧: PUT
    /api/settings/scan-range が両方まとめて受け付けていた)。
    """
    r = client.put(
        "/api/settings/auto-scan-interval",
        json={"auto_scan_interval_minutes": 30},
    )
    assert r.status_code == 200
    assert r.json()["auto_scan_interval_minutes"] == 30

    r2 = client.get("/api/settings/scan-range")
    assert r2.json()["auto_scan_interval_minutes"] == 30


def test_update_auto_scan_interval_does_not_touch_scan_range(client):
    """
    自動更新間隔だけを更新しても、既に設定済みの取得範囲
    (scan_range_mode / scan_range_value) は変化しないこと
    (2026-09-08 API分割の回帰テスト)。
    """
    client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "days", "scan_range_value": 7},
    )

    r = client.put(
        "/api/settings/auto-scan-interval",
        json={"auto_scan_interval_minutes": 15},
    )
    assert r.status_code == 200
    assert r.json()["scan_range_mode"] == "days"
    assert r.json()["scan_range_value"] == 7
    assert r.json()["auto_scan_interval_minutes"] == 15


def test_update_scan_range_settings_does_not_touch_auto_interval(client):
    """
    取得範囲だけを更新しても、既に設定済みの自動更新間隔は
    変化しないこと (2026-09-08 API分割の回帰テスト、逆方向)。
    """
    client.put(
        "/api/settings/auto-scan-interval",
        json={"auto_scan_interval_minutes": 45},
    )

    r = client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "pages", "scan_range_value": 3},
    )
    assert r.status_code == 200
    assert r.json()["scan_range_mode"] == "pages"
    assert r.json()["scan_range_value"] == 3
    assert r.json()["auto_scan_interval_minutes"] == 45


# ---------------------------------------------------------------------
# 監視対象の地域設定 (2026-09-10新設)
# ---------------------------------------------------------------------


def test_get_region_settings_default(client):
    """
    scan_stateにまだ行が無い状態でも、北九州デフォルトが返ること
    (get_monitored_target()経由で初期行が作られるため)。
    """
    r = client.get("/api/settings/region")
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "fukuoka"
    assert body["area_id"] == "731"
    assert body["area_name"] == "kitakyushu"


def test_update_region_settings_with_area(client):
    r = client.put(
        "/api/settings/region",
        json={"prefecture": "osaka", "area_id": "999", "area_name": "sample_area"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "osaka"
    assert body["area_id"] == "999"
    assert body["area_name"] == "sample_area"

    # 反映されていることをGETでも確認
    r2 = client.get("/api/settings/region")
    assert r2.json() == body


def test_update_region_settings_prefecture_only(client):
    """area_id/area_nameを省略すると都道府県のみの監視になること。"""
    r = client.put(
        "/api/settings/region",
        json={"prefecture": "osaka"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "osaka"
    assert body["area_id"] is None
    assert body["area_name"] is None


def test_update_region_settings_rejects_partial_area(client):
    """area_idのみ・area_nameのみの指定は422になること。"""
    r = client.put(
        "/api/settings/region",
        json={"prefecture": "osaka", "area_id": "999"},
    )
    assert r.status_code == 422


def test_update_region_settings_does_not_touch_scan_range(client):
    """
    地域設定の更新は、既に設定済みの取得範囲・自動更新間隔・カテゴリを
    変化させないこと (他の設定タブとの独立性を確認する)。
    """
    client.put(
        "/api/settings/scan-range",
        json={"scan_range_mode": "days", "scan_range_value": 5},
    )
    client.put("/api/settings/auto-scan-interval", json={"auto_scan_interval_minutes": 20})

    r = client.put(
        "/api/settings/region",
        json={"prefecture": "osaka", "area_id": "999", "area_name": "sample_area"},
    )
    assert r.status_code == 200

    range_settings = client.get("/api/settings/scan-range").json()
    assert range_settings["scan_range_mode"] == "days"
    assert range_settings["scan_range_value"] == 5
    assert range_settings["auto_scan_interval_minutes"] == 20


# ---------------------------------------------------------------------
# 市区町村候補の動的取得 (2026-09-12新設)
# ---------------------------------------------------------------------


def test_get_area_options_empty_when_never_fetched(client):
    r = client.get("/api/settings/region/areas", params={"prefecture": "fukuoka"})
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "fukuoka"
    assert body["options"] == []
    assert body["fetched_at"] is None


def test_fetch_area_options_success(client, monkeypatch):
    """
    実際のジモティーのページ (実機HTMLフィクスチャ) をモックし、
    取得した市区町村候補がDBに保存されてレスポンスに含まれること。
    """
    import scraper.fetch as fetch_module

    html = (FIXTURES / "area_list_fukuoka_sale.html").read_text(encoding="utf-8")
    monkeypatch.setattr(fetch_module, "fetch_html", lambda *a, **k: html)

    r = client.post("/api/settings/region/fetch-areas", params={"prefecture": "fukuoka"})
    assert r.status_code == 200
    body = r.json()
    assert body["prefecture"] == "fukuoka"
    assert len(body["options"]) == 41
    assert body["fetched_at"] is not None

    kitakyushu = next((o for o in body["options"] if o["area_id"] == "731"), None)
    assert kitakyushu is not None
    assert kitakyushu["display_name"] == "北九州市"

    # 取得後、GETで再度参照してもキャッシュから同じ内容が返ること
    r2 = client.get("/api/settings/region/areas", params={"prefecture": "fukuoka"})
    assert len(r2.json()["options"]) == 41


def test_fetch_area_options_returns_502_when_fetch_fails(client, monkeypatch):
    from scraper.fetch import FetchError
    import scraper.fetch as fetch_module

    def boom(*args, **kwargs):
        raise FetchError("network error")

    monkeypatch.setattr(fetch_module, "fetch_html", boom)

    r = client.post("/api/settings/region/fetch-areas", params={"prefecture": "fukuoka"})
    assert r.status_code == 502


def test_fetch_area_options_returns_502_when_no_areas_found(client, monkeypatch):
    """市区郡ブロックが見つからないページの場合、502を返すこと。"""
    import scraper.fetch as fetch_module

    monkeypatch.setattr(
        fetch_module, "fetch_html", lambda *a, **k: "<html><body>no areas</body></html>"
    )

    r = client.post("/api/settings/region/fetch-areas", params={"prefecture": "fukuoka"})
    assert r.status_code == 502


# ---------------------------------------------------------------------
# 保存期間削除の設定 (2026-09-11新設)
# ---------------------------------------------------------------------


def test_get_retention_settings_default(client):
    """scan_stateにまだ行が無い状態でも、デフォルト(有効・7日)が返ること。"""
    r = client.get("/api/settings/retention")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["retention_days"] == 7


def test_update_retention_settings(client):
    r = client.put("/api/settings/retention", json={"enabled": False, "retention_days": 14})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["retention_days"] == 14

    r2 = client.get("/api/settings/retention")
    assert r2.json() == body


def test_update_retention_settings_rejects_zero_days(client):
    r = client.put("/api/settings/retention", json={"enabled": True, "retention_days": 0})
    assert r.status_code == 422


def test_update_retention_settings_does_not_touch_region(client):
    """保存期間設定の更新が、既に設定済みの地域・取得範囲を変化させないこと。"""
    client.put(
        "/api/settings/region",
        json={"prefecture": "osaka", "area_id": "999", "area_name": "sample_area"},
    )

    r = client.put("/api/settings/retention", json={"enabled": True, "retention_days": 3})
    assert r.status_code == 200

    region = client.get("/api/settings/region").json()
    assert region["prefecture"] == "osaka"


# ---------------------------------------------------------------------
# 検索ワードでピックアップするフィルタ (2026-09-08 新設)
# ---------------------------------------------------------------------


def test_get_pickup_search_default(client):
    r = client.get("/api/settings/pickup-search")
    assert r.status_code == 200
    assert r.json() == {
        "search_expression": "",
        "include_words": [],
        "exclude_words": [],
        "is_builder_synced": True,
    }


def test_update_pickup_search(client):
    r = client.put(
        "/api/settings/pickup-search",
        json={
            "search_expression": "(iPhone|iPad)",
            "include_words": ["iPhone", "iPad"],
            "exclude_words": ["ジャンク"],
            "is_builder_synced": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["search_expression"] == "(iPhone|iPad)"
    assert r.json()["include_words"] == ["iPhone", "iPad"]
    assert r.json()["exclude_words"] == ["ジャンク"]

    r2 = client.get("/api/settings/pickup-search")
    assert r2.json()["search_expression"] == "(iPhone|iPad)"


def test_update_pickup_search_persists_manual_edit_out_of_sync(client):
    """
    ビルダーの自動生成後に生の正規表現欄を手直しした場合、
    is_builder_synced=False として保存できること。
    """
    r = client.put(
        "/api/settings/pickup-search",
        json={
            "search_expression": "^(?!.*ジャンク).*iPhone",
            "include_words": ["iPhone"],
            "exclude_words": ["ジャンク"],
            "is_builder_synced": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["is_builder_synced"] is False


def test_update_pickup_search_rejects_invalid_regex(client):
    """
    正規表現として不正な文字列は422で拒否されること (保存されない)。
    """
    r = client.put(
        "/api/settings/pickup-search",
        json={"search_expression": "(unclosed"},
    )
    assert r.status_code == 422

    # 保存されていないこと (デフォルトのまま)
    r2 = client.get("/api/settings/pickup-search")
    assert r2.json()["search_expression"] == ""


def test_update_pickup_search_empty_expression_is_allowed(client):
    """空文字は「絞り込みなし」を意味し、正規表現検証をスキップして許可される。"""
    r = client.put("/api/settings/pickup-search", json={"search_expression": ""})
    assert r.status_code == 200
    assert r.json()["search_expression"] == ""


# ---------------------------------------------------------------------
# 簡易フィルタの検索履歴 (2026-09-08 新設)
# ---------------------------------------------------------------------


def test_get_search_history_empty_initially(client):
    r = client.get("/api/search-history")
    assert r.status_code == 200
    assert r.json() == {"queries": []}


def test_add_search_history_returns_updated_list(client):
    r = client.post("/api/search-history", json={"query": "iPhone"})
    assert r.status_code == 201
    assert r.json() == {"queries": ["iPhone"]}

    r2 = client.post("/api/search-history", json={"query": "iPad"})
    assert r2.json() == {"queries": ["iPad", "iPhone"]}


def test_search_history_persists_across_requests(client):
    client.post("/api/search-history", json={"query": "iPhone"})
    r = client.get("/api/search-history")
    assert r.json() == {"queries": ["iPhone"]}


def test_clear_search_history(client):
    client.post("/api/search-history", json={"query": "iPhone"})
    client.post("/api/search-history", json={"query": "iPad"})

    r = client.delete("/api/search-history")
    assert r.status_code == 204

    r2 = client.get("/api/search-history")
    assert r2.json() == {"queries": []}


# ---------------------------------------------------------------------
# NGカテゴリの階層区別 (2026-09-08 新設)
# ---------------------------------------------------------------------


def _set_category_hierarchy(db_path, article_id, *, parent_id=None, parent_name=None,
                             mid_id=None, mid_name=None):
    """
    テスト用に、既存投稿へ大カテゴリ/中間カテゴリの情報を直接注入する
    ヘルパー。実際の巡回では個別ページ取得後にしか判明しない情報だが、
    ここではテストの見通しを良くするため直接UPDATEする。
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE active_articles SET category_parent_id = ?, category_parent_name = ?, "
        "category_mid_id = ?, category_mid_name = ? WHERE article_id = ?",
        (parent_id, parent_name, mid_id, mid_name, article_id),
    )
    conn.commit()
    conn.close()


def test_create_ng_category_with_level(client):
    r = client.post(
        "/api/ng-categories",
        json={"category_id": "fur", "category_name": "家具", "category_level": "parent"},
    )
    assert r.status_code == 201
    assert r.json()["category_level"] == "parent"

    r2 = client.get("/api/ng-categories")
    assert r2.json()[0]["category_level"] == "parent"


def test_create_ng_category_defaults_to_leaf(client):
    """category_levelを省略した場合、後方互換として'leaf'扱いになること。"""
    r = client.post("/api/ng-categories", json={"category_id": "1205"})
    assert r.status_code == 201
    assert r.json()["category_level"] == "leaf"


def test_ng_category_parent_level_hides_all_descendants(client, db_path):
    """
    大カテゴリ (category_level='parent') をNG登録すると、そのカテゴリの
    配下 (ジャンル・サブジャンルを問わず) すべてが非表示になること。
    """
    _set_category_hierarchy(
        db_path, "1jntvx", parent_id="fur", parent_name="家具",
        mid_id="1354", mid_name="調理器具",
    )

    client.post(
        "/api/ng-categories",
        json={"category_id": "fur", "category_name": "家具", "category_level": "parent"},
    )

    r = client.get("/api/articles?status=active&visibility=hidden")
    ids = {a["article_id"] for a in r.json()}
    assert "1jntvx" in ids


def test_used_categories_includes_parent_level(client, db_path):
    """
    2026-09-08拡張: /api/categories/used が大カテゴリ (category_level=
    'parent') も候補として返すこと。
    """
    _set_category_hierarchy(db_path, "1jntvx", parent_id="fur", parent_name="家具")

    r = client.get("/api/categories/used")
    body = r.json()
    parent_items = [item for item in body if item["category_level"] == "parent"]
    assert any(item["category_id"] == "fur" and item["category_name"] == "家具" for item in parent_items)


def test_used_categories_leaf_includes_parent_mid_info(client, db_path):
    """
    サブジャンル (category_level='leaf') の候補には、親ジャンルの情報
    (parent_mid_id/parent_mid_name) が付与されること
    (フロントエンドでの「ジャンル→配下のサブジャンル」表示のため)。
    """
    _set_category_hierarchy(
        db_path, "1jntvx", mid_id="1354", mid_name="調理器具",
    )

    r = client.get("/api/categories/used")
    body = r.json()
    leaf_items = [item for item in body if item["category_level"] == "leaf"]
    assert len(leaf_items) > 0
    for item in leaf_items:
        if item["parent_mid_id"] == "1354":
            assert item["parent_mid_name"] == "調理器具"


def test_used_categories_mid_includes_parent_category_info(client, db_path):
    """
    2026-09-09拡張: ジャンル (category_level='mid') の候補には、親の
    大カテゴリ情報 (parent_id/parent_name) が付与されること
    (フロントエンドでの「大カテゴリ→ジャンル→サブジャンル」の
    完全な入れ子表示のため)。
    """
    _set_category_hierarchy(
        db_path, "1jntvx", parent_id="fur", parent_name="家具",
        mid_id="1354", mid_name="調理器具",
    )

    r = client.get("/api/categories/used")
    body = r.json()
    mid_items = [item for item in body if item["category_level"] == "mid"]
    assert len(mid_items) > 0
    matched = [item for item in mid_items if item["category_id"] == "1354"]
    assert len(matched) == 1
    assert matched[0]["parent_id"] == "fur"
    assert matched[0]["parent_name"] == "家具"



# ---------------------------------------------------------------------


def test_export_settings_endpoint(client):
    client.post("/api/ng-keywords", json={"keyword": "ジャンク"})

    r = client.get("/api/settings/export")
    assert r.status_code == 200
    body = r.json()
    assert body["format_version"] == 1
    assert len(body["ng_keywords"]) == 1
    assert body["ng_keywords"][0]["keyword"] == "ジャンク"


def test_import_settings_endpoint_replaces_existing(client):
    client.post("/api/ng-keywords", json={"keyword": "既存のワード"})

    r = client.post(
        "/api/settings/import",
        json={
            "format_version": 1,
            "ng_keywords": [{"keyword": "新しいワード", "is_active": True}],
            "ng_categories": [],
            "seller_rules": [],
        },
    )
    assert r.status_code == 200
    assert len(r.json()["ng_keywords"]) == 1
    assert r.json()["ng_keywords"][0]["keyword"] == "新しいワード"

    r2 = client.get("/api/ng-keywords")
    keywords = [item["keyword"] for item in r2.json()]
    assert keywords == ["新しいワード"]


def test_import_settings_endpoint_rejects_invalid_data(client):
    r = client.post(
        "/api/settings/import",
        json={
            "format_version": 1,
            "ng_keywords": [],
            "ng_categories": [],
            "seller_rules": [{"seller_id": "s1", "rule_type": "invalid"}],
        },
    )
    assert r.status_code == 422


def test_import_settings_endpoint_recomputes_filter_flags(client):
    """
    インポート後、既存投稿への非表示フラグが再計算されること
    (NGワード登録時と同様の即時反映)。
    """
    r = client.post(
        "/api/settings/import",
        json={
            "format_version": 1,
            "ng_keywords": [{"keyword": "ガス", "is_active": True}],
            "ng_categories": [],
            "seller_rules": [],
        },
    )
    assert r.status_code == 200

    r2 = client.get("/api/articles?status=active&visibility=hidden")
    titles = [a["list_title"] for a in r2.json()]
    assert any("ガス" in t for t in titles)


def test_export_import_round_trip_via_api(client):
    """エクスポート→インポートをAPI経由で行い、内容が保持されること。"""
    client.post("/api/ng-keywords", json={"keyword": "ジャンク"})
    client.put("/api/settings/scan-range", json={"scan_range_mode": "days", "scan_range_value": 10})

    exported = client.get("/api/settings/export").json()

    r = client.post("/api/settings/import", json=exported)
    assert r.status_code == 200
    assert r.json()["ng_keywords"][0]["keyword"] == "ジャンク"
    assert r.json()["scan_state"]["scan_range_value"] == 10
