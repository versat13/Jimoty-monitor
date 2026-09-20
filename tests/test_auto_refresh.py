"""
scheduler/auto_refresh.py のユニットテスト。

実HTTPアクセスができない環境のため、scraper.fetch.fetch_html を
モック化する (tests/test_scheduler_job.py と同じ方針)。
"""

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from repository.article_repository import get_connection
from repository.scan_settings_repository import update_auto_scan_interval, update_scan_range_settings
from scheduler.auto_refresh import _check_and_run_if_due, is_likely_sleep_resume

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_path():
    """テスト用の一時DBファイルパス。auto_refresh側は毎回DB接続を
    作り直す実装のため (get_connection(db_path))、":memory:"ではなく
    実ファイルを使う必要がある。"""
    path = tempfile.mktemp(suffix=".db")
    conn = get_connection(path)
    conn.close()
    return path


@pytest.fixture
def list_html():
    return (FIXTURES / "list_real.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html():
    return (FIXTURES / "detail_real.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_scan_state_tracker():
    """
    2026-09-10新設。scheduler.scan_state_tracker はプロセス内グローバル
    な状態を持つため、テスト間でリークしないよう前後で強制リセットする
    (tests/test_api.py の同名fixtureと同じ理由)。
    """
    from scheduler.scan_state_tracker import mark_scan_finished

    mark_scan_finished()
    yield
    mark_scan_finished()


def test_runs_scan_with_default_interval_when_row_does_not_exist(db_path, list_html, detail_html):
    """
    2026-09-13変更: 以前はscan_stateに行が無い(auto_scan_interval_
    minutesが実質NULL)場合、自動更新は「未設定」として何もしなかった。
    auto_scan_interval_minutesのデフォルト値を30分に変更した
    (ユーザーとの合意事項) ことに伴い、行が無い場合は
    get_scan_range_settings()がデフォルト値(30分)を返すようになり、
    このケースでも自動更新が実行されるようになった。
    """
    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_called()


def test_does_nothing_when_auto_interval_explicitly_disabled(db_path):
    """
    auto_scan_interval_minutesが明示的にNULL (ユーザーが設定画面で
    空欄にして保存した状態) なら何も実行しないこと。

    2026-09-13変更: デフォルト値が30分になったことに伴い、
    「未設定」を検証するには行を明示的に作成しauto_scan_interval_
    minutes=NULLを指定する必要がある (行が存在しない場合は
    get_scan_range_settings()がデフォルト値30を返すため、このテストの
    意図する状況にならない)。
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=None)
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_not_called()


def test_runs_scan_when_never_scanned_before(db_path, list_html, detail_html):
    """
    auto_scan_interval_minutesが設定済みで、まだ一度も巡回していない
    (last_scanned_atがNULL) 場合は、即座に巡回を実行すること。
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_called()

    conn = get_connection(db_path)
    row = conn.execute("SELECT last_scanned_at FROM scan_state").fetchone()
    conn.close()
    assert row["last_scanned_at"] is not None


def test_does_not_run_when_interval_not_elapsed(db_path, list_html):
    """
    前回巡回からまだauto_scan_interval_minutes分経過していない場合は
    実行しないこと。
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    # 5分前に巡回済み、という状態を作る (UTC、DBの保存形式に合わせる)。
    recent = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE scan_state SET last_scanned_at = ? "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        (recent,),
    )
    conn.commit()
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_not_called()


def test_runs_when_interval_elapsed(db_path, list_html, detail_html):
    """
    前回巡回からauto_scan_interval_minutes分以上経過していれば
    実行すること。
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    # 40分前に巡回済み (間隔30分を超えている)。
    old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE scan_state SET last_scanned_at = ? "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        (old,),
    )
    conn.commit()
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_called()


def test_runs_after_long_gap_simulating_sleep_resume(db_path, list_html, detail_html):
    """
    2026-09-12新設。PCがスリープ状態から復帰した場合を想定した回帰
    テスト。前回巡回から長時間 (12時間、通常の巡回間隔よりずっと長い)
    が経過していても、判定ロジックは実時刻 (datetime.now(timezone.utc))
    ベースで「前回実行からの経過時間」を計算するため、スリープ中に
    チェックループ (asyncio.sleep) 自体が進んでいなかったとしても、
    復帰後最初のチェックで正しく「更新のタイミングを逃していた」と
    判定し、巡回を実行できること。

    (このテストが検証しているのは「経過時間の判定ロジックが実時刻
    ベースであること」自体であり、OSのスリープ動作そのものは
    シミュレートできないため、"長時間経過後のlast_scanned_at" という
    形で状況を再現している。)
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE scan_state SET last_scanned_at = ? "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        (old,),
    )
    conn.commit()
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.side_effect = [list_html] + [detail_html] * 100
        asyncio.run(_check_and_run_if_due(db_path))

    mock_fetch.assert_called()


def test_uses_monitored_target_from_db(db_path, list_html):
    """
    自動更新が実際にscan_stateに保存された監視対象(地域・カテゴリ)を
    使って巡回すること (ハードコードされたデフォルト値ではなく)。
    """
    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    conn.execute(
        "UPDATE scan_state SET prefecture = 'osaka', category_slug = 'sale-fur' "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)"
    )
    conn.commit()
    conn.close()

    with patch("scheduler.scan_runner.fetch_html") as mock_fetch, \
         patch("scheduler.scan_runner.polite_sleep"):
        mock_fetch.return_value = list_html
        asyncio.run(_check_and_run_if_due(db_path))

    called_url = mock_fetch.call_args_list[0].args[1]
    assert "osaka" in called_url
    assert "sale-fur" in called_url


# --- 多重起動防止 (2026-09-10新設) ---


def test_skips_when_manual_scan_already_running(db_path, list_html):
    """
    2026-09-10新設。手動更新 (scan_state_tracker.try_start_scan()) が
    既に実行中の状態で自動更新のタイミングが来ても、巡回を開始せず
    スキップすること (多重起動防止)。
    """
    from scheduler.scan_state_tracker import mark_scan_finished, try_start_scan

    conn = get_connection(db_path)
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)
    conn.close()

    assert try_start_scan() is True  # 手動更新が実行中、という状況を模する
    try:
        with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
            asyncio.run(_check_and_run_if_due(db_path))
        mock_fetch.assert_not_called()
    finally:
        mark_scan_finished()


def test_run_scan_sync_noop_when_scan_starts_between_check_and_run(db_path, list_html):
    """
    2026-09-10新設。_check_and_run_if_due()の事前チェック通過後、実際に
    _run_scan_sync()が動く直前に手動更新が割り込んだ場合でも、
    try_start_scan()のアトミックな判定により二重に巡回が実行されない
    ことを確認する (TOCTOU競合対策の回帰テスト)。
    """
    from scheduler.auto_refresh import _run_scan_sync
    from scheduler.scan_state_tracker import mark_scan_finished, try_start_scan

    conn = get_connection(db_path)
    range_settings = update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)
    from repository.scan_settings_repository import get_monitored_target

    target = get_monitored_target(conn)
    conn.close()

    assert try_start_scan() is True  # ここで手動更新が割り込んだ状況を模する
    try:
        with patch("scheduler.scan_runner.fetch_html") as mock_fetch:
            _run_scan_sync(db_path, target, range_settings)
        mock_fetch.assert_not_called()  # 割り込みのため巡回は実行されない
    finally:
        mark_scan_finished()


# --- スリープ復帰検知 (2026-09-12新設) ---


def test_is_likely_sleep_resume_false_for_normal_interval():
    """通常のチェック間隔 (30秒) 程度ならスリープ復帰とみなさないこと。"""
    assert is_likely_sleep_resume(30) is False
    assert is_likely_sleep_resume(35) is False  # 多少の誤差は許容範囲


def test_is_likely_sleep_resume_true_for_long_gap():
    """
    想定チェック間隔の3倍を大きく超える遅れ (PCのスリープ復帰等) は
    検知されること。
    """
    assert is_likely_sleep_resume(300) is True  # 5分
    assert is_likely_sleep_resume(43200) is True  # 12時間相当
