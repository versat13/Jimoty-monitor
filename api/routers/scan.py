"""
巡回実行（「今すぐ更新」ボタン等）に関するエンドポイント
(api/main.py から分割、2026-09-13)。
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter(tags=["scan"])


class ScanTriggerOut(BaseModel):
    total_seen: int
    new_articles: int
    price_changed: int
    newly_missing: int
    notified_count: int
    title_changed: int = 0  # 2026-09-07 追加
    cancelled: bool = False  # 2026-09-10追加: 緊急停止により途中で打ち切られたか


class NotifiedArticleOut(BaseModel):
    """
    トースト通知・ブラウザ通知1件分の簡易情報 (2026-09-15新設)。
    ArticleOut (api/schemas.py) は列数が多く通知表示には過剰なため、
    Discord Embed (notifications/discord_notifier.py の
    build_article_embed) と同じ項目セットに絞った軽量版として
    別途定義する。
    """

    article_id: str
    list_title: str
    price: int | None
    url: str
    thumbnail_url: str | None
    area_name: str | None


class ScanStatusOut(BaseModel):
    """
    GET /api/scan-status のレスポンス。
    2026-09-10新設: 手動・自動を問わず「今スキャン中か」「前回いつ
    完了したか」「次回自動更新はいつ頃か」をUIに伝えるための状態API。
    BottomNav付近の更新インジケーター・前回/次回更新表示がこれを
    ポーリングして参照する想定。
    """

    is_scanning: bool
    last_scanned_at: str | None
    auto_scan_interval_minutes: int | None
    # 2026-09-10: 自動更新が有効な場合のみ、last_scanned_at +
    # auto_scan_interval_minutes から算出したおおよその次回実行予定時刻
    # (UTC、datetime('now')基準の他タイムスタンプ列と同じ形式)。
    # 実際の実行はscheduler.auto_refresh._CHECK_INTERVAL_SECONDS
    # (30秒) 間隔のポーリングで行われるため、多少前後しうる参考値。
    next_scan_estimated_at: str | None
    # 2026-09-10追加: 巡回中の進捗表示用 (BottomNav付近のUI)。
    # is_scanning=Falseのときは全てNoneになる。progress_max_pageは
    # 取得範囲が'pages'モードのときのみ値を持つ ('days'モードは
    # 事前に何ページで終わるか分からないため常にNone。UI側は上限不明
    # の表示にする)。
    progress_current_page: int | None
    progress_max_page: int | None
    progress_seen_count: int | None
    # 2026-09-15追加: トースト通知・ブラウザ通知向け。直近の巡回で
    # 「検索」タブ (pickup_search) の条件にヒットした新規投稿の簡易
    # 情報一覧 (Discord Embedと同じ項目セット)。対象が無ければ空配列。
    # notified_atは、この一覧がいつの巡回結果かを示す (scan_stateの
    # last_notified_atをそのまま返す)。フロント (ScanStatusContext) は
    # notified_atが前回ポーリング時から変化した場合のみ、articlesを
    # 新規の通知対象として扱う (変化していなければ同じ内容を再度
    # 通知しない)。手動更新・自動更新のどちらの巡回結果もここに反映
    # される (scheduler.scan_runner.run_scan_with_range が巡回完了の
    # たびにscan_stateへ書き込むため)。
    notified_articles: list[NotifiedArticleOut]
    notified_at: str | None


@router.get("/api/scan-status", response_model=ScanStatusOut)
def get_scan_status():
    """
    現在の巡回状態を返す (2026-09-10新設)。

    ブラウザは一覧・設定どちらの画面にいてもこのエンドポイントを
    定期的にポーリングすることで、手動更新・自動更新のどちらが
    実行中でもインジケーターに反映できる (ページ遷移やブラウザの
    リロードを挟んでも、この関数はサーバー側の実行状態をそのまま
    返すだけなので状態が失われない)。

    2026-09-15追加: トースト通知・ブラウザ通知向けに、直近の巡回で
    「検索」タブ条件にヒットした新規投稿の簡易情報も併せて返す
    (notified_articles / notified_at)。詳細はScanStatusOutの
    コメント参照。
    """
    from datetime import datetime, timedelta

    from repository.scan_settings_repository import (
        get_last_notified_articles,
        get_scan_progress,
        get_scan_range_settings,
    )
    from scheduler.scan_state_tracker import is_scanning

    conn = get_db()
    range_settings = get_scan_range_settings(conn)
    scan_state_row = conn.execute(
        "SELECT last_scanned_at FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    progress = get_scan_progress(conn)

    # 2026-09-15追加: 通知対象の投稿情報を取得する。last_notified_articles
    # のarticle_id一覧はDiscordへの通知試行対象と同じ集合 (対象0件の
    # 巡回後は空リストになる)。article_idsが空ならDBへの追加クエリを
    # 省略する (通知機能を使っていない大多数のユーザーへの負荷を
    # 避けるため)。
    last_notified = get_last_notified_articles(conn)
    notified_articles: list[NotifiedArticleOut] = []
    if last_notified.article_ids:
        placeholders = ",".join("?" for _ in last_notified.article_ids)
        article_rows = conn.execute(
            f"SELECT article_id, list_title, price, url, thumbnail_url, area_name "
            f"FROM active_articles WHERE article_id IN ({placeholders})",
            last_notified.article_ids,
        ).fetchall()
        # 2026-09-15: article_idsの並び順 (巡回で見つかった順) を保つため、
        # SQLクエリ結果を辞書化してから元の順序で並べ直す。IN句の結果は
        # 順序が保証されないため。
        rows_by_id = {article_row["article_id"]: article_row for article_row in article_rows}
        notified_articles = [
            NotifiedArticleOut(
                article_id=article_row["article_id"],
                list_title=article_row["list_title"],
                price=article_row["price"],
                url=article_row["url"],
                thumbnail_url=article_row["thumbnail_url"],
                area_name=article_row["area_name"],
            )
            for article_id in last_notified.article_ids
            if (article_row := rows_by_id.get(article_id)) is not None
        ]

    conn.close()

    last_scanned_at = scan_state_row["last_scanned_at"] if scan_state_row is not None else None

    next_scan_estimated_at = None
    if last_scanned_at is not None and range_settings.auto_scan_interval_minutes is not None:
        last_dt = datetime.fromisoformat(last_scanned_at)
        next_dt = last_dt + timedelta(minutes=range_settings.auto_scan_interval_minutes)
        next_scan_estimated_at = next_dt.isoformat(sep=" ")

    return ScanStatusOut(
        is_scanning=is_scanning(),
        last_scanned_at=last_scanned_at,
        auto_scan_interval_minutes=range_settings.auto_scan_interval_minutes,
        next_scan_estimated_at=next_scan_estimated_at,
        progress_current_page=progress.current_page,
        progress_max_page=progress.max_page,
        progress_seen_count=progress.seen_count,
        notified_articles=notified_articles,
        notified_at=last_notified.notified_at,
    )


class ScanCancelOut(BaseModel):
    cancelled: bool  # True: 実行中の巡回に停止要求を送った / False: 巡回中ではなかった


@router.post("/api/scan/cancel", response_model=ScanCancelOut)
def cancel_scan():
    """
    実行中の巡回 (手動・自動いずれも) に緊急停止を要求する (2026-09-10新設)。

    実際に停止するまでのタイムラグ・安全性の考慮については
    scheduler.scan_state_tracker のモジュールdocstring参照。
    """
    from scheduler.scan_state_tracker import request_cancel

    return ScanCancelOut(cancelled=request_cancel())


@router.post("/api/scan", response_model=ScanTriggerOut)
def trigger_scan(
    prefecture: str | None = None,
    category_slug: str | None = None,
    category_id: str | None = None,
    area_id: str | None = None,
    area_name: str | None = None,
):
    """
    一覧巡回を即座に1回実行する (UIの「今すぐ更新」ボタン向け)。

    scheduler.job.run_scan_with_range() を、現在保存されている
    取得範囲設定 (scan_range_mode / scan_range_value。設定画面の
    「取得範囲」で変更可能。未設定ならデフォルトの1ページ目のみ)
    に従って呼び出す薄いラッパー。

    2026-09-07 変更: 従来は run_scan() (1ページ固定) を直接
    呼んでいたが、取得範囲設定の追加に伴い run_scan_with_range() 経由に
    切り替えた。デフォルト設定 (pages, 1) では従来と同じ「1ページ目
    のみ」の挙動になる。

    2026-09-09 変更: 従来は prefecture 等の監視対象がこのエンドポイント
    のデフォルト引数 (prefecture="fukuoka" 等) にハードコードされて
    おり、フロントエンドも常に引数なしで呼んでいたため、実質的に
    常に固定の地域・カテゴリでしか動作していなかった。自動更新
    (サーバー側定期実行) の追加にあたり、リクエストに引数が無い場合は
    DB (scan_state テーブル、repository.scan_settings_repository.
    get_monitored_target) から監視対象を読み込むようにした。将来
    地域変更UIができた際、そのUIで保存した内容がこのエンドポイントにも
    自動的に反映される (ユーザーとの合意事項:「今後また地域変更を
    行えるUIを新設する可能性があるので設定としては余地を残しておいて
    ほしい」)。

    引数を明示的に渡した場合は、その値がDBの内容より優先される
    (後方互換のため。既存のテスト・呼び出し元への影響を避ける)。

    低頻度アクセスの原則があるため、UI側は連打防止 (ボタンの
    一時的な無効化等) を行うことが望ましい。

    2026-09-10 変更: scheduler.scan_state_tracker と連携し、
      - 既に巡回中 (自動更新のバックグラウンド実行中を含む) の場合は
        新たな巡回を開始せず 409 を返す (多重起動防止。開始判定と
        フラグ更新は try_start_scan() でアトミックに行うため、
        タイミングが重なっても二重に巡回が走ることはない)。
      - 巡回中フラグはtry/finallyで確実に解除する (処理中に例外が
        発生してもフラグが立ちっぱなしにならないようにするため)。
    """
    from repository.scan_settings_repository import (
        clear_scan_progress,
        get_monitored_target,
        get_scan_range_settings,
    )
    from scraper.fetch import build_client
    from scheduler.job import run_scan_with_range
    from scheduler.scan_state_tracker import mark_scan_finished, try_start_scan

    if not try_start_scan():
        raise HTTPException(
            status_code=409,
            detail="既に巡回が実行中です (自動更新中の可能性があります)。完了までお待ちください。",
        )

    conn = get_db()
    try:
        range_settings = get_scan_range_settings(conn)
        target = get_monitored_target(conn)

        resolved_prefecture = prefecture if prefecture is not None else target.prefecture
        resolved_category_slug = category_slug if category_slug is not None else target.category_slug
        resolved_category_id = category_id if category_id is not None else target.category_id
        resolved_area_id = area_id if area_id is not None else target.area_id
        resolved_area_name = area_name if area_name is not None else target.area_name

        with build_client() as client:
            result = run_scan_with_range(
                conn, client,
                prefecture=resolved_prefecture, category_slug=resolved_category_slug,
                category_id=resolved_category_id, area_id=resolved_area_id,
                area_name=resolved_area_name,
                scan_range_mode=range_settings.scan_range_mode,
                scan_range_value=range_settings.scan_range_value,
            )
    finally:
        # 2026-09-10追加: run_scan_with_range()自体も正常系・緊急停止
        # いずれのパスでも進捗をクリアするが、ネットワークエラー等で
        # 例外が起きた場合はそこまで到達しない。ここで確実にクリアする
        # (詳細は scan_settings_repository.clear_scan_progress()
        # docstring参照)。
        try:
            clear_scan_progress(conn)
        except Exception:
            logging.getLogger(__name__).warning("巡回進捗のクリアに失敗しました", exc_info=True)
        conn.close()
        mark_scan_finished()

    return ScanTriggerOut(
        total_seen=result.total_seen,
        new_articles=result.new_articles,
        price_changed=result.price_changed,
        newly_missing=result.newly_missing,
        notified_count=len(result.notified),
        title_changed=result.title_changed,
        cancelled=result.cancelled,
    )


@router.get("/api/health")
def health():
    return {"status": "ok"}
