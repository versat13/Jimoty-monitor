"""
repository/scan_settings_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection
from repository.scan_settings_repository import (
    get_last_notified_articles,
    get_monitored_target,
    get_retention_settings,
    get_scan_range_settings,
    update_auto_scan_interval,
    update_last_notified_articles,
    update_monitored_target,
    update_retention_settings,
    update_scan_range_only,
    update_scan_range_settings,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


def test_default_settings_when_no_row(conn):
    """
    2026-09-13変更: auto_scan_interval_minutesのデフォルトをNoneから
    30分に変更 (ユーザーとの合意事項)。
    """
    settings = get_scan_range_settings(conn)
    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 1
    assert settings.auto_scan_interval_minutes == 30


def test_update_creates_row_when_none_exists(conn):
    settings = update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=14)
    assert settings.scan_range_mode == "days"
    assert settings.scan_range_value == 14

    row_count = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"]
    assert row_count == 1


def test_update_reused_existing_row(conn):
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=14)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=3)

    row_count = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"]
    assert row_count == 1  # 2回目の更新で行が増えていないこと

    settings = get_scan_range_settings(conn)
    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 3


def test_update_persists_across_reads(conn):
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=7)
    settings = get_scan_range_settings(conn)
    assert settings.scan_range_mode == "days"
    assert settings.scan_range_value == 7


@pytest.mark.parametrize("mode", ["weeks", "months", "", "PAGES"])
def test_invalid_mode_raises(conn, mode):
    with pytest.raises(ValueError):
        update_scan_range_settings(conn, scan_range_mode=mode, scan_range_value=1)


@pytest.mark.parametrize("value", [0, -1, -100])
def test_invalid_value_raises(conn, value):
    with pytest.raises(ValueError):
        update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=value)


def test_auto_scan_interval_minutes_stored_as_placeholder(conn):
    """
    自動更新頻度は2026-09-07時点では設定項目の器のみ (実際にこの値を
    使ってスケジューラを定期実行する仕組みは未実装)。値の保存・
    読み出し自体はできることだけ確認する。
    """
    settings = update_scan_range_settings(
        conn, scan_range_mode="pages", scan_range_value=1, auto_scan_interval_minutes=30
    )
    assert settings.auto_scan_interval_minutes == 30

    reread = get_scan_range_settings(conn)
    assert reread.auto_scan_interval_minutes == 30


# ---------------------------------------------------------------------
# update_auto_scan_interval (2026-09-08 新設)
#
# 「取得範囲」タブと「自動更新」タブを別々に保存しても互いの値を
# 上書きしないようにするために追加した専用関数。
# ---------------------------------------------------------------------


def test_update_auto_scan_interval_creates_row_when_none_exists(conn):
    settings = update_auto_scan_interval(conn, auto_scan_interval_minutes=20)
    assert settings.auto_scan_interval_minutes == 20
    # 取得範囲側はデフォルト値のまま作成されること
    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 1

    row_count = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"]
    assert row_count == 1


def test_update_auto_scan_interval_does_not_change_scan_range(conn):
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=10)
    settings = update_auto_scan_interval(conn, auto_scan_interval_minutes=5)

    assert settings.scan_range_mode == "days"
    assert settings.scan_range_value == 10
    assert settings.auto_scan_interval_minutes == 5

    row_count = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"]
    assert row_count == 1  # 行が増えていないこと (既存行を更新)


def test_update_scan_range_settings_requires_explicit_auto_interval_to_preserve(conn):
    """
    update_scan_range_settings() は auto_scan_interval_minutes を
    省略するとNoneで上書きしてしまう (デフォルト値がNoneのため)。
    取得範囲のみを更新したい場合は update_scan_range_only() を使う
    べきで、この関数を直接使う場合は呼び出し元が既存値を明示的に
    渡す必要がある、という仕様を記録するテスト。

    2026-09-08: API層 (update_scan_range_settings_endpoint) は既に
    update_scan_range_only() を使うよう修正済みで、この関数
    (update_scan_range_settings) を経由しない。
    """
    update_auto_scan_interval(conn, auto_scan_interval_minutes=25)
    current = get_scan_range_settings(conn)

    settings = update_scan_range_settings(
        conn,
        scan_range_mode="pages",
        scan_range_value=2,
        auto_scan_interval_minutes=current.auto_scan_interval_minutes,
    )

    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 2
    assert settings.auto_scan_interval_minutes == 25


def test_update_scan_range_only_preserves_auto_interval(conn):
    """
    update_scan_range_only() (2026-09-08新設) は
    auto_scan_interval_minutes に一切触れないため、引数を渡さなくても
    既存の自動更新間隔がそのまま保持されること。
    update_scan_range_settings_endpoint はこちらを使っている。
    """
    update_auto_scan_interval(conn, auto_scan_interval_minutes=25)

    settings = update_scan_range_only(conn, scan_range_mode="pages", scan_range_value=2)

    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 2
    assert settings.auto_scan_interval_minutes == 25


@pytest.mark.parametrize("value", [0, -1, -100])
def test_update_auto_scan_interval_invalid_value_raises(conn, value):
    with pytest.raises(ValueError):
        update_auto_scan_interval(conn, auto_scan_interval_minutes=value)


def test_update_auto_scan_interval_none_is_allowed(conn):
    """Noneは「未設定に戻す」という意味で許可される (1未満とは区別)。"""
    update_auto_scan_interval(conn, auto_scan_interval_minutes=10)
    settings = update_auto_scan_interval(conn, auto_scan_interval_minutes=None)
    assert settings.auto_scan_interval_minutes is None


# ---------------------------------------------------------------------
# get_monitored_target (2026-09-09 新設)
# ---------------------------------------------------------------------


def test_get_monitored_target_default_when_no_row(conn):
    """
    scan_state に行が無い場合、trigger_scan() の従来のデフォルト値
    (福岡県北九州市・全カテゴリ) と揃えた暫定値が返ること。
    """
    target = get_monitored_target(conn)
    assert target.prefecture == "fukuoka"
    assert target.category_slug == "sale-all"
    assert target.category_id == "all"
    assert target.area_id == "731"
    assert target.area_name == "kitakyushu"


@pytest.mark.parametrize(
    "make_first_save",
    [
        lambda conn: update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=2),
        lambda conn: update_scan_range_only(conn, scan_range_mode="pages", scan_range_value=2),
        lambda conn: update_auto_scan_interval(conn, auto_scan_interval_minutes=30),
    ],
)
def test_area_defaults_survive_settings_saved_before_first_scan(conn, make_first_save):
    """
    回帰テスト (2026-09-10): 「取得範囲」「自動更新」タブのいずれかを
    一度も巡回していない (=scan_stateに行が無い) 状態で最初に保存すると、
    以前は area_id/area_name が NULL のまま行が作られてしまい、以後
    ずっと市区町村を絞らない都道府県全域が巡回対象になってしまう不具合が
    あった。3つの更新関数のどれを最初に呼んでも、area_id/area_name が
    北九州市のデフォルト値で埋まっていることを確認する。
    """
    make_first_save(conn)

    target = get_monitored_target(conn)
    assert target.area_id == "731"
    assert target.area_name == "kitakyushu"
    assert target.prefecture == "fukuoka"

    row_count = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchone()["c"]
    assert row_count == 1  # get_monitored_targetの呼び出しで行が増えていないこと


def test_get_monitored_target_reads_from_scan_state(conn):
    """
    scan_state に行があれば、その内容 (prefecture/category_slug/
    category_id/area_id/area_name) を正しく返すこと。
    """
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    conn.execute(
        "UPDATE scan_state SET prefecture = ?, category_slug = ?, category_id = ?, "
        "area_id = ?, area_name = ? WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        ("osaka", "sale-fur", "1245", "999", "sample_area"),
    )
    conn.commit()

    target = get_monitored_target(conn)
    assert target.prefecture == "osaka"
    assert target.category_slug == "sale-fur"
    assert target.category_id == "1245"
    assert target.area_id == "999"
    assert target.area_name == "sample_area"


# --- update_monitored_target (2026-09-10新設: 地域選択UI) ---


def test_update_monitored_target_sets_prefecture_and_area(conn):
    """都道府県+市区町村を指定して更新できること。"""
    target = update_monitored_target(
        conn, prefecture="osaka", area_id="999", area_name="sample_area"
    )
    assert target.prefecture == "osaka"
    assert target.area_id == "999"
    assert target.area_name == "sample_area"

    row = conn.execute("SELECT region_type FROM scan_state ORDER BY id LIMIT 1").fetchone()
    assert row["region_type"] == "prefecture_city"


def test_update_monitored_target_prefecture_only(conn):
    """
    area_id/area_nameを省略すると「都道府県のみ監視」(市区町村を絞らない)
    になり、region_typeが'prefecture'になること。
    """
    target = update_monitored_target(conn, prefecture="osaka", area_id=None, area_name=None)
    assert target.prefecture == "osaka"
    assert target.area_id is None
    assert target.area_name is None

    row = conn.execute("SELECT region_type FROM scan_state ORDER BY id LIMIT 1").fetchone()
    assert row["region_type"] == "prefecture"


def test_update_monitored_target_does_not_touch_category(conn):
    """
    カテゴリ設定 (category_slug/category_id) には一切触れないこと
    (取得範囲・自動更新間隔と同様、他の設定タブの値を上書きしない設計)。
    """
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=3)
    conn.execute(
        "UPDATE scan_state SET category_slug = 'sale-fur', category_id = '1245' "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)"
    )
    conn.commit()

    update_monitored_target(conn, prefecture="osaka", area_id="999", area_name="sample_area")

    target = get_monitored_target(conn)
    assert target.category_slug == "sale-fur"
    assert target.category_id == "1245"

    settings = get_scan_range_settings(conn)
    assert settings.scan_range_value == 3  # 取得範囲も変わっていないこと


def test_update_monitored_target_rejects_empty_prefecture(conn):
    with pytest.raises(ValueError):
        update_monitored_target(conn, prefecture="", area_id=None, area_name=None)


def test_update_monitored_target_rejects_partial_area(conn):
    """area_id/area_nameは両方指定するか両方省略するかのどちらかであること。"""
    with pytest.raises(ValueError):
        update_monitored_target(conn, prefecture="osaka", area_id="999", area_name=None)

    with pytest.raises(ValueError):
        update_monitored_target(conn, prefecture="osaka", area_id=None, area_name="sample_area")


def test_update_monitored_target_creates_row_with_defaults_when_none_exists(conn):
    """
    scan_stateにまだ行が無い状態から呼んでも、他のデフォルト値
    (取得範囲・カテゴリ) が_ensure_scan_state_rowの北九州デフォルトで
    正しく初期化されること (2026-09-10のバグ修正の回帰確認を兼ねる)。
    """
    update_monitored_target(conn, prefecture="osaka", area_id="999", area_name="sample_area")

    settings = get_scan_range_settings(conn)
    assert settings.scan_range_mode == "pages"
    assert settings.scan_range_value == 1

    target = get_monitored_target(conn)
    assert target.category_slug == "sale-all"


# --- 保存期間削除設定 (2026-09-11新設) ---


def test_retention_settings_default_when_no_row(conn):
    """scan_stateに行が無い場合、デフォルト値(有効・7日)を返すこと。"""
    settings = get_retention_settings(conn)
    assert settings.enabled is True
    assert settings.retention_days == 7


def test_update_retention_settings(conn):
    settings = update_retention_settings(conn, enabled=False, retention_days=14)
    assert settings.enabled is False
    assert settings.retention_days == 14

    reread = get_retention_settings(conn)
    assert reread.enabled is False
    assert reread.retention_days == 14


def test_update_retention_settings_rejects_zero_days(conn):
    with pytest.raises(ValueError):
        update_retention_settings(conn, enabled=True, retention_days=0)


def test_update_retention_settings_does_not_touch_scan_range(conn):
    """
    保存期間設定の更新が、既に設定済みの取得範囲・地域を変化させない
    こと (他の設定タブとの独立性を確認する)。
    """
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=5)
    update_monitored_target(conn, prefecture="osaka", area_id="999", area_name="sample_area")

    update_retention_settings(conn, enabled=True, retention_days=3)

    range_settings = get_scan_range_settings(conn)
    assert range_settings.scan_range_mode == "days"
    assert range_settings.scan_range_value == 5

    target = get_monitored_target(conn)
    assert target.prefecture == "osaka"


def test_update_retention_settings_creates_row_with_defaults_when_none_exists(conn):
    """scan_stateにまだ行が無い状態から呼んでも、北九州デフォルトで初期化されること。"""
    update_retention_settings(conn, enabled=True, retention_days=3)

    target = get_monitored_target(conn)
    assert target.prefecture == "fukuoka"
    assert target.area_id == "731"


def test_get_last_notified_articles_default_empty(conn):
    """
    2026-09-15新設。scan_stateにまだ行が無い状態から呼んでも、
    空リスト・Noneを返すこと (通知機能を使っていない大多数の
    ユーザーに影響を出さないための安全なデフォルト)。
    """
    result = get_last_notified_articles(conn)
    assert result.article_ids == []
    assert result.notified_at is None


def test_update_and_get_last_notified_articles(conn):
    """
    2026-09-15新設。update_last_notified_articles()で保存した
    article_id一覧が、get_last_notified_articles()でそのまま
    (順序も含め) 取得できること。"""
    update_last_notified_articles(conn, ["id3", "id1", "id2"])
    result = get_last_notified_articles(conn)
    assert result.article_ids == ["id3", "id1", "id2"]
    assert result.notified_at is not None


def test_update_last_notified_articles_washes_out_previous_result(conn):
    """
    2026-09-15新設。前回の巡回結果が残ったままにならないよう、
    毎回の呼び出しで洗い替え (上書き) されること。対象0件の巡回が
    続いた場合に古い通知対象がいつまでも残り続けるバグを防ぐための
    挙動確認。
    """
    update_last_notified_articles(conn, ["id1", "id2"])
    update_last_notified_articles(conn, [])

    result = get_last_notified_articles(conn)
    assert result.article_ids == []


def test_update_last_notified_articles_creates_row_with_defaults_when_none_exists(conn):
    """scan_stateにまだ行が無い状態から呼んでも、北九州デフォルトで初期化されること。"""
    update_last_notified_articles(conn, ["id1"])

    target = get_monitored_target(conn)
    assert target.prefecture == "fukuoka"
    assert target.area_id == "731"


def test_update_last_notified_articles_does_not_touch_scan_range(conn):
    """
    通知対象の更新が、既に設定済みの取得範囲・地域を変化させないこと
    (他の設定タブとの独立性を確認する。test_update_retention_settings_
    does_not_touch_scan_rangeと同じ観点のテスト)。
    """
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=5)
    update_monitored_target(conn, prefecture="osaka", area_id="999", area_name="sample_area")

    update_last_notified_articles(conn, ["id1"])

    range_settings = get_scan_range_settings(conn)
    assert range_settings.scan_range_mode == "days"
    assert range_settings.scan_range_value == 5

    target = get_monitored_target(conn)
    assert target.prefecture == "osaka"


def test_get_last_notified_articles_ignores_malformed_json(conn):
    """
    2026-09-15新設。last_notified_article_ids列に不正なJSON (手動での
    DB操作やマイグレーション不整合等を想定) が入っていても例外を
    発生させず、空リストとして扱うこと (通知機能の不具合が巡回本体や
    他のAPIレスポンスに波及しないための安全策)。
    """
    from repository.scan_settings_repository import _ensure_scan_state_row

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET last_notified_article_ids = ? WHERE id = ?",
        ("{not valid json", row_id),
    )
    conn.commit()

    result = get_last_notified_articles(conn)
    assert result.article_ids == []
