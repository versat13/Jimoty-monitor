"""
article_repository.py のユニットテスト。

実データ (list_real.html) を使い、フロー⑧(新規/既存判定)、
missing遷移、確定判定 (2026-08-23 設計合意事項) を検証する。
"""

import dataclasses
from pathlib import Path

import pytest

from repository.article_repository import (
    confirm_missing_article,
    get_missing_articles,
    list_deleted_articles,
    mark_missing_articles,
    purge_expired_articles,
    upsert_from_list_article,
)
from repository.seller_repository import upsert_seller
from scraper.detail_parser import parse_detail_page
from scraper.list_parser import parse_list_page

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from repository.article_repository import get_connection, upsert_from_detail_article

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def list_articles():
    html = (FIXTURES / "list_real.html").read_text(encoding="utf-8")
    return parse_list_page(html, current_year=2026)


def test_new_article_is_inserted(conn, list_articles):
    article = list_articles[0]
    result = upsert_from_list_article(conn, article)
    assert result.is_new is True
    assert result.price_changed is False

    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None
    assert row["article_status"] == "active"
    assert row["list_title"] == article.list_title


def test_all_real_articles_insert_without_error(conn, list_articles):
    """実データ52件すべてが例外なく新規登録できること。"""
    for a in list_articles:
        result = upsert_from_list_article(conn, a)
        assert result.is_new is True

    count = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    assert count == len(list_articles)


def test_existing_article_no_price_change(conn, list_articles):
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    result = upsert_from_list_article(conn, article)  # 同じ内容で再度流す
    assert result.is_new is False
    assert result.price_changed is False

    history_count = conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE article_id = ?", (article.article_id,)
    ).fetchone()[0]
    assert history_count == 0


def test_price_change_recorded(conn, list_articles):
    """
    価格変化があった場合、price_historyに記録され、かつ
    active_articles.price が更新されること (仕様書フロー⑧)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    modified = dataclasses.replace(article, price=(article.price or 0) + 500)
    result = upsert_from_list_article(conn, modified)

    assert result.is_new is False
    assert result.price_changed is True
    assert result.old_price == article.price
    assert result.new_price == modified.price

    row = conn.execute(
        "SELECT price FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row["price"] == modified.price

    history = conn.execute(
        "SELECT * FROM price_history WHERE article_id = ?", (article.article_id,)
    ).fetchall()
    assert len(history) == 1
    assert history[0]["old_price"] == article.price
    assert history[0]["new_price"] == modified.price


def test_new_article_price_change_count_is_zero(conn, list_articles):
    """新規登録時点では、まだ一度も値変更が確認されていないので0であること。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    row = conn.execute(
        "SELECT price_change_count FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["price_change_count"] == 0


def test_price_change_increments_count(conn, list_articles):
    """
    2026-09-10新設。価格変化があった回のみ price_change_count が
    +1されること (一覧カードの「n回目の値変更」ラベル用)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    modified = dataclasses.replace(article, price=(article.price or 0) + 500)
    upsert_from_list_article(conn, modified)

    row = conn.execute(
        "SELECT price_change_count FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["price_change_count"] == 1


def test_price_change_count_accumulates_across_multiple_changes(conn, list_articles):
    """複数回価格が変化すれば、そのたびに+1され続けること (累計カウント)。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    price = article.price or 1000
    for _ in range(3):
        price += 500
        upsert_from_list_article(conn, dataclasses.replace(article, price=price))

    row = conn.execute(
        "SELECT price_change_count FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["price_change_count"] == 3


def test_price_change_count_not_incremented_without_price_change(conn, list_articles):
    """
    価格が変わらない巡回ではカウントされないこと
    (title_changed_atのように「一度上がったら下がらない」性質を
    確認するため、価格以外 (タイトル) が変わってもカウントは
    増えないことも合わせて確認する)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    upsert_from_list_article(conn, article)  # 同じ内容で再度upsert

    modified_title_only = dataclasses.replace(article, list_title="タイトルだけ変更")
    upsert_from_list_article(conn, modified_title_only)

    row = conn.execute(
        "SELECT price_change_count FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["price_change_count"] == 0


def test_price_change_count_persists_after_missing_and_restored(conn, list_articles):
    """
    2026-09-10新設。missing状態からactiveに復帰しても、
    price_change_countはリセットされないこと (ユーザーとの合意事項:
    「監視範囲外」→自動確認でactiveに戻っても累計は保持し続ける)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    modified = dataclasses.replace(article, price=(article.price or 0) + 500)
    upsert_from_list_article(conn, modified)

    mark_missing_articles(conn, seen_article_ids=set())  # 一覧に出なかったことにする

    # 再び一覧に出現 (missingからactiveへ復帰)
    upsert_from_list_article(conn, modified)

    row = conn.execute(
        "SELECT price_change_count, article_status FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["article_status"] == "active"
    assert row["price_change_count"] == 1  # リセットされていない


def test_title_changed_is_reflected_as_latest_value(conn, list_articles):
    """
    2026-09-07 方針変更: ジモティー運用上、既存投稿のタイトルが
    「引取が決まりました！○○」のように後から書き換えられることが
    あるため、タイトルも価格と同様に一覧巡回のたびに比較し、
    変化があれば最新値へ上書きする (旧: 2026-08-23合意の「タイトル
    変更は追跡しない」から方針変更。履歴 (変遷) は持たず、単純に
    最新値へ上書きするのみで、個別ページへの再アクセスは発生しない)。
    """
    article = list_articles[0]
    result_initial = upsert_from_list_article(conn, article)
    assert result_initial.is_new is True

    modified = dataclasses.replace(article, list_title="全く違うタイトルに変更")
    result = upsert_from_list_article(conn, modified)

    assert result.title_changed is True
    assert result.old_title == article.list_title
    assert result.new_title == "全く違うタイトルに変更"

    row = conn.execute(
        "SELECT list_title, title_changed_at FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["list_title"] == "全く違うタイトルに変更"  # 最新のタイトルに上書きされている
    assert row["title_changed_at"] is not None


def test_title_unchanged_does_not_set_title_changed_flag(conn, list_articles):
    """
    タイトルが変わっていない巡回では title_changed=False であり、
    title_changed_at も (前回設定されていなければ) NULLのままであること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    result = upsert_from_list_article(conn, article)  # 同じタイトルで再度upsert

    assert result.title_changed is False

    row = conn.execute(
        "SELECT title_changed_at FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["title_changed_at"] is None


def test_title_change_does_not_affect_price_history(conn, list_articles):
    """
    タイトル変更は price_history のような履歴テーブルを持たない
    (ユーザーとの合意事項)。タイトルのみ変わったケースで
    price_history に行が増えていないことを確認する。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    modified = dataclasses.replace(article, list_title="最終値下げ！" + article.list_title)
    upsert_from_list_article(conn, modified)

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM price_history WHERE article_id = ?", (article.article_id,)
    ).fetchone()["c"]
    assert count == 0


def test_title_and_price_can_change_simultaneously(conn, list_articles):
    """
    価格とタイトルが同じ巡回で同時に変わっても、両方とも正しく
    検知・反映されること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    modified = dataclasses.replace(
        article, list_title="最終値下げ！" + article.list_title, price=(article.price or 0) + 100,
    )
    result = upsert_from_list_article(conn, modified)

    assert result.title_changed is True
    assert result.price_changed is True

    row = conn.execute(
        "SELECT list_title, price FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["list_title"] == modified.list_title
    assert row["price"] == modified.price


# --- missing遷移 (2026-08-23 設計合意事項) ---

def test_mark_missing_when_not_in_current_scan(conn, list_articles):
    """一覧に出現しなかった投稿がmissing状態になること。"""
    for a in list_articles:
        upsert_from_list_article(conn, a)

    seen_ids = {a.article_id for a in list_articles[5:]}  # 先頭5件を欠落させる
    missing = mark_missing_articles(conn, seen_ids)

    assert len(missing) == 5
    assert set(missing) == {a.article_id for a in list_articles[:5]}

    for aid in missing:
        row = conn.execute(
            "SELECT article_status, missing_since FROM active_articles WHERE article_id = ?", (aid,)
        ).fetchone()
        assert row["article_status"] == "missing"
        assert row["missing_since"] is not None


def test_missing_does_not_delete_immediately(conn, list_articles):
    """
    即削除ではなくmissing状態への遷移に留まること
    (初回相談で指摘した誤判定リスクへの対応の核心)。
    """
    for a in list_articles:
        upsert_from_list_article(conn, a)

    seen_ids = {a.article_id for a in list_articles[1:]}
    mark_missing_articles(conn, seen_ids)

    count = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    assert count == len(list_articles)  # 誰も削除されていない


def test_reappearing_article_restored_to_active(conn, list_articles):
    """
    一度missingになった投稿が、次の巡回で一覧に再出現した場合
    activeに復帰すること (新着ラッシュで一時的に押し出された場合の救済)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    mark_missing_articles(conn, set())  # 一覧が空 = 全部missingになる

    row = conn.execute(
        "SELECT article_status FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row["article_status"] == "missing"

    # 次の巡回で再出現
    result = upsert_from_list_article(conn, article)
    assert result.is_new is False

    row = conn.execute(
        "SELECT article_status FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row["article_status"] == "active"


def test_get_missing_articles(conn, list_articles):
    for a in list_articles:
        upsert_from_list_article(conn, a)
    mark_missing_articles(conn, {a.article_id for a in list_articles[3:]})

    missing_rows = get_missing_articles(conn)
    assert len(missing_rows) == 3


# --- 個別ページでの確定判定 (2026-08-23 設計合意事項) ---

def test_confirm_missing_restored_when_still_active(conn, list_articles):
    """
    個別ページを確認した結果、まだ受付中(is_closed=False)だった場合、
    activeに復帰すること (単に一覧の固定件数から押し出されただけのケース)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())

    result = confirm_missing_article(conn, article.article_id, still_exists=True, is_closed=False)
    assert result == "restored"

    row = conn.execute(
        "SELECT article_status FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row["article_status"] == "active"


def test_confirm_missing_closed_when_closed(conn, list_articles):
    """
    2026-09-11変更: 個別ページでis_closed=Trueが確認された場合、
    以前は削除されていたが、削除せずmissing_kind='confirmed_closed'
    のまま一覧に残ること (「終了」タブ再設計、ユーザーとの合意事項)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())

    result = confirm_missing_article(conn, article.article_id, still_exists=True, is_closed=True)
    assert result == "closed"

    row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row is not None  # 削除されていない
    assert row["article_status"] == "missing"
    assert row["missing_kind"] == "confirmed_closed"


def test_confirm_missing_closed_when_404(conn, list_articles):
    """
    2026-09-11変更: 個別ページ自体が存在しない(still_exists=False)
    場合も、削除せずmissing_kind='confirmed_closed'のまま残ること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())

    result = confirm_missing_article(conn, article.article_id, still_exists=False, is_closed=False)
    assert result == "closed"

    row = conn.execute(
        "SELECT article_status, missing_kind FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row is not None
    assert row["missing_kind"] == "confirmed_closed"


def test_status_history_recorded(conn, list_articles):
    """
    article_status_history に、状態遷移の経緯が記録されること
    (猶予ロジックのブラックボックス化を避けるための可視化。合意事項)。

    2026-09-11変更: 終了確定時にDBから削除しなくなったことに伴い、
    to_status="deleted"ではなく"missing"のまま (missing_kindの変化と
    してreasonに残す) 記録に変わった。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())
    confirm_missing_article(conn, article.article_id, still_exists=True, is_closed=True)

    history = conn.execute(
        "SELECT * FROM article_status_history WHERE article_id = ? ORDER BY id",
        (article.article_id,),
    ).fetchall()

    assert len(history) == 2
    assert history[0]["from_status"] == "active"
    assert history[0]["to_status"] == "missing"
    assert history[0]["reason"] == "list_not_found"
    assert history[1]["from_status"] == "missing"
    assert history[1]["to_status"] == "missing"
    assert history[1]["reason"] == "detail_confirmed_closed"


# --- 個別ページ情報の統合 (実データ、外部キー依存順序の確認) ---

def test_detail_article_requires_seller_upserted_first(conn, list_articles):
    """
    seller_idはsellersテーブルへの外部キー制約を持つため、
    先にupsert_sellerしておかないとupsert_from_detail_articleが失敗すること
    (設計上の意図的な制約であることの確認)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)

    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)
    # article_idを無理やり一致させて未登録のseller_idで試みる
    detail_forced = dataclasses.replace(detail, article_id=article.article_id)

    with pytest.raises(Exception):  # sqlite3.IntegrityError
        upsert_from_detail_article(conn, detail_forced, seller_id=detail.seller.seller_id)


def test_detail_article_integration_after_seller_registered(conn, list_articles):
    """正しい順序(seller登録→詳細追加)なら成功し、JOINで出品者情報が引けること。"""
    detail_html = (FIXTURES / "detail_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)

    # detail.article_id (1jntvx) は list_real.html に実在する
    article = next(a for a in list_articles if a.article_id == detail.article_id)
    upsert_from_list_article(conn, article)

    upsert_seller(conn, detail.seller)
    upsert_from_detail_article(conn, detail, seller_id=detail.seller.seller_id)

    joined = conn.execute(
        """
        SELECT a.full_title, s.seller_name, s.rating
        FROM active_articles a LEFT JOIN sellers s ON a.seller_id = s.seller_id
        WHERE a.article_id = ?
        """,
        (detail.article_id,),
    ).fetchone()

    assert joined["full_title"] == detail.full_title
    assert joined["seller_name"] == "テスト出品者A"
    assert joined["rating"] == 5.0


def test_detail_article_overwrites_category_from_list(conn, list_articles):
    """
    2026-09-08 バグ修正の回帰テスト。

    従来、upsert_from_detail_article() はcategory_id/category_name
    (詳細カテゴリ) を更新しておらず、一覧ページ由来の粗い値のまま
    固定されていた。一覧ページはカテゴリ・ジャンル・サブジャンルを
    区別できないため、詳細ページ (BreadcrumbList由来、より正確)
    取得後はcategory_id/category_nameも上書きされるべきである。

    detail_closed_real.html (生活雑貨 > 調理器具 > 鍋、グリル) の
    category_id ("1359") が、一覧由来の値を上書きしてDBに反映
    されることを確認する。
    """
    detail_html = (FIXTURES / "detail_closed_real.html").read_text(encoding="utf-8")
    detail = parse_detail_page(detail_html)

    # list_real.html には detail_closed_real.html と同じarticle_idの
    # 投稿が実在しないため、任意の一覧投稿にarticle_idを合わせて
    # 疑似的に「一覧由来の粗いcategory_idが、詳細取得後に上書き
    # される」状況を再現する。
    article = list_articles[0]
    original_list_category_id = article.category_id
    detail_forced = dataclasses.replace(detail, article_id=article.article_id)

    upsert_from_list_article(conn, article)
    upsert_seller(conn, detail.seller)
    upsert_from_detail_article(conn, detail_forced, seller_id=detail.seller.seller_id)

    row = conn.execute(
        "SELECT category_id, category_name, category_mid_id, category_mid_name, "
        "category_parent_id, category_parent_name FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()

    # 詳細ページ由来の値 (サブジャンル="鍋、グリル") で上書きされ、
    # 一覧由来の粗い値 (original_list_category_id) のままではないこと。
    assert row["category_id"] == "1359"
    assert row["category_id"] != original_list_category_id
    assert row["category_name"] == "鍋、グリル"
    assert row["category_mid_id"] == "1354"
    assert row["category_mid_name"] == "調理器具"
    assert row["category_parent_id"] == "sale-hom"
    assert row["category_parent_name"] == "生活雑貨"


# --- display_order (2026-08-24 新設、公式順の再現) ---

def test_display_order_reflects_list_order(conn, list_articles):
    """
    upsert_from_list_articleにdisplay_orderを渡すと、その値が
    そのままDBに保存されること (公式の並び順を再現するための機能)。
    """
    for i, a in enumerate(list_articles[:5]):
        upsert_from_list_article(conn, a, display_order=i)

    for i, a in enumerate(list_articles[:5]):
        row = conn.execute(
            "SELECT display_order FROM active_articles WHERE article_id = ?",
            (a.article_id,),
        ).fetchone()
        assert row["display_order"] == i


def test_display_order_updated_on_rescan(conn, list_articles):
    """
    既存投稿でも、再度upsertされるたびにdisplay_orderが最新の巡回結果で
    上書きされること (常に「直近の並び順」を反映する設計の確認)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article, display_order=0)

    # 2回目の巡回では別の順位だったとする
    upsert_from_list_article(conn, article, display_order=3)

    row = conn.execute(
        "SELECT display_order FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    ).fetchone()
    assert row["display_order"] == 3


# --- 「終了」タブ再設計 (2026-09-11新設): missing_kind の自動分類 ---


def _missing_kind_of(conn, article_id):
    row = conn.execute(
        "SELECT missing_kind FROM active_articles WHERE article_id = ?", (article_id,)
    ).fetchone()
    return row["missing_kind"] if row else None


def test_mark_missing_classifies_confirmed_closed_when_within_seen_range(conn, list_articles):
    """
    消えた投稿の旧display_orderが、今回の巡回で見えた最大display_order
    以下 (=本来なら見えるはずの順位にいたのに消えた) なら
    'confirmed_closed' に分類されること。
    """
    a, b, c = list_articles[0], list_articles[1], list_articles[2]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=1)  # これが消える想定
    upsert_from_list_article(conn, c, display_order=2)

    # 次回巡回でbだけ見えなくなった。a, cのdisplay_orderの範囲(0, 2)の
    # 内側にbの旧display_order(1)があるため、confirmed_closed候補。
    mark_missing_articles(conn, {a.article_id, c.article_id}, max_seen_display_order=2)

    assert _missing_kind_of(conn, b.article_id) == "confirmed_closed"


def test_mark_missing_classifies_range_uncertain_when_beyond_seen_range(conn, list_articles):
    """
    消えた投稿の旧display_orderが、今回の巡回で見えた最大display_order
    より大きい (=取得範囲の末尾より後ろにいた) 場合は
    'range_uncertain' に分類されること。
    """
    a, b = list_articles[0], list_articles[1]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=10)  # 取得範囲の末尾より後

    # 今回の巡回ではaしか見えず (取得範囲が狭まった想定)、
    # 見えた最大display_orderは0。bの旧display_order(10)はそれより
    # 大きいため、range_uncertain扱いになる。
    mark_missing_articles(conn, {a.article_id}, max_seen_display_order=0)

    assert _missing_kind_of(conn, b.article_id) == "range_uncertain"


def test_mark_missing_without_max_display_order_defaults_to_range_uncertain(conn, list_articles):
    """max_seen_display_orderを渡さない(None)場合、後方互換として全件range_uncertainになること。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article, display_order=0)

    mark_missing_articles(conn, set())

    assert _missing_kind_of(conn, article.article_id) == "range_uncertain"


def test_mark_missing_null_display_order_defaults_to_range_uncertain(conn, list_articles):
    """
    旧display_orderがNULL (display_order導入前の古いデータ等) の場合、
    安全側に倒してrange_uncertainとして扱われること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)  # display_order省略 = NULL

    mark_missing_articles(conn, set(), max_seen_display_order=5)

    assert _missing_kind_of(conn, article.article_id) == "range_uncertain"


def test_get_missing_articles_filters_by_missing_kind(conn, list_articles):
    """get_missing_articles(missing_kind=...)で絞り込めること。"""
    a, b = list_articles[0], list_articles[1]
    upsert_from_list_article(conn, a, display_order=0)
    upsert_from_list_article(conn, b, display_order=1)

    mark_missing_articles(conn, set(), max_seen_display_order=1)  # 両方confirmed_closed候補
    conn.execute(
        "UPDATE active_articles SET missing_kind = 'range_uncertain' WHERE article_id = ?",
        (b.article_id,),
    )

    closed = get_missing_articles(conn, missing_kind="confirmed_closed")
    uncertain = get_missing_articles(conn, missing_kind="range_uncertain")
    assert [r["article_id"] for r in closed] == [a.article_id]
    assert [r["article_id"] for r in uncertain] == [b.article_id]


# --- 「終了」タブ再設計 (2026-09-11新設): 保存期間削除 (purge_expired_articles) ---


def test_purge_expired_articles_deletes_expired_missing(conn, list_articles):
    """missing_since基準で保存期間を過ぎたmissing投稿が削除されること。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())
    conn.execute(
        "UPDATE active_articles SET missing_since = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 1
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is None


def test_purge_expired_articles_keeps_recent_missing(conn, list_articles):
    """保存期間内のmissing投稿は削除されないこと。"""
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    mark_missing_articles(conn, set())  # missing_sinceはたった今

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 0
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None


def test_purge_expired_articles_deletes_expired_active(conn, list_articles):
    """
    2026-09-11新設。last_seen_at基準で保存期間を過ぎたactive投稿も
    削除対象になること (ユーザーとの合意事項: activeも一律対象、
    一覧を溜め込みすぎないためのクリーンアップ目的)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 1
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is None


def test_purge_expired_articles_keeps_recently_seen_active(conn, list_articles):
    """
    巡回のたびにlast_seen_atが更新され続けるactive投稿は、実質
    「最後に確認できてから○日」を超えない限り削除されないこと。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)  # last_seen_atはたった今

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 0


def test_purge_expired_articles_records_history_with_original_status(conn, list_articles):
    """
    削除時のarticle_status_historyに、削除前の実際のステータス
    (active/missing) がfrom_statusとして記録されること。
    """
    active_article, missing_article = list_articles[0], list_articles[1]
    upsert_from_list_article(conn, active_article)
    upsert_from_list_article(conn, missing_article)
    mark_missing_articles(conn, {active_article.article_id})

    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (active_article.article_id,),
    )
    conn.execute(
        "UPDATE active_articles SET missing_since = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (missing_article.article_id,),
    )

    purge_expired_articles(conn, retention_days=7)

    history = {
        row["article_id"]: row["from_status"]
        for row in conn.execute(
            "SELECT article_id, from_status FROM article_status_history "
            "WHERE reason = 'retention_period_expired'"
        ).fetchall()
    }
    assert history[active_article.article_id] == "active"
    assert history[missing_article.article_id] == "missing"


# ---------------------------------------------------------------------
# purge_expired_articles: 監視中の投稿を削除対象から除外
# (2026-09-13新設、ユーザーとの合意事項)
# ---------------------------------------------------------------------


def test_purge_expired_articles_excludes_watched_article(conn, list_articles):
    """
    watched_articles (投稿単位の☆監視) に登録されている投稿は、
    保存期間を過ぎても削除されないこと。

    db/schema.sqlのwatched_articlesテーブルのコメントが明記する
    設計思想 (「物理削除された投稿を後で見返すニーズより、ウォッチ
    解除の意思決定はユーザー自身が行うべき」) との整合性を確認する。
    """
    from repository.watchlist_repository import add_watch

    article = list_articles[0]
    upsert_from_list_article(conn, article)
    add_watch(conn, article.article_id)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 0
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None


def test_purge_expired_articles_excludes_watched_seller_article(conn, list_articles):
    """
    監視ユーザー (seller_rules, rule_type='watch', is_active=1) の
    投稿は、保存期間を過ぎても削除されないこと。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute("INSERT INTO sellers (seller_id) VALUES ('seller-1')")
    conn.execute(
        "UPDATE active_articles SET seller_id = 'seller-1' WHERE article_id = ?",
        (article.article_id,),
    )
    conn.execute(
        "INSERT INTO seller_rules (seller_id, rule_type, is_active) VALUES ('seller-1', 'watch', 1)"
    )
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 0
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is not None


def test_purge_expired_articles_ignores_inactive_watched_seller_rule(conn, list_articles):
    """
    監視ユーザー登録があっても is_active=0 (解除済み) であれば、
    通常通り保存期間削除の対象になること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute("INSERT INTO sellers (seller_id) VALUES ('seller-1')")
    conn.execute(
        "UPDATE active_articles SET seller_id = 'seller-1' WHERE article_id = ?",
        (article.article_id,),
    )
    conn.execute(
        "INSERT INTO seller_rules (seller_id, rule_type, is_active) VALUES ('seller-1', 'watch', 0)"
    )
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 1
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is None


def test_purge_expired_articles_resumes_after_unwatching(conn, list_articles):
    """
    投稿単位の監視(☆)を解除すれば、次回以降の保存期間削除で
    通常通り対象になること (ユーザーが意思を持って解除した時点で
    削除対象に戻る、という設計の確認)。
    """
    from repository.watchlist_repository import add_watch, remove_watch

    article = list_articles[0]
    upsert_from_list_article(conn, article)
    add_watch(conn, article.article_id)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    # 監視中は削除されない
    assert purge_expired_articles(conn, retention_days=7) == 0

    # 監視を解除すれば、次回は通常通り削除される
    remove_watch(conn, article.article_id)
    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 1
    row = conn.execute(
        "SELECT * FROM active_articles WHERE article_id = ?", (article.article_id,)
    ).fetchone()
    assert row is None


def test_purge_expired_articles_excludes_watched_missing_article(conn, list_articles):
    """
    監視中の投稿は、missing (公開終了) 状態になっていても
    保存期間を過ぎて削除されないこと (activeだけでなくmissingでも
    同様に除外されることの確認)。
    """
    from repository.watchlist_repository import add_watch

    article = list_articles[0]
    upsert_from_list_article(conn, article)
    add_watch(conn, article.article_id)
    mark_missing_articles(conn, set())
    conn.execute(
        "UPDATE active_articles SET missing_since = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purged = purge_expired_articles(conn, retention_days=7)

    assert purged == 0


# ---------------------------------------------------------------------
# purge_expired_articles: 削除履歴 (deleted_articles_log)
# (2026-09-14新設、ユーザーとの合意事項)
# ---------------------------------------------------------------------


def test_purge_expired_articles_records_deleted_articles_log(conn, list_articles):
    """
    削除された投稿のタイトル・価格等がdeleted_articles_logに
    スナップショットとして残ること。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    purge_expired_articles(conn, retention_days=7)

    logs = list_deleted_articles(conn)
    assert len(logs) == 1
    assert logs[0]["article_id"] == article.article_id
    assert logs[0]["list_title"] == article.list_title
    assert logs[0]["price"] == article.price
    assert logs[0]["article_status"] == "active"
    assert logs[0]["deleted_at"] is not None


def test_list_deleted_articles_orders_by_deleted_at_desc(conn, list_articles):
    """削除履歴一覧は削除日時の新しい順に返ること。"""
    article1, article2 = list_articles[0], list_articles[1]
    upsert_from_list_article(conn, article1)
    upsert_from_list_article(conn, article2)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article1.article_id,),
    )
    purge_expired_articles(conn, retention_days=7)

    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article2.article_id,),
    )
    purge_expired_articles(conn, retention_days=7)

    logs = list_deleted_articles(conn)
    assert len(logs) == 2
    # 後から削除された article2 が先頭に来ること
    assert logs[0]["article_id"] == article2.article_id
    assert logs[1]["article_id"] == article1.article_id


def test_purge_expired_articles_also_purges_old_deleted_log(conn, list_articles):
    """
    削除履歴自体も、deleted_at基準で保存期間を過ぎたら削除される
    こと (「消したわけではない投稿の履歴に強い興味はない」という
    ユーザーの方針への対応)。
    """
    article = list_articles[0]
    upsert_from_list_article(conn, article)
    conn.execute(
        "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )
    purge_expired_articles(conn, retention_days=7)
    assert len(list_deleted_articles(conn)) == 1

    # 削除履歴自体のdeleted_atを古い日付に書き換え、保存期間切れの
    # 状態を作る。
    conn.execute(
        "UPDATE deleted_articles_log SET deleted_at = datetime('now', '-10 days') "
        "WHERE article_id = ?",
        (article.article_id,),
    )

    # 次回のpurge実行時に、古い削除履歴も一緒に掃除されること。
    purge_expired_articles(conn, retention_days=7)

    assert len(list_deleted_articles(conn)) == 0


def test_list_deleted_articles_respects_limit(conn, list_articles):
    """limit引数で返す件数の上限を制御できること。"""
    for article in list_articles[:3]:
        upsert_from_list_article(conn, article)
        conn.execute(
            "UPDATE active_articles SET last_seen_at = datetime('now', '-10 days') "
            "WHERE article_id = ?",
            (article.article_id,),
        )
        purge_expired_articles(conn, retention_days=7)

    logs = list_deleted_articles(conn, limit=2)
    assert len(logs) == 2
