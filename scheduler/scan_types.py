"""
巡回処理の結果を表すデータクラス群。

scheduler/job.py (旧・巡回ジョブ本体の単一ファイル) から分割
(2026-09-13)。これらのデータクラスは fetch_html・polite_sleep・
is_cancel_requested のいずれにも依存せず、テストからも直接
patch対象にされていないため、他の巡回ロジックと切り離して
安全に独立させられる。
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ScanResult:
    """1回の一覧巡回 (run_scan) の結果サマリ。UI・ログ表示用。"""

    total_seen: int
    new_articles: int
    price_changed: int
    newly_missing: int
    notified: list[str]  # 通知対象になった article_id のリスト
    purged_count: int = 0  # 2026-09-04: 保持期限(3週間)切れで削除した件数
    title_changed: int = 0  # 2026-09-07 追加: タイトルが変化した既存投稿の件数
    # 2026-09-10追加: 緊急停止によりページ巡回の途中で打ち切られたか。
    # Trueの場合、まだ見ていないページの投稿が残っている可能性があるため、
    # missing化 (mark_missing_articles) は意図的にスキップしている
    # (run_scan_with_range() のNote参照)。
    cancelled: bool = False
    # 2026-09-13追加: 「検索」タブ (pickup_search) の条件にヒットし、
    # Discordへ通知を試みた件数。Discord通知が無効/未設定の場合は
    # 判定自体を行わないため常に0になる。送信自体の成否 (Webhook URLが
    # 無効だった等) はここには反映しない (UI側には「対象件数」として
    # 見せ、送信エラーの詳細はサーバーログを見る想定)。
    discord_notified_count: int = 0
    # 2026-09-15追加: 「検索」タブ (pickup_search) の条件にヒットした
    # 新規投稿のarticle_idのリスト (トースト通知・ブラウザ通知の対象)。
    # Discordへの通知試行対象と同じ集合だが、フロントエンド側が
    # GET /api/scan-status のポーリングで「前回までに見た通知対象との
    # 差分」を取り、新規に現れたものだけトースト/ブラウザ通知を出す
    # ために使う (通知のON/OFF判定自体はフロント側で行う。この一覧は
    # Discord・トースト・ブラウザいずれか1つでも有効なら埋まる。
    # scheduler.scan_runner._load_pickup_search_pattern_if_any_notification_enabled
    # 参照)。
    pickup_search_matched: list[str] = field(default_factory=list)


@dataclass
class MissingCheckResult:
    """
    (2026-09-04 廃止済み) 旧run_missing_check()のバルク版結果サマリ。
    後方互換のため型自体は残すが、現在この型を返す関数はない。
    1件単位の確認は confirm_single_missing_article() を使うこと。
    """

    checked: int
    restored: int
    deleted: int


@dataclass
class PageScanResult:
    """
    1ページ分の巡回結果 (内部使用)。missing化・purgeは含まない
    (複数ページを束ねてから1回だけ実行する必要があるため)。
    """

    seen_ids: set[str]
    total_seen: int
    new_articles: int
    price_changed: int
    notified: list[str]
    oldest_reference_dt: "date | None"  # そのページで最も古かった投稿の基準日 (日数範囲判定用)
    title_changed: int = 0  # 2026-09-07 追加
    # 2026-09-11追加: このページで採番されたdisplay_orderの最大値。
    # 「終了」タブ再設計 (確定終了/監視範囲外の判定) に使う。
    # 詳細はrun_scan_with_range() および
    # repository.article_repository.mark_missing_articles()
    # docstring参照。ページが0件だった場合はNone。
    max_display_order: "int | None" = None
    # 2026-09-13追加: 「検索」タブ (pickup_search) の条件にヒットした
    # 新規投稿のarticle_idのリスト (Discord通知機能)。notified
    # (NGでない新規投稿全般、トースト通知用) とは判定基準が異なる
    # 別の集合であるため、フィールドも分けている。呼び出し元
    # (run_scan_with_range) が全ページ分を束ねてDiscordへまとめて
    # 通知する。
    pickup_search_matched: list[str] = field(default_factory=list)
    # 2026-09-14追加: 一覧ページから取得できた総件数のヒント
    # (「全242690件中 1-50件表示」相当のテキストから抽出)。
    # scan_range_mode="days" のとき、総ページ数が事前に分からない
    # ため、この値を使って呼び出し元 (run_scan_with_range) が概算の
    # scan_progress_max_pageを計算し、進捗バーに反映する。取得できな
    # かった場合はNone (進捗バーは不定形表示にフォールバックする)。
    total_count_hint: "int | None" = None
