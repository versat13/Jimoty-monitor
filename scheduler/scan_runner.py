"""
巡回ジョブ本体。仕様書 v1.0 6章「フィルタリング処理フロー（確定）」①〜⑬を
1回の巡回として統合する。

    ① 一覧ページ取得
    ② p-articles-list-item を固定件数分すべて列挙
    ③ 広告除外
    ④ article_id抽出
    ⑤ 地域判定
    ⑥ カテゴリ判定
    ⑦ NGワード判定
    ⑧ DB照合（新規／既存判定）
    ⑨ 個別ページ取得（新規投稿のみ）
    ⑩ 出品者情報・全文説明・正式カテゴリ取得
    ⑪ seller_rules照合 → is_hidden_by_ruleフラグ設定
    ⑫ active_articlesへ保存
    ⑬ 通知判定（NGでない新規投稿のみトースト通知）

②〜⑦ (広告除外・URL構造からの各種ID抽出・NGワード判定) は
scraper/list_parser.py の時点で完了済み (ListArticle が既に
広告除外・地域/カテゴリ判定済みのデータ)。このモジュールが担うのは、
その後のフロー⑦後半〜⑬ (NGワード判定の実行そのもの、DB照合、
個別ページ取得、保存、通知判定) を1つの巡回として繋ぐことである。

=== missing処理について (2026-09-04 設計変更) ===

「一覧から消えた投稿」の確定判定について、旧設計 (2026-08-23合意、
run_missing_check() としてmissing状態の投稿全件を毎回機械的に
個別ページ確認していたバルク処理) は廃止した。

廃止理由 (ユーザーとの設計合意事項): ジモティーの性質上、良品は
すぐに取引終了になり、価格更新等の動きがあれば一覧の上位に
再出現する。一覧から消えた投稿すべてを毎回自動で確認しに行く
運用は、巡回1回あたりのアクセス数が実質倍増しうる割に、
この取引サイクルに対してはオーバースペックだった。

新設計:
    - run_scan() は今まで通り「今回の一覧に何が出ていたか」だけを見て
      missing化する (一覧取得1回で完結、軽い処理)。
    - missing状態の投稿は「公開終了」タブ (フロントエンド) に表示され
      続ける。ユーザーが興味を持った投稿だけ、confirm_single_missing_
      article() で1件ずつ個別に確認できる (api/main.pyの
      POST /api/articles/{article_id}/confirm-status)。
    - 確認されないまま3週間 (missing_since起点) 経過した投稿は、
      purge_expired_missing_articles() が自動的に削除する。この削除
      処理はDB内で完結し、外部への一切のHTTPアクセスを伴わない
      ため、run_scan() の一環として毎回実行しても低頻度アクセスの
      原則に反しない。
    - 「公開終了タブに残り続けている＝一覧から消えてまだ日が浅い」
      という情報自体が「これは人気だったのかもしれない」という
      参考情報にもなる、というのがこの設計の狙いの一つ。

=== 分割の経緯 (2026-09-13) ===

以前は scheduler/job.py という単一ファイルにこのモジュールの内容が
すべて収まっていた。データクラス (ScanResult等) と一部のヘルパー関数
(日付計算・NGルール読み込み) は scheduler/scan_types.py・
scheduler/scan_helpers.py へ切り出し済みだが、このファイルに残る
関数群 (_scan_one_page, run_scan, run_scan_with_range,
_fetch_and_store_detail, confirm_single_missing_article,
fetch_seller_profile_on_demand) はいずれも fetch_html・polite_sleep・
is_cancel_requested のいずれかに依存しており、かつ
tests/test_scheduler_job.py・tests/test_auto_refresh.py・
tests/test_api.py が `patch("scheduler.job.fetch_html")` のように
「このモジュール上の名前」を直接書き換える形でテストしていたため、
安全に分離するにはテスト側の参照先モジュール名も
scheduler.scan_runner に合わせて変更する必要があった。

scheduler/job.py は本モジュールへの後方互換の窓口として残している
(古いimport文 `from scheduler.job import run_scan` 等が今後も動作する
ようにするため)。新規コードは scheduler.scan_runner を直接
importすることを推奨する。
"""

import logging
from datetime import timedelta

import httpx

from filters.category_filter import check_ng_category
from filters.keyword_filter import check_ng_keywords
from filters.pickup_search_filter import matches_search_expression
from repository.article_repository import (
    confirm_missing_article,
    mark_missing_articles,
    mark_notified,
    purge_expired_articles,
    update_filter_flags,
    upsert_from_detail_article,
    upsert_from_list_article,
)
from repository.seller_repository import (
    get_seller_rule,
    replace_seller_other_articles,
    upsert_seller,
    upsert_seller_profile,
)
from scraper.detail_parser import parse_detail_page
from scraper.fetch import FetchError, build_list_url, fetch_html, polite_sleep
from scraper.list_parser import extract_total_count, parse_list_page
from scraper.profile_parser import parse_profile_page
from repository.scan_settings_repository import (
    DEFAULT_RETENTION_DAYS,
    ensure_scan_state_row,
    get_retention_settings,
    update_last_notified_articles,
)
from repository.discord_notification_repository import get_discord_notification_settings
from repository.pickup_search_repository import get_pickup_search
from notifications.discord_notifier import send_discord_notification
from scheduler.scan_state_tracker import is_cancel_requested
from scheduler.scan_helpers import (
    current_date_for_range,
    current_year_for_range,
    load_active_rules,
    reference_date_for_range,
)
from scheduler.scan_types import MissingCheckResult, PageScanResult, ScanResult  # noqa: F401 (MissingCheckResultは後方互換のため再エクスポート)

logger = logging.getLogger(__name__)

# 一覧ページ1ページあたりの投稿数 (実データで確認済み、ジモティー固定仕様)。
# display_order をページ跨ぎの通し番号にするためのオフセット計算にのみ使う。
# 実際の件数がこれより少ないページ (最終ページ等) があっても、次ページの
# オフセットが多少詰まって空きが出るだけで、順序の前後関係は崩れない。
ARTICLES_PER_PAGE = 50

# 2026-09-10追加、2026-09-13修正: run_scan_with_range() のページ巡回の
# 絶対上限 (安全弁)。scan_range_mode="days" のとき、本来なら
# oldest_reference_dt が cutoff_date を下回った時点で自然に終了する
# はずだが、ジモティー側が実在しないページ番号 (例: 9ページ目以降)
# へのリクエストに対して404/301を返さず、フォールバック的に別の
# 一覧 (トップページ相当) を200 OKで返してくることが実機で確認された
# (2026-09-10、ユーザー報告)。この場合 oldest_reference_dt が
# 新しい日付のまま更新され続け、cutoff_dateを下回らないため、
# 終了条件が働かず実質無限ループになる不具合があった。
#
# 2026-09-13修正: 当初はページの重複検知 (フォールバックページかどうかを
# 判定する関数) を主な対策とし、この上限は「万一それでも検知しきれない
# ケースに備えた保険」として導入する計画だったが、その重複検知自体は
# 実装されないまま、この定数もwhileループ内で一度も参照されずに
# 残っていた (つまり無限ループ対策が実質的に機能していなかった)。
# 重複検知の実装は判定基準の設計 (何をもって「同じページの
# 繰り返し」とみなすか) が必要なため、現時点ではこの絶対上限のみを
# 実際にrun_scan_with_range()のwhileループへ適用し、確実に無限
# ループを防ぐことを優先した。重複検知自体は将来の課題として残す
# (30ページ分の無駄なアクセスをしてから打ち切る形になるため、
# 低頻度アクセスの原則との兼ね合いでは理想的ではないが、
# 無限ループよりは望ましいという判断)。
MAX_PAGES_SAFETY_LIMIT = 30



def _scan_one_page(
    conn, client: httpx.Client, list_url: str, *, display_order_offset: int = 0,
    pickup_search_pattern: str = "",
) -> PageScanResult:
    """
    一覧ページ1ページ分を取得し、記事単位のフロー⑦〜⑬
    (NGワード/NGカテゴリ判定・DB照合・個別ページ取得・保存・通知判定)
    を実行する。missing化・purge・コミットは呼び出し元 (run_scan /
    run_scan_with_range) が複数ページ分をまとめてから1回だけ行う。

    2026-09-07 リファクタリング理由:
    従来の run_scan() は1ページの取得からmissing化・commitまでを
    一体で行っており、docstringには「複数ページを巡回したい場合は
    呼び出し元がpage番号を変えながらこの関数を複数回呼ぶこと」と
    書かれていた。しかし mark_missing_articles(conn, seen_ids) は
    「今回の巡回全体で見た全article_idの集合」を前提にしており、
    単純に複数回呼ぶと2ページ目の呼び出し時に1ページ目のseen_idsが
    失われ、1ページ目にしか出現しなかった投稿が誤ってmissing化
    されてしまう。取得範囲設定 (ページ数/日数) の追加にあたり、
    複数ページ巡回を安全に行えるようにするため、ページ単位の処理と
    missing化を分離した。

    2026-09-07 バグ修正 (display_order):
    display_order はこれまで enumerate(articles) によりページ内で
    毎回 0 から採番していたため、2ページ目以降の投稿も1ページ目と
    同じ 0〜49 の範囲の値で保存されてしまい、複数ページ巡回時に
    「公式サイトと同じ並び順」というdisplay_orderの目的を満たせて
    いなかった (ユーザーからの実機確認・指摘により判明)。
    display_order_offset (呼び出し元がページ番号から算出した
    (page-1)*50 等の値) をページ内インデックスに加算することで、
    巡回全体を通した通し番号になるよう修正した。

    Args:
        pickup_search_pattern: 2026-09-13追加。「検索」タブ
            (pickup_search) の保存済み正規表現。空文字なら
            Discord通知の判定自体を行わない (呼び出し元が
            Discord通知が無効/未設定の場合に空文字を渡す想定)。
    """
    logger.info("一覧ページを取得します: %s", list_url)
    try:
        list_html = fetch_html(client, list_url)
    except FetchError as e:
        logger.error("一覧ページの取得に失敗しました: %s", e)
        raise

    # ②③④⑤⑥ (広告除外・article_id抽出・地域/カテゴリ判定) は
    # list_parser.parse_list_page() の内部で完了済み
    articles = parse_list_page(list_html, current_year=current_year_for_range())
    logger.info("一覧パース結果: %d件 (広告除外後)", len(articles))

    # 2026-09-14追加: 進捗バー (scan_range_mode="days" のときの概算
    # 表示) 用に、一覧ページ最下部の総件数表示を取得しておく。
    # 取得できなくても巡回処理自体には影響しない (Noneのまま進む)。
    total_count_hint = extract_total_count(list_html)

    ng_keywords, ng_categories = load_active_rules(conn)

    seen_ids: set[str] = set()
    new_count = 0
    price_changed_count = 0
    title_changed_count = 0
    notified: list[str] = []
    pickup_search_matched: list[str] = []
    oldest_reference_dt = None

    for local_index, article in enumerate(articles):
        display_order = display_order_offset + local_index
        seen_ids.add(article.article_id)

        # 取得範囲「過去n日」の判定用に、この投稿の基準日
        # (更新日があれば更新日、なければ作成日) を求めておく。
        # 一覧は新着順に並んでいる前提のため、ページ内で最も古い
        # 基準日を代表値として呼び出し元に返す。
        #
        # 2026-09-08 バグ修正: PR枠 (is_pr_slot=True) は一覧の新着順を
        # 無視して表示され続けるため、PR枠込みで最古値を計算すると
        # 「本当は新しい投稿が後続ページにまだ多数あるのに、たった
        # 1件の古いPR枠が混ざっているだけで即座に巡回を打ち切って
        # しまう」という不具合があった (実機確認・ユーザー報告により
        # 判明: 3日前までの設定なのに1ページ目のみで打ち切られ、
        # 実際にはPR枠として表示されていた古い投稿が原因だった)。
        # PR枠は最古値の計算対象から除外する。
        if not article.is_pr_slot:
            ref_date = reference_date_for_range(article)
            if ref_date is not None and (oldest_reference_dt is None or ref_date < oldest_reference_dt):
                oldest_reference_dt = ref_date

        # 2026-09-07 追加: updated_date_raw が無いのは「まだ更新されて
        # いない新規投稿」として正常だが、created_date_raw まで無い場合は
        # 一覧の日時表記そのものがパースできていない異常なケースのため
        # 警告ログを残す (ユーザーとの打ち合わせで整理した区別)。
        if article.updated_date_raw is None and article.created_date_raw is None:
            logger.warning(
                "投稿の更新日・作成日がいずれも取得できませんでした (パース異常の可能性): %s",
                article.article_id,
            )

        # ⑦ NGワード判定 (一覧由来の情報のみで判定可能)
        keyword_result = check_ng_keywords(article.list_title, article.description_short, ng_keywords)

        # ⑧ DB照合（article_idの新規／既存判定）
        # display_order: 一覧に出現した順番をそのまま保持する
        # (公式サイトと同じ並び順を再現するため。2026-08-24 新設)
        upsert_result = upsert_from_list_article(conn, article, display_order=display_order)

        if upsert_result.price_changed:
            price_changed_count += 1
            logger.info(
                "価格変化を検知: %s (%s円 -> %s円)",
                article.article_id, upsert_result.old_price, upsert_result.new_price,
            )

        if upsert_result.title_changed:
            # 2026-09-07 追加: タイトル変更はヒストリーを持たず最新値に
            # 上書きするのみだが (repository.article_repository の
            # upsert_from_list_article docstring参照)、変更が起きた
            # こと自体はログレベルで残しておく。
            title_changed_count += 1
            logger.info(
                "タイトル変更を検知: %s (%s -> %s)",
                article.article_id, upsert_result.old_title, upsert_result.new_title,
            )

        if upsert_result.is_new:
            new_count += 1
            # ⑨⑩ 個別ページ取得・出品者情報等の取得 (新規投稿のみ)
            # この時点で category_mid_id (中間カテゴリ) がDBに保存される
            _fetch_and_store_detail(conn, client, article.url, article.article_id)

        # ⑦ NGカテゴリ判定
        #
        # 2026-09-07 バグ修正 (重要): 以前はこの判定を個別ページ取得より
        # "前" に行っており、一覧由来の article.category_id のみを
        # check_ng_category() に渡していた。しかし category_mid_id
        # (中間カテゴリID) は個別ページ取得後にしか判明しない
        # (filters/category_filter.py のdocstring参照)。このため、
        # 「中間カテゴリ単位でNG登録している」場合、新規投稿の
        # 初回巡回時にはその中間カテゴリがまだDBに存在せず、
        # NGカテゴリ判定に一切引っかからないまま
        # is_hidden_by_category=False で保存され、さらに⑬の通知判定でも
        # NGとして扱われずに通知されてしまう不具合があった
        # (filters/recompute.py 側は category_mid_id も見て判定するため、
        # NGカテゴリ登録・変更後の再計算では正しく隠れるが、
        # 「新規登録された瞬間」だけこの不整合の影響を受けていた)。
        #
        # 修正方針: 個別ページ取得 (category_mid_idの確定) の後に
        # 判定し直すよう順序を入れ替える。個別ページ取得が行われない
        # 既存投稿 (is_new=False) の場合も、DBに保存済みの
        # category_mid_id を読み直してから判定することで、
        # 新規・既存どちらの経路でも同じ基準で判定されるようにする。
        row = conn.execute(
            "SELECT seller_id, category_mid_id, category_parent_id FROM active_articles WHERE article_id = ?",
            (article.article_id,),
        ).fetchone()
        category_mid_id = row["category_mid_id"] if row is not None else None
        category_parent_id = row["category_parent_id"] if row is not None else None
        category_result = check_ng_category(
            article.category_id,
            ng_categories,
            category_mid_id=category_mid_id,
            category_parent_id=category_parent_id,
        )

        # ⑪ NGユーザー判定 (取得・保存自体はフラグに関わらず必ず行う。仕様書5-4)
        seller_rule_hidden = False
        if row is not None and row["seller_id"] is not None:
            rule = get_seller_rule(conn, row["seller_id"])
            seller_rule_hidden = rule is not None and rule["rule_type"] == "ng"

        update_filter_flags(
            conn,
            article.article_id,
            is_hidden_by_keyword=keyword_result.matched,
            is_hidden_by_category=category_result.matched,
            is_hidden_by_seller_rule=seller_rule_hidden,
            matched_ng_keywords=keyword_result.matched_keywords,
        )

        # ⑬ 通知判定（NGでない新規投稿のみトースト通知）
        is_hidden = keyword_result.matched or category_result.matched or seller_rule_hidden
        if upsert_result.is_new and not is_hidden:
            notified.append(article.article_id)
            mark_notified(conn, article.article_id)
            logger.info("通知対象: %s - %s", article.article_id, article.list_title)

            # 2026-09-13追加: 「検索」タブ (pickup_search) の条件に
            # ヒットした新規投稿は、上記のトースト通知対象とは別に
            # Discord通知の対象としても記録する。NGでない新規投稿の
            # うち、さらに検索条件にマッチしたものだけに絞り込む
            # (NG判定済みの投稿を通知してしまわないよう、is_hiddenの
            # 判定より後で行う)。
            if pickup_search_pattern and matches_search_expression(
                article.list_title, article.description_short, pickup_search_pattern
            ):
                pickup_search_matched.append(article.article_id)

    return PageScanResult(
        seen_ids=seen_ids,
        total_seen=len(articles),
        new_articles=new_count,
        price_changed=price_changed_count,
        notified=notified,
        oldest_reference_dt=oldest_reference_dt,
        title_changed=title_changed_count,
        max_display_order=(display_order_offset + len(articles) - 1) if articles else None,
        pickup_search_matched=pickup_search_matched,
        total_count_hint=total_count_hint,
    )


def _load_pickup_search_pattern_if_any_notification_enabled(conn) -> str:
    """
    Discord・アプリ内トースト・ブラウザ通知のいずれかが有効な場合のみ、
    検索タブ (pickup_search) の正規表現パターンを読み込んで返す
    (2026-09-13追加、2026-09-15拡張)。

    2026-09-15変更: 従来はDiscord通知が有効な場合のみ読み込んでいたが、
    「Discordと共通の条件でトースト通知・ブラウザ通知も出したい」
    という要望により、3種類のうちどれか1つでも有効なら読み込むように
    した (関数名もそれに合わせて変更。旧名
    _load_pickup_search_pattern_if_discord_enabled は呼び出し元が
    存在しないため削除した)。

    いずれも無効/未設定の場合は空文字を返す。これにより、
    _scan_one_page() 側の判定 (if pickup_search_pattern: ...) が
    自然にスキップされ、通知機能を一切使っていないユーザーには
    余分なオーバーヘッド・挙動変化が生じないようにしている。
    """
    settings = get_discord_notification_settings(conn)
    discord_active = settings.enabled and bool(settings.webhook_url)
    if not (discord_active or settings.in_app_enabled or settings.browser_enabled):
        return ""
    pickup_search = get_pickup_search(conn)
    return pickup_search.search_expression


def _send_discord_notifications_for_matched_articles(conn, article_ids: list[str]) -> int:
    """
    検索タブの条件にヒットした新規投稿をDiscordへ通知する
    (2026-09-13追加)。

    article_ids が空、またはDiscord通知が無効/未設定の場合は何もせず
    0を返す。実際の送信失敗 (Webhook URLが無効化された等) は
    notifications.discord_notifier 側でログに警告を出すのみとし、
    この関数・呼び出し元の巡回処理自体は失敗させない (通知は補助機能
    であるため)。

    Returns:
        Discordへ通知を試みた件数 (送信の成否は問わない)。
    """
    if not article_ids:
        return 0

    settings = get_discord_notification_settings(conn)
    if not settings.enabled or not settings.webhook_url:
        return 0

    placeholders = ",".join("?" for _ in article_ids)
    rows = conn.execute(
        f"SELECT article_id, list_title, price, url, thumbnail_url, area_name "
        f"FROM active_articles WHERE article_id IN ({placeholders})",
        article_ids,
    ).fetchall()
    articles = [dict(row) for row in rows]

    send_discord_notification(settings.webhook_url, articles)
    return len(articles)


def run_scan(conn, client: httpx.Client, list_url: str) -> ScanResult:
    """
    一覧ページ1ページ分を巡回し、フロー①〜⑬を実行する (従来通りの
    単一ページ版。後方互換のため維持)。

    複数ページ・過去n日といった取得範囲を指定して巡回したい場合は
    run_scan_with_range() を使うこと (2026-09-07 追加)。

    Args:
        conn: repository.article_repository.get_connection() で得たDB接続
        client: scraper.fetch.build_client() で得たhttpxクライアント
        list_url: scraper.fetch.build_list_url() で組み立てた一覧ページURL

    Returns:
        ScanResult。呼び出し元はこれを使ってログ出力やUI表示を行う。
    """
    # 2026-09-13追加: Discord通知が有効な場合のみ、検索タブの正規表現
    # パターンを読み込んで _scan_one_page に渡す (無効時は空文字を渡し、
    # 判定自体を省略してオーバーヘッドを避ける)。
    pickup_search_pattern = _load_pickup_search_pattern_if_any_notification_enabled(conn)

    page_result = _scan_one_page(conn, client, list_url, pickup_search_pattern=pickup_search_pattern)

    newly_missing = mark_missing_articles(conn, page_result.seen_ids)
    if newly_missing:
        logger.info("%d件の投稿がmissing状態になりました: %s", len(newly_missing), newly_missing)

    # 2026-09-11変更: purge_expired_missing_articles()を
    # purge_expired_articles()に置き換えた (missingだけでなくactiveも
    # 対象、日数も設定可能になった。詳細はそちらのdocstring参照)。
    # この関数(run_scan)はレガシーな1ページ版で、設定(scan_state)から
    # retention_enabled/retention_daysを読む経路を持たないため、
    # デフォルト値 (7日) で動作させる。
    purged_count = purge_expired_articles(conn, retention_days=DEFAULT_RETENTION_DAYS)
    if purged_count:
        logger.info("保存期間(%d日)切れの投稿を削除しました: %d件", DEFAULT_RETENTION_DAYS, purged_count)

    conn.commit()

    discord_notified_count = _send_discord_notifications_for_matched_articles(
        conn, page_result.pickup_search_matched
    )
    # 2026-09-15追加: トースト通知・ブラウザ通知向けに、今回の巡回で
    # pickup_search条件にヒットした新規投稿をscan_stateへ保存する
    # (対象0件でも洗い替えのため必ず呼ぶ)。詳細は
    # update_last_notified_articles() のdocstring参照。
    update_last_notified_articles(conn, page_result.pickup_search_matched)

    return ScanResult(
        total_seen=page_result.total_seen,
        new_articles=page_result.new_articles,
        price_changed=page_result.price_changed,
        newly_missing=len(newly_missing),
        notified=page_result.notified,
        purged_count=purged_count,
        title_changed=page_result.title_changed,
        discord_notified_count=discord_notified_count,
        pickup_search_matched=page_result.pickup_search_matched,
    )


def run_scan_with_range(
    conn,
    client: httpx.Client,
    *,
    prefecture: str,
    category_slug: str,
    category_id: str | None = None,
    area_id: str | None = None,
    area_name: str | None = None,
    scan_range_mode: str = "pages",
    scan_range_value: int = 1,
    sleep_seconds: float = 1.5,
) -> ScanResult:
    """
    取得範囲設定 (ページ数 or 過去n日) に従って一覧を複数ページ
    巡回し、フロー①〜⑬をまとめて実行する (2026-09-07 追加)。

    Args:
        prefecture, category_slug, category_id, area_id, area_name:
            scraper.fetch.build_list_url() に渡すのと同じ引数。
        scan_range_mode: "pages" または "days" (排他)。
            db/schema.sql の scan_state.scan_range_mode と対応する。
        scan_range_value:
            scan_range_mode="pages" のとき: 巡回する最大ページ数
                (1なら従来通り1ページ目のみ)。
            scan_range_mode="days" のとき: 遡る日数。一覧を新着順に
                ページ送りしながら、そのページで最も古かった投稿の
                基準日 (更新日優先・なければ作成日) が
                「今日から scan_range_value 日より前」になった時点で
                以降のページ送りを打ち切る (一覧が新着順である前提を
                利用する)。2026-09-08時点でPR枠 (is_pr_slot=True) は
                この最古値の判定対象から除外している (PR枠は新着順を
                無視して表示され続けるため、含めると誤って早期に
                打ち切ってしまう不具合があった)。
        sleep_seconds: ページ間のアクセス間隔 (低頻度アクセスの原則。
            scraper.fetch.polite_sleep() に渡す)。

    Returns:
        全ページ分を合算した ScanResult。missing化・purgeは
        全ページの取得が終わった後にまとめて1回だけ実行する
        (理由は _scan_one_page() のdocstring参照)。

    Note:
        重複投稿 (DBに既存のarticle_id) は、価格・タイトルの差分
        チェックのみを行い、個別ページへの再アクセスはしない
        (upsert_from_list_article の既存の挙動をそのまま踏襲)。
        このため、取得範囲を広げてアクセス数が増えるのは
        「新規に見つかった投稿の件数」に比例する分のみであり、
        既存投稿の再確認によってアクセス数が跳ね上がることはない。

    Note (2026-09-10追加、トランザクション分割・緊急停止):
        以前は全ページの取得・処理が終わるまで1本のトランザクションを
        保持していたが、この間他の接続 (設定変更等) が書き込みロック
        待ちになる問題があったため、ページ単位で commit() するように
        変更した。missing化 (mark_missing_articles) は「巡回全体で
        見た全article_idの集合」を前提とするため、これは従来通り
        全ページ走査後にまとめて1回だけ行う。

        scheduler.scan_state_tracker.is_cancel_requested() が
        True を返した場合、次のページに着手する前に巡回を打ち切る
        (ページの途中では止めない)。この場合 ScanResult.cancelled が
        True になり、missing化・期限切れ削除はスキップされる
        (まだ見ていない後続ページの投稿を誤ってmissing扱いしないため)。
        呼び出し元 (trigger_scan / _run_scan_sync) は、この関数の
        呼び出し前後で scan_state_tracker.mark_scan_started() /
        mark_scan_finished() を呼ぶ責務を持つ。

    Note (2026-09-13追加、無限ループ対策):
        scan_range_mode="days" のとき、ジモティー側が実在しない
        ページ番号に対して0件ではなくフォールバック的に別の一覧を
        200 OKで返してくることがある (2026-09-10、実機確認済み)。
        この場合 cutoff_date による終了条件が働かないため、
        MAX_PAGES_SAFETY_LIMIT (モジュール定数) に達した時点で
        強制的に打ち切る。この上限に達して打ち切られた場合も
        cancelled=True 相当の扱いはせず (ユーザーによる意図的な
        停止ではないため)、それまでに取得できたページ分の結果を
        そのまま返す (missing化・purgeも通常通り実行する)。
    """
    if scan_range_mode not in ("pages", "days"):
        raise ValueError(f"scan_range_modeはpagesまたはdaysである必要があります: {scan_range_mode}")
    if scan_range_value < 1:
        raise ValueError(f"scan_range_valueは1以上である必要があります: {scan_range_value}")

    all_seen_ids: set[str] = set()
    total_seen = 0
    new_articles = 0
    price_changed = 0
    notified: list[str] = []
    title_changed = 0
    cancelled = False
    # 2026-09-13追加: 「検索」タブ (pickup_search) の条件にヒットした
    # 新規投稿のarticle_idを、全ページ分まとめて集約する (Discord通知)。
    pickup_search_matched: list[str] = []
    # 2026-09-11追加: 「終了」タブ再設計 (確定終了/監視範囲外の判定) 用。
    # 今回の巡回全体を通して実際に見えた投稿のdisplay_orderの最大値。
    # mark_missing_articles() に渡し、消えた投稿の旧display_orderが
    # この値以下 (=本来見えるはずの範囲内) かどうかで判定する。
    overall_max_display_order: int | None = None

    max_pages = scan_range_value if scan_range_mode == "pages" else None
    cutoff_date = None
    if scan_range_mode == "days":
        cutoff_date = current_date_for_range() - timedelta(days=scan_range_value)

    # 2026-09-13追加: Discord通知が有効な場合のみ、検索タブの正規表現
    # パターンを読み込む (無効時は空文字を渡し、_scan_one_page側の
    # 判定自体を省略する)。ループの外で1回だけ読めば十分
    # (巡回の途中で設定が変わることは通常想定しない)。
    pickup_search_pattern = _load_pickup_search_pattern_if_any_notification_enabled(conn)

    # 2026-09-10追加: 巡回開始時に進捗表示用カラムをリセットする。
    # BottomNav付近のUI (GET /api/scan-status) がこれを見て「更新中…
    # 2/3ページ・128件確認」のような表示を出す。scan_progress_max_page
    # は'pages'モードのときのみ値を入れる ('days'モードは何ページで
    # 終わるか事前に分からないため、UI側は上限不明の表示にする)。
    #
    # ensure_scan_state_row()で行の存在を先に保証する (設定タブを
    # 一度も開かずに「今すぐ更新」を押した場合でも、下のUPDATE文が
    # 空振りしないようにするため)。
    ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET scan_progress_current_page = 0, "
        "scan_progress_max_page = ?, scan_progress_seen_count = 0 "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        (max_pages,),
    )
    conn.commit()

    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break

        # 2026-09-13追加: 無限ループ対策 (モジュール定数
        # MAX_PAGES_SAFETY_LIMIT のdocstring、およびこの関数のNote
        # 「無限ループ対策」参照)。scan_range_mode="days" のとき、
        # ジモティー側のフォールバック応答によりcutoff_dateによる
        # 終了条件が働かないケースがあるため、ページ数そのものに
        # 絶対上限を設ける。pagesモードでは通常max_pagesの方が
        # 先に効くため実質的に影響しないが、両モード共通の安全網
        # として無条件にチェックする。
        if page > MAX_PAGES_SAFETY_LIMIT:
            logger.warning(
                "ページ巡回が安全上限(%d ページ)に達したため打ち切ります "
                "(scan_range_mode=%s)。ジモティー側が想定外のページを "
                "返し続けている可能性があります。",
                MAX_PAGES_SAFETY_LIMIT, scan_range_mode,
            )
            break

        # 2026-09-10追加: 緊急停止対応。次のページ取得に進む前に確認する
        # (ページの途中では止めない。理由はscan_state_tracker.pyの
        # モジュールdocstring「停止の粒度について」参照)。
        if is_cancel_requested():
            logger.info("緊急停止が要求されたため、ページ%d着手前に巡回を打ち切ります", page)
            cancelled = True
            break

        list_url = build_list_url(
            prefecture, category_slug,
            category_id=category_id, area_id=area_id, area_name=area_name,
            page=page,
        )

        if page > 1:
            polite_sleep(sleep_seconds)

        page_result = _scan_one_page(
            conn, client, list_url,
            display_order_offset=(page - 1) * ARTICLES_PER_PAGE,
            pickup_search_pattern=pickup_search_pattern,
        )

        all_seen_ids |= page_result.seen_ids
        total_seen += page_result.total_seen
        new_articles += page_result.new_articles
        price_changed += page_result.price_changed
        title_changed += page_result.title_changed
        notified.extend(page_result.notified)
        pickup_search_matched.extend(page_result.pickup_search_matched)
        if page_result.max_display_order is not None:
            overall_max_display_order = (
                page_result.max_display_order
                if overall_max_display_order is None
                else max(overall_max_display_order, page_result.max_display_order)
            )

        # 2026-09-14追加: scan_range_mode="days" のとき (総ページ数が
        # 事前に分からないモード)、1ページ目の総件数ヒント
        # (page_result.total_count_hint) から概算のページ数上限を
        # 計算し、scan_progress_max_pageにセットする。これにより
        # 進捗バーがdaysモードでも「全体のうちどれくらい確認したか」
        # の概算を表示できるようになる (BottomNav.jsx参照)。
        #
        # 2ページ目以降では計算し直さない (1ページ目の値で十分。
        # 巡回中に総件数が大きく変わることは通常想定しない)。
        # MAX_PAGES_SAFETY_LIMITを超える概算値は無意味 (どのみち
        # そこで打ち切られるため) なので、その値で頭打ちにする。
        if (
            page == 1
            and scan_range_mode == "days"
            and page_result.total_count_hint is not None
        ):
            estimated_max_page = min(
                MAX_PAGES_SAFETY_LIMIT,
                max(1, -(-page_result.total_count_hint // ARTICLES_PER_PAGE)),  # 切り上げ除算
            )
            conn.execute(
                "UPDATE scan_state SET scan_progress_max_page = ? "
                "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
                (estimated_max_page,),
            )

        # 2026-09-10追加: 進捗表示を更新する (トランザクション分割で
        # 追加したページ単位commitに相乗りする形)。
        conn.execute(
            "UPDATE scan_state SET scan_progress_current_page = ?, "
            "scan_progress_seen_count = ? "
            "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
            (page, total_seen),
        )

        # 2026-09-10追加: ページ単位でコミットする (トランザクション分割)。
        # 以前は全ページの取得が終わるまで1本の長いトランザクションを
        # 保持しており、その間 (ネットワーク取得込みで数秒〜長い場合は
        # 数十秒) 他の接続からの書き込み (設定変更等) がロック待ちに
        # なっていた。ページ単位でこまめにコミットすることで、ロックが
        # 発生してもごく短時間で解放されるようにする
        # (repository.article_repository.get_connection() のWALモード化
        # と合わせて、実質的にロック競合をほぼ解消する狙い)。
        #
        # 注意: mark_missing_articles()は「巡回全体で見た全article_idの
        # 集合」を前提とするため、ここではまだ呼ばない (全ページ走査後に
        # まとめて1回だけ実行する、という既存の設計は維持する)。
        conn.commit()

        if page_result.total_seen == 0:
            # 一覧が空 (存在しないページ番号まで進んだ) なら打ち切り
            logger.info("ページ%dは投稿0件のため巡回を終了します", page)
            break

        if scan_range_mode == "days":
            if page_result.oldest_reference_dt is not None and page_result.oldest_reference_dt < cutoff_date:
                logger.info(
                    "ページ%dで基準日(%s)が範囲(%s日前=%s)を下回ったため巡回を終了します",
                    page, page_result.oldest_reference_dt, scan_range_value, cutoff_date,
                )
                break

        page += 1

    # 2026-09-10追加: 巡回終了時 (正常終了・打ち切りいずれも) に
    # 進捗表示をクリアする。「更新中でないのに古い進捗が残っている」
    # 状態を防ぐ。
    conn.execute(
        "UPDATE scan_state SET scan_progress_current_page = NULL, "
        "scan_progress_max_page = NULL, scan_progress_seen_count = NULL "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)"
    )
    conn.commit()

    if cancelled:
        # 2026-09-10追加: 緊急停止時はmissing化・purgeを行わない。
        # まだ見ていないページに存在するはずの投稿まで「一覧から消えた
        # (missing)」と誤判定してしまうリスクがあるため、安全側に倒す。
        # 既に各ページはコミット済みなので、そこまでの新規投稿・価格変化
        # 等の検知結果自体は失われない。
        newly_missing: list[str] = []
        purged_count = 0
        logger.info("緊急停止のため、missing化・期限切れ削除はスキップしました")
    else:
        newly_missing = mark_missing_articles(
            conn, all_seen_ids, max_seen_display_order=overall_max_display_order
        )
        if newly_missing:
            logger.info("%d件の投稿がmissing状態になりました: %s", len(newly_missing), newly_missing)

        # 2026-09-11追加: 「終了」タブ再設計。mark_missing_articles()が
        # 'confirmed_closed'候補に分類した投稿 (=取得範囲内で消えた、
        # 本当に終了した可能性が高い投稿) だけを対象に、個別ページへ
        # 自動で再アクセスして確定させる。'range_uncertain'
        # (取得範囲外に押し出されただけの可能性がある投稿) は対象外
        # (自動アクセスしない。ユーザーとの合意事項)。
        #
        # このアクセスは「今回の巡回で新たにconfirmed_closed候補になった
        # 投稿」のみに限定する (get_missing_articlesで全件取得すると、
        # 過去の巡回で既に候補になったまま未確認の投稿まで毎回
        # 再アクセスしてしまい、アクセス数が際限なく増えるため)。
        confirmed_closed_count = 0
        restored_from_candidate_count = 0
        if newly_missing:
            newly_missing_set = set(newly_missing)
            candidates = [
                row["article_id"] for row in conn.execute(
                    "SELECT article_id FROM active_articles "
                    "WHERE article_status = 'missing' AND missing_kind = 'confirmed_closed'"
                ).fetchall()
                if row["article_id"] in newly_missing_set
            ]
            for candidate_id in candidates:
                result = confirm_single_missing_article(conn, client, candidate_id)
                if result == "restored":
                    restored_from_candidate_count += 1
                elif result == "closed":
                    confirmed_closed_count += 1
            if candidates:
                logger.info(
                    "終了確定候補%d件を自動確認しました (終了確定%d件, 受付中に復帰%d件)",
                    len(candidates), confirmed_closed_count, restored_from_candidate_count,
                )

        # 2026-09-11変更: purge_expired_missing_articles()を
        # purge_expired_articles()に置き換えた (missingだけでなく
        # activeも対象、保存日数もscan_state.retention_daysから読んで
        # ユーザーが設定できるようになった。retention_enabled=False
        # なら削除処理自体を行わない。詳細はそちらのdocstring参照)。
        retention_settings = get_retention_settings(conn)
        if retention_settings.enabled:
            purged_count = purge_expired_articles(conn, retention_days=retention_settings.retention_days)
            if purged_count:
                logger.info(
                    "保存期間(%d日)切れの投稿を削除しました: %d件",
                    retention_settings.retention_days, purged_count,
                )
        else:
            purged_count = 0

    # 2026-09-09追加: 巡回完了時刻・件数をscan_stateに記録する。
    # 自動更新 (サーバー側定期実行) が「前回いつ実行したか」を判定する
    # ために使う。手動実行 (「今すぐ更新」ボタン) でも同様に更新する
    # ことで、手動実行した直後に自動更新がすぐ重複実行されるのを防ぐ
    # (両方が同じ場所を見るため一貫する)。
    #
    # 2026-09-10: 緊急停止時もここは更新する (「前回いつ動いたか」の
    # 実態を反映するため。UI側は結果のcancelledフラグを見て
    # 「途中で停止しました」等の表示を出し分けられる)。
    conn.execute(
        "UPDATE scan_state SET last_scanned_at = datetime('now'), last_scan_item_count = ? "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)",
        (total_seen,),
    )

    conn.commit()

    # 2026-09-13追加: 検索タブの条件にヒットした新規投稿をDiscordへ通知
    # する。commit()の後に行うことで、通知先に含めた投稿が確実にDB上に
    # 保存済みの状態になってから送信する (万一送信中に例外が起きても、
    # 既にDBへの反映自体は完了しているようにするため)。
    discord_notified_count = _send_discord_notifications_for_matched_articles(
        conn, pickup_search_matched
    )
    # 2026-09-15追加: トースト通知・ブラウザ通知向けに、今回の巡回で
    # pickup_search条件にヒットした新規投稿をscan_stateへ保存する
    # (対象0件でも洗い替えのため必ず呼ぶ)。緊急停止で打ち切られた
    # 場合も、それまでに処理したページ分の結果はそのまま通知対象に
    # 含める (Discord通知と同じ扱い)。詳細は
    # update_last_notified_articles() のdocstring参照。
    update_last_notified_articles(conn, pickup_search_matched)

    return ScanResult(
        total_seen=total_seen,
        new_articles=new_articles,
        price_changed=price_changed,
        newly_missing=len(newly_missing),
        notified=notified,
        purged_count=purged_count,
        title_changed=title_changed,
        cancelled=cancelled,
        discord_notified_count=discord_notified_count,
        pickup_search_matched=pickup_search_matched,
    )


def _fetch_and_store_detail(conn, client: httpx.Client, article_url: str, article_id: str) -> None:
    """
    新規投稿の個別ページを取得し、出品者情報とともに保存する (フロー⑨⑩)。

    呼び出し順序 (repository/article_repository.py のdocstring参照):
        1. seller_repository.upsert_seller() で出品者を先に登録
        2. article_repository.upsert_from_detail_article() で投稿に紐付け

    2026-09-06 修正 (重要バグ修正): 以前はネットワークエラー
    (FetchError) しか捕捉しておらず、HTMLパース中の例外や
    article_id不一致によるDB更新スキップが原因で、この関数の呼び出し元
    (run_scan の for ループ) が丸ごと例外で停止することがあった。

    影響: 一覧に52件の投稿があるうち、たまたま1件でも個別ページの
    取得・パースに失敗すると、それ以降に処理されるはずだった投稿の
    個別ページ情報 (投稿日・更新日・出品者情報等) が一切取得されない
    まま巡回全体が中断する不具合があった (ユーザー報告: 「個別ページを
    開いても投稿日・最終更新日が表示されない」の根本原因)。
    一覧由来の情報は先に保存済みのため投稿自体は一覧に表示されるが、
    詳細情報だけ欠落する、という分かりにくい形で症状が出ていた。

    修正方針: この関数はあくまで「1件の投稿の個別ページ処理」の
    単位であるべきで、ここで起きた問題が他の投稿の処理に波及しては
    ならない (仕様書5-4「取得漏れゼロの原則」)。関数全体を
    try/except Exception で包み、どの段階で何が起きても呼び出し元の
    ループへ例外を伝播させない。FetchErrorは既知の失敗パターン
    (ネットワーク不調・404等) として個別のログメッセージを出す。
    """
    try:
        detail_html = fetch_html(client, article_url)
        logger.info("個別ページ取得成功 (%s): %d文字", article_id, len(detail_html))

        detail = parse_detail_page(detail_html)
        # 2026-09-07新設: 診断用ログ。「投稿日・最終更新日が表示され
        # ない」不具合の調査で、これまでlogger.warning/exceptionが
        # 一切発火しないまま(=例外は起きていない)created_datetimeが
        # nullのまま保存される事例が複数報告されたため、パース結果の
        # 中身自体を毎回ログに残すようにした。history_datetimesが
        # 空の辞書 {} で返ってきている場合、parse_detail_page内の
        # 正規表現がそのHTMLの書式に一致していないことが分かる。
        logger.info(
            "個別ページパース結果 (%s): article_id=%s, history_datetimes=%s",
            article_id, detail.article_id, detail.history_datetimes,
        )

        # 2026-09-06新設: 詳細ページからパースしたarticle_idが、
        # 呼び出し元が一覧から得たarticle_idと一致するか検証する。
        # 一致しない場合、upsert_from_detail_article()はdetail.article_id
        # の方でUPDATEを試みるため、該当行が存在しなければ何も更新され
        # ないまま静かに終わる (「取得したのに保存されない」という
        # 気づきにくい失敗)。ここで検知してログに残す。
        if detail.article_id is not None and detail.article_id != article_id:
            logger.warning(
                "個別ページのarticle_idが一覧と一致しません (一覧: %s, 詳細ページ: %s)。"
                "URL: %s",
                article_id, detail.article_id, article_url,
            )

        seller_id = None
        if detail.seller is not None and detail.seller.seller_id is not None:
            upsert_seller(conn, detail.seller)
            seller_id = detail.seller.seller_id

        # 2026-09-06: 一覧側で確定済みのarticle_idを明示的に渡す
        # (detail.article_idのパースがずれていても正しい行を更新できる
        # ようにするため。上のif文で不一致は検知・ログ済み)。
        upsert_from_detail_article(conn, detail, seller_id=seller_id, article_id=article_id)
        logger.info("個別ページ保存完了 (%s)", article_id)
    except FetchError as e:
        # 個別ページの取得に失敗しても、一覧由来のデータは既に保存済みなので
        # 「取得漏れ」そのものにはならない。ログに残して処理は継続する。
        logger.warning("個別ページの取得に失敗しました (%s): %s", article_id, e)
    except Exception:
        # HTMLパース失敗・article_id抽出失敗(ValueError)・想定外のDB
        # エラー等、fetch_html以外のあらゆる例外をここで止める。
        # 一覧由来のデータは既に保存済みなので、この投稿の詳細情報が
        # 欠けるだけで済み、後続の投稿の処理には影響しない。
        logger.exception(
            "個別ページの処理中にエラーが発生しました (%s): %s", article_id, article_url
        )


def confirm_single_missing_article(conn, client: httpx.Client, article_id: str) -> str | None:
    """
    'missing' 状態の投稿1件について、個別ページへ直接アクセスして
    確定判定する (2026-09-04 新設。旧run_missing_checkのバルク版を廃止)。

    廃止の経緯 (ユーザーとの設計合意事項):
        旧run_missing_check()は'missing'状態の投稿すべてに対して
        機械的に個別ページアクセスを行っており、巡回1回あたりの
        アクセス数が実質倍増しうる設計だった。

        ジモティーの性質 (良品はすぐ取引終了になる／価格更新等の動きが
        あれば一覧の上位に再出現する) を踏まえると、「一覧から消えた
        投稿すべてを毎回自動で確認しにいく」精度は過剰であり、
        「終了」タブに表示され続けている間はアクセスせず放置し、
        保存期間削除 (repository.article_retention_repository参照)
        で自動的に整理する方が、アクセス数を増やさずに済む。

        代わりに、ユーザーが「終了」タブを見て興味を持った投稿だけ、
        この関数で1件ずつ個別に確認できるようにした
        (api/main.py の POST /api/articles/{article_id}/confirm-status)。
        加えて2026-09-11の「終了」タブ再設計により、「確定終了候補」
        (missing_kind='confirmed_closed') はscheduler.job.
        run_scan_with_range() がこの関数を使って自動的に確認する
        経路も追加された (詳細はそちらのdocstring参照)。

    Args:
        article_id: 対象の投稿ID ('missing'状態であること)

    Returns:
        "restored" | "closed" | None (対象がmissing状態でない場合)
    """
    row = conn.execute(
        "SELECT url FROM active_articles WHERE article_id = ? AND article_status = 'missing'",
        (article_id,),
    ).fetchone()
    if row is None:
        logger.info("確認スキップ: missing状態の投稿ではありません: %s", article_id)
        return None

    url = row["url"]

    try:
        detail_html = fetch_html(client, url)
        still_exists = True
    except FetchError as e:
        logger.info("個別ページにアクセスできませんでした (終了と推定): %s (%s)", article_id, e)
        still_exists = False
        detail_html = None

    is_closed = False
    if still_exists and detail_html is not None:
        detail = parse_detail_page(detail_html)
        is_closed = detail.is_closed

    result = confirm_missing_article(conn, article_id, still_exists=still_exists, is_closed=is_closed)
    conn.commit()

    if result == "restored":
        logger.info("復帰: %s (まだ受付中でした)", article_id)
    else:
        logger.info("終了確定: %s", article_id)

    return result


def fetch_seller_profile_on_demand(conn, client: httpx.Client, seller_id: str) -> bool:
    """
    出品者のプロフィールページをオンデマンドで取得し、sellersテーブルを更新する。

    「見るまでは取らない」設計 (2026-08-30 設計合意事項)。
    run_scan() は出品者の新規登録 (upsert_seller、個別ページ由来の
    情報のみ) までしか行わず、プロフィールページへの追加アクセスは
    一切しない。プロフィールページの取得は、この関数を呼んだ時
    (= UIで「続きを読む」または「更新」が押された時) にのみ発生する。

    呼び出し元 (api/main.py) が「続きを読む」(未取得時のみ) と
    「更新」(常に取得) の判定を行い、取得すべきと判断した場合にのみ
    この関数を呼ぶ。この関数自体は無条件に取得する
    (= profile_fetched_at の有無による分岐はここでは行わない)。

    2026-09-04 追加 → 同日に方針転換: 当初は投稿一覧が11件以上ある
    出品者向けに、next_page_url を辿って全ページ合算する実装を
    入れていた (MAX_PROFILE_PAGES=20)。しかし恒常的に数百件規模の
    出品を抱える出品者では「更新」1回につき最大20アクセスが発生し、
    低頻度アクセスの原則を実質的に破ってしまうと判断し撤回した。
    現在は1ページ目のみを取得する。

    合計出品数 (post_count / other_articles_total_count) は1ページ目
    の「全◯件中」という表記から取得できるため、この方式でも「今
    何件出品しているか」は正確に分かる。「どんな商品を出しているか」
    は1ページ目 (最終更新日順で最大10件程度) の概観で十分とし、
    全件の一覧化は目的としない。このソフトはログインも問い合わせも
    行わず、監視・概覧の補助に徹する設計であるため、この妥協は
    許容する。

    Args:
        conn: DBコネクション
        client: httpx.Client (呼び出し元が生成・クローズを管理する)
        seller_id: 対象の出品者ID

    Returns:
        bool: 取得・更新に成功したら True。
              出品者がDBに存在しない、seller_profile_urlが未設定、
              または取得中にFetchErrorが発生した場合は False。
              (呼び出し元がHTTPステータスに変換する)
    """
    row = conn.execute(
        "SELECT seller_profile_url FROM sellers WHERE seller_id = ?", (seller_id,)
    ).fetchone()
    if row is None:
        logger.info("プロフィール取得スキップ: 出品者が未登録です: %s", seller_id)
        return False

    profile_url = row["seller_profile_url"]
    if not profile_url:
        logger.info("プロフィール取得スキップ: seller_profile_urlが未設定です: %s", seller_id)
        return False

    try:
        profile_html = fetch_html(client, profile_url)
    except FetchError as e:
        logger.warning("プロフィールページの取得に失敗しました: %s (%s)", seller_id, e)
        return False

    # 2026-09-04: プロフィールページは常に1ページ目のみ取得する
    # (次ページを辿らない)。合計出品数は profile.other_articles_total_count
    # ("全◯件中"の表記) から取得済みなので、これ以上のアクセスは
    # 「1出品者につき1回」という低頻度アクセスの原則を守るために行わない。
    profile = parse_profile_page(profile_html)

    upsert_seller_profile(conn, seller_id, profile)
    # 2026-09-04: プロフィールページの投稿一覧 (1ページ目、最大10件程度)
    # で seller_other_articles を洗い替えする。「この出品者の他の投稿」
    # 表示に、監視ツールが偶然検知した投稿だけでなく公式プロフィール
    # ページの投稿一覧 (概観分) を反映するため。全件ではない点は
    # UI側 (SellerPanel.jsx) で total_count と表示件数の差として示す。
    replace_seller_other_articles(conn, seller_id, profile)
    conn.commit()
    return True
