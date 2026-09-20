"""
巡回処理の実行状態 (「今スキャン中か」「緊急停止が要求されたか」) を
プロセス内で共有管理する (2026-09-10新設)。

=== 背景 ===

自動更新 (サーバー側定期実行) の追加により、巡回処理が
「手動更新ボタン」からだけでなく、バックグラウンドループからも
開始されるようになった。これに伴い、以下の要望が出てきた:

  - 手動・自動を問わず、今まさに巡回中かどうかをUIに表示したい
    (BottomNav付近のインジケーター表示・アニメーション用)。
  - 手動・自動を問わず、実行中の巡回を緊急停止できるようにしたい。
  - 手動更新と自動更新が同時に走って二重に巡回してしまわないように
    したい (多重起動防止)。

trigger_scan() エンドポイント (api/main.py, リクエストのたびに別
スレッドで実行される) と auto_refresh_loop() (asyncio.to_thread() で
別スレッド実行される) の両方から共通して参照・更新できる必要が
あるため、プロセス内グローバルな状態として実装する (このアプリは
ローカル常駐のシングルユーザー向けであり、複数プロセスに分散する
ことは想定していないため、DBを介さない軽量なインメモリ共有で
十分と判断した)。

=== 排他制御について ===

「既にスキャン中かどうかを確認してから開始する」という判定は、
チェックと更新の間に別スレッドが割り込む競合 (TOCTOU) を避けるため、
try_start_scan() 1関数でアトミックに行う (threading.Lockで保護)。
手動更新ボタンの連打や、手動更新と自動更新のタイミングが偶然重なった
場合でも、どちらか一方だけが実際に巡回を開始する。

=== 停止の粒度について ===

「緊急停止」は、実行中の1ページ分の処理 (_scan_one_page) が完了した
直後、次のページへ進む前のタイミングでのみ効果を持つ (ページの
途中で処理を打ち切ることはしない)。これは:
  - HTTPリクエストの送信中や、DBへのINSERT/UPDATEの最中に処理を
    中断すると、中途半端な状態でデータが残るリスクがあるため。
  - scheduler.job.run_scan_with_range() が2026-09-10のトランザクション
    分割によりページ単位でcommitするようになったため、ページの
    境界で止めればDBの一貫性を保ったまま安全に停止できるため。
このため、停止要求を出してから実際に停止するまで、ページ1枚分の
取得・処理時間 (数秒程度) のタイムラグがあることを利用側は前提とする。
"""

import threading

_lock = threading.Lock()

# 2026-09-10新設: 現在スキャン中かどうか。try_start_scan()で開始
# (True化) し、mark_scan_finished()で終了 (正常終了・エラー・
# キャンセルいずれでも) を反映する。GET /api/scan-status がこれを
# 参照してUIへ伝える。
_is_scanning = False

# 2026-09-10新設: 緊急停止が要求されているかどうか。UIからの
# POST /api/scan/cancel でセットされ、run_scan_with_range()のページ
# ループがこれを見て次のページに進まず打ち切る。1回の停止要求は
# 巡回が終了 (または次に開始) した時点でクリアする。
_cancel_requested = False


def try_start_scan() -> bool:
    """
    巡回を開始できるかどうかをアトミックに判定し、開始できるなら
    実行中フラグを立てる (前回分の停止要求もクリアする)。

    Returns:
        True: 開始できた (呼び出し元は巡回を実行してよい)。
        False: 既に他の巡回が実行中 (呼び出し元は巡回を実行せず、
            多重起動として扱うこと)。
    """
    global _is_scanning, _cancel_requested
    with _lock:
        if _is_scanning:
            return False
        _is_scanning = True
        _cancel_requested = False
        return True


def mark_scan_finished() -> None:
    """巡回終了時 (正常終了・エラー・キャンセルいずれでも) に呼ぶ。"""
    global _is_scanning, _cancel_requested
    with _lock:
        _is_scanning = False
        _cancel_requested = False


def is_scanning() -> bool:
    """現在巡回中かどうかを返す (GET /api/scan-status 用)。"""
    with _lock:
        return _is_scanning


def request_cancel() -> bool:
    """
    緊急停止を要求する。

    Returns:
        True: 実行中の巡回に停止要求を伝えた。
        False: そもそも巡回中ではなかった (要求は無視される)。
    """
    global _cancel_requested
    with _lock:
        if not _is_scanning:
            return False
        _cancel_requested = True
        return True


def is_cancel_requested() -> bool:
    """run_scan_with_range()のページループが、次ページに進む前に確認する。"""
    with _lock:
        return _cancel_requested
