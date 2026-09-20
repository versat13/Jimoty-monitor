"""
scheduler/scan_state_tracker.py のユニットテスト。

プロセス内グローバルな状態を扱うモジュールのため、各テストの前後で
確実にリセットする (他のテストファイルへ影響を漏らさないため)。
"""

import threading

import pytest

from scheduler.scan_state_tracker import (
    is_cancel_requested,
    is_scanning,
    mark_scan_finished,
    request_cancel,
    try_start_scan,
)


@pytest.fixture(autouse=True)
def _reset():
    mark_scan_finished()
    yield
    mark_scan_finished()


def test_initial_state_is_idle():
    assert is_scanning() is False
    assert is_cancel_requested() is False


def test_try_start_scan_succeeds_when_idle():
    assert try_start_scan() is True
    assert is_scanning() is True


def test_try_start_scan_fails_when_already_scanning():
    assert try_start_scan() is True
    assert try_start_scan() is False  # 2回目は失敗する (多重起動防止)
    assert is_scanning() is True  # 状態は「実行中」のまま変わらない


def test_mark_scan_finished_resets_state():
    try_start_scan()
    request_cancel()
    mark_scan_finished()

    assert is_scanning() is False
    assert is_cancel_requested() is False  # 停止要求もクリアされる


def test_try_start_scan_after_finish_succeeds_again():
    try_start_scan()
    mark_scan_finished()
    assert try_start_scan() is True  # 終了後は再度開始できる


def test_try_start_scan_clears_previous_cancel_request():
    """
    前回の巡回で出された停止要求が、次回開始時まで残っていないこと
    (mark_scan_finished()でクリアされるが、念のため開始時にも
    クリアされることを確認する回帰テスト)。
    """
    try_start_scan()
    request_cancel()
    mark_scan_finished()

    try_start_scan()
    assert is_cancel_requested() is False


def test_request_cancel_returns_false_when_idle():
    assert request_cancel() is False
    assert is_cancel_requested() is False


def test_request_cancel_returns_true_when_scanning():
    try_start_scan()
    assert request_cancel() is True
    assert is_cancel_requested() is True


def test_try_start_scan_is_atomic_under_concurrent_calls():
    """
    複数スレッドから同時にtry_start_scan()を呼んでも、成功するのは
    ちょうど1スレッドだけであること (threading.Lockによる排他制御の
    検証)。TOCTOU競合が残っていると複数スレッドが成功してしまう。
    """
    results = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()  # 全スレッドをできるだけ同時にスタートさせる
        results.append(try_start_scan())

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == 19
