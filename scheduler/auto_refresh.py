"""
自動更新のサーバー側定期実行 (2026-09-09 新設)。

設定画面の「自動更新」タブで指定した分数 (auto_scan_interval_minutes)
ごとに、run_scan_with_range() を自動的に実行する。ブラウザを閉じていて
もサーバープロセス (uvicorn) が起動している限り動作する
(ユーザー方針: 「サーバー側定期実行」)。

=== 設計方針 ===

外部スケジューラライブラリ (APScheduler等) を追加せず、標準ライブラリの
asyncio だけで実装する。理由:
  - このツールはローカル常駐のシングルユーザー向けであり、複数プロセス
    間での分散実行やcronライクな複雑なスケジュール指定は不要。
  - 「n分ごとに1回実行する」という単純な要件に対して外部ライブラリの
    機能はほとんど使わず、依存を増やすデメリットの方が大きい。

ループの動作:
  1. 起動時 (FastAPIのlifespanイベント) に無限ループのバックグラウンド
     タスクを1つ開始する。
  2. ループは _CHECK_INTERVAL_SECONDS おきに一度、DBから
     auto_scan_interval_minutes と last_scanned_at を読み、
     「前回実行からその分数以上経過したか」を判定する。
  3. 経過していれば1回だけ巡回を実行する (run_scan_with_range)。
     実行後、last_scanned_at が更新されるため、次のチェックでは
     再度その時点からの経過時間で判定される。
  4. auto_scan_interval_minutes が未設定 (None) の場合は何もしない
     (自動更新は無効)。

チェック間隔 (_CHECK_INTERVAL_SECONDS) を実際の巡回間隔
(auto_scan_interval_minutes、分単位) より短くすることで、指定分数から
大きくズレずに実行できる。ズレの最大値は _CHECK_INTERVAL_SECONDS
未満に収まる。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from repository.article_repository import get_connection
from repository.scan_settings_repository import (
    clear_scan_progress,
    get_monitored_target,
    get_scan_range_settings,
)
from scraper.fetch import build_client
from scheduler.job import run_scan_with_range
from scheduler.scan_state_tracker import is_scanning, mark_scan_finished, try_start_scan

logger = logging.getLogger(__name__)

# ループが「前回実行から何分経過したか」を確認する頻度。
# auto_scan_interval_minutesの最小単位である「1分」より短くし、
# 指定した分数からのズレを抑える。
_CHECK_INTERVAL_SECONDS = 30


def is_likely_sleep_resume(seconds_since_last_tick: float) -> bool:
    """
    2026-09-12新設。ループの前回イテレーションから今回までの実測秒数
    (time.monotonic()の差分) を受け取り、「PCがスリープしていた
    可能性が高いか」を判定する。

    想定チェック間隔 (_CHECK_INTERVAL_SECONDS) の3倍以上遅れていれば
    スリープ復帰とみなす。3倍としているのは、GC一時停止やOSの一時的な
    スケジューリング遅延等による誤検知を避けるための余裕。

    この判定はログ出力のためだけに使われ、実際の「更新タイミングを
    逃していないか」の判定自体 (auto_refresh._check_and_run_if_due)
    には影響しない (そちらは実時刻ベースで独立して正しく判定できる
    設計のため)。
    """
    return seconds_since_last_tick > _CHECK_INTERVAL_SECONDS * 3


async def auto_refresh_loop(db_path: str) -> None:
    """
    FastAPIのlifespanイベントから起動される無限ループ。
    アプリケーション終了時 (asyncio.CancelledError) で正常終了する。

    2026-09-12追加: PCがスリープ状態から復帰した場合の対応。
    _check_and_run_if_due() 自体は「前回巡回からの経過時間」を実時刻
    (datetime.now(timezone.utc)) で判定しているため、スリープ中に
    このループ (asyncio.sleep) が進んでいなかったとしても、復帰後
    最初のチェックで「更新のタイミングを逃していた」ことを正しく
    検知し、巡回を実行できる設計になっている
    (tests/test_auto_refresh.py の
    test_runs_after_long_gap_simulating_sleep_resume 参照)。

    このループ自身では、time.monotonic() (OSがスリープしている間は
    進まない単調増加時計) を使って「本来 _CHECK_INTERVAL_SECONDS
    ごとに来るはずのチェックが、実際には何秒後に来たか」を測定し、
    is_likely_sleep_resume() で大幅な遅れを検知したらログに残す
    (動作の可視化・トラブルシュート用。判定ロジック自体の正しさは
    上記の通りタイマーの遅れに依存しないため、このログが無くても
    機能は正しく動く)。
    """
    import time

    logger.info("自動更新の定期実行ループを開始しました (チェック間隔: %d秒)", _CHECK_INTERVAL_SECONDS)
    last_tick = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            elapsed = now - last_tick
            if is_likely_sleep_resume(elapsed):
                logger.info(
                    "自動更新: 前回のチェックから%.0f秒経過していました "
                    "(PCのスリープ復帰等が考えられます)。更新タイミングを "
                    "逃していないか確認します。",
                    elapsed,
                )
            last_tick = now

            try:
                await _check_and_run_if_due(db_path)
            except Exception:
                # 1回のチェック/実行が失敗しても、ループ自体は継続する
                # (一時的なネットワーク不調等で自動更新が完全に停止して
                # しまうのを避けるため)。
                logger.exception("自動更新のチェック処理中にエラーが発生しました")
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("自動更新の定期実行ループを終了します")
        raise


async def _check_and_run_if_due(db_path: str) -> None:
    """
    DBを見て、自動更新の実行タイミングが来ていれば1回巡回する。

    同期的なDB操作・巡回処理 (httpx含む) をブロッキングせずに実行する
    ため、asyncio.to_thread() でワーカースレッドに委譲する
    (scheduler.job.run_scan_with_range自体は同期関数であり、
    async化していないため)。

    2026-09-10追加: 手動更新 (「今すぐ更新」ボタン) が既に実行中の
    場合はこの回の自動更新をスキップする (多重起動防止。
    scheduler.scan_state_tracker 参照)。次のチェック
    (_CHECK_INTERVAL_SECONDS後) で改めて判定されるため、自動更新が
    完全に止まるわけではない。
    """
    if is_scanning():
        logger.info("自動更新: 既に巡回中 (手動更新等) のため、今回はスキップします")
        return

    conn = get_connection(db_path)
    try:
        range_settings = get_scan_range_settings(conn)
        interval_minutes = range_settings.auto_scan_interval_minutes
        if interval_minutes is None:
            return  # 自動更新は未設定 (無効)

        row = conn.execute(
            "SELECT last_scanned_at FROM scan_state ORDER BY id LIMIT 1"
        ).fetchone()
        last_scanned_at = row["last_scanned_at"] if row is not None else None

        if last_scanned_at is not None:
            last_dt = datetime.fromisoformat(last_scanned_at)
            # 2026-09-09: scan_state.last_scanned_at はSQLiteの
            # datetime('now') (UTC) で保存されている
            # (repository.article_repository の他のタイムスタンプ列と
            # 同じ方式)。ローカル時刻のdatetime.now()と直接比較すると
            # タイムゾーン分のズレが誤差として乗ってしまうため、
            # 同じUTCで比較する。
            elapsed = datetime.now(timezone.utc).replace(tzinfo=None) - last_dt
            if elapsed < timedelta(minutes=interval_minutes):
                return  # まだ間隔に達していない

        target = get_monitored_target(conn)
    finally:
        conn.close()

    logger.info("自動更新: 巡回を実行します (間隔=%s分)", interval_minutes)
    await asyncio.to_thread(_run_scan_sync, db_path, target, range_settings)


def _run_scan_sync(db_path: str, target, range_settings) -> None:
    """
    実際の巡回処理 (同期)。asyncio.to_thread() から呼ばれる。

    trigger_scan() エンドポイント (api/main.py) とほぼ同じ処理内容だが、
    そちらはHTTPリクエストごとにDB接続・httpxクライアントを作るのに
    対し、こちらはバックグラウンドループから直接呼ぶための薄い
    ラッパーとして分離している。

    2026-09-10追加: scheduler.scan_state_tracker のフラグを
    trigger_scan() と同様に立てる。これにより、UIの更新インジケーター
    (GET /api/scan-status) は手動・自動どちらの巡回中でも「更新中」を
    検知でき、また緊急停止 (POST /api/scan/cancel) も手動・自動を
    区別せず効く。

    try_start_scan() は、_check_and_run_if_due() での事前チェックと
    このワーカースレッドでの実行開始の間に手動更新が割り込んだ場合の
    最終防波堤でもある (アトミックな判定のため、ここで多重起動を
    確実に防げる)。既に他の巡回が実行中だった場合は何もせず終了する。
    """
    if not try_start_scan():
        logger.info("自動更新: 実行直前に他の巡回が開始されたため、今回はスキップします")
        return

    conn = get_connection(db_path)
    try:
        with build_client() as client:
            result = run_scan_with_range(
                conn, client,
                prefecture=target.prefecture, category_slug=target.category_slug,
                category_id=target.category_id, area_id=target.area_id,
                area_name=target.area_name,
                scan_range_mode=range_settings.scan_range_mode,
                scan_range_value=range_settings.scan_range_value,
            )
        logger.info(
            "自動更新: 巡回が完了しました (%d件確認, 新規%d件, 通知%d件%s)",
            result.total_seen, result.new_articles, len(result.notified),
            ", 緊急停止により途中終了" if result.cancelled else "",
        )
    finally:
        # 2026-09-10追加: run_scan_with_range()自体も正常系・緊急停止
        # いずれのパスでも進捗をクリアするが、ネットワークエラー等で
        # 例外が起きた場合はそこまで到達しない。ここで確実にクリアする
        # (api.main.trigger_scan() と同じ安全策)。
        try:
            clear_scan_progress(conn)
        except Exception:
            logger.warning("巡回進捗のクリアに失敗しました", exc_info=True)
        conn.close()
        mark_scan_finished()
