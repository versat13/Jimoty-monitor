"""
active_articles テーブルへの読み書きを担うrepository。

根拠:
- 仕様書 v1.0 5-3 (active_articles / price_history)
- 仕様書 v1.0 6章 フロー⑧⑫
- 2026-08-23 のユーザーとの設計合意:
    「一覧から消えた投稿」は即削除ではなく missing 状態を経由し、
    次回巡回で個別ページ確認してから確定させる (db/schema.sql 冒頭コメント参照)
    再浮上時の差分検知は価格変化のみ (タイトル・説明文は追わない)

このモジュールはDBへの読み書きのみを担当し、HTTP取得やパース処理は
含めない (scraper/, filters/ の責務)。呼び出し元 (scheduler/job.py、
未実装) が「パース結果を渡す→保存する」という順で使うことを想定する。
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from scraper.detail_parser import DetailArticle
from scraper.list_parser import ListArticle

SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"

logger = logging.getLogger(__name__)

# 2026-09-07 追加: scan_state テーブルへの列追加マイグレーション。
#
# schema.sql は CREATE TABLE IF NOT EXISTS で読み込まれるため、
# 既に scan_state テーブルが存在するDBファイル (旧バージョンで
# 運用開始済みの環境) では、schema.sql 側に列を増やしても
# 実行時にはテーブルへ反映されない。そのため起動時に
# ALTER TABLE ... ADD COLUMN を試み、「既に列がある」エラー
# (旧DBに対する初回マイグレーション後の2回目以降の起動、および
# 新規DBでschema.sqlが列付きで作成された場合) は無視する。
_SCAN_STATE_MIGRATION_COLUMNS = [
    ("region_type", "TEXT NOT NULL DEFAULT 'prefecture_city'"),
    ("area_portal_id", "TEXT"),
    ("distance_km", "INTEGER"),
    ("scan_range_mode", "TEXT NOT NULL DEFAULT 'pages'"),
    ("scan_range_value", "INTEGER NOT NULL DEFAULT 1"),
    # 2026-09-13変更: db/schema.sql側はDEFAULT 30に変更したが、この
    # ALTER TABLE ADD COLUMN文自体は「まだ列が存在しない既存DB」に
    # 対してのみ実行される (「既に列がある」エラーはexcept節で無視する
    # 方式。このファイル冒頭のコメント参照)。つまりこのDEFAULT句が
    # 実際に使われるのは「この列が一度も存在しなかった非常に古いDB」
    # だけであり、「既にこの列を持つが値がNULL (=自動更新オフ)」の
    # 既存ユーザーには一切影響しない。これは意図的な判断:
    # NULLが「まだ一度も設定したことがない」のか「意図的にオフに
    # した」のかをDB上で区別する方法がなく、既存ユーザーの意図的な
    # オフ設定を勝手に30分へ変更するのは危険なため、新規DBにのみ
    # このデフォルト値を適用する (repository/scan_settings_repository.py
    # の DEFAULT_AUTO_SCAN_INTERVAL_MINUTES も参照。そちらは
    # 「scan_stateに行が1つも無い」場合の初回行作成時に使われる、
    # 実質的にこちらと同じ意図の値)。
    ("auto_scan_interval_minutes", "INTEGER DEFAULT 30"),
    # 2026-09-10 追加: 巡回中の進捗表示用 (BottomNav付近のUI)。
    # 巡回開始時にNULLへリセットし、ページ単位commitのタイミングで
    # 都度更新する。巡回が完了/停止/エラー終了したらまたNULLへ戻す
    # (「更新中でないのに進捗が残っている」状態を防ぐため)。
    # scan_progress_max_pageは取得範囲が'pages'モードのときのみ値が
    # 入る ('days'モードは何ページで終わるか事前に分からないため、
    # UI側は上限不明の不定形バー表示にする)。
    ("scan_progress_current_page", "INTEGER"),
    ("scan_progress_max_page", "INTEGER"),
    ("scan_progress_seen_count", "INTEGER"),
    # 2026-09-11 追加: 保存期間削除の設定。db/schema.sql の同名列と
    # 同じ意味を持つ。詳細はそちらのコメント参照。
    ("retention_enabled", "INTEGER NOT NULL DEFAULT 1"),
    ("retention_days", "INTEGER NOT NULL DEFAULT 7"),
    # 2026-09-15 追加: トースト通知・ブラウザ通知用。直近の巡回
    # (run_scan_with_range) で「検索」タブ (pickup_search) の条件に
    # ヒットした新規投稿のarticle_idをJSON配列文字列として保存する。
    # Discordへの通知試行対象と同じ集合。自動更新 (サーバー側定期実行、
    # scheduler/auto_refresh.py) はScanResultを誰にも返さずバック
    # グラウンドで完結するため、手動・自動どちらの巡回結果もフロント
    # から見えるようにするには、DBを経由する必要がある。
    # GET /api/scan-status がこれを読み、last_notified_atと合わせて
    # 返す。フロント (ScanStatusContext) はlast_notified_atが前回の
    # ポーリングから変化したときだけ、この一覧をトースト/ブラウザ
    # 通知の対象として扱う (同じ内容を毎回のポーリングで重複通知
    # しないようにするため)。
    ("last_notified_article_ids", "TEXT"),
    ("last_notified_at", "TEXT"),
]

# 2026-09-07 追加: active_articles.title_changed_at のマイグレーション
# (タイトル変更の反映機能。理由は _SCAN_STATE_MIGRATION_COLUMNS と同様、
# 既存DBファイルには schema.sql の列追加が反映されないため)。
_ACTIVE_ARTICLES_MIGRATION_COLUMNS = [
    ("title_changed_at", "TEXT"),
    # 2026-09-10 追加: 価格変更の累計回数 (このツールで監視を始めてから
    # 確認できた回数)。ユーザーとの合意事項:
    #   - 一覧の投稿カードに「n回目の値変更」ラベルを常時表示する
    #     (title_changed_atのように「直近の巡回のみ」ではなく、一度
    #     値が変わったら以後ずっと表示され続ける)。
    #   - 値上げ/値下げの方向性 (UP/DOWN) は表示しない。回数のみ。
    #   - 「監視範囲外」→自動確認でactiveに戻った場合もリセットしない
    #     (監視開始からの累計として保持し続ける)。
    # price_history に行が追加されるたびに (upsert_from_list_article)
    # +1する。0は「一度も値変更が確認されていない」ことを表し、
    # その場合はUI側でラベル自体を表示しない。
    ("price_change_count", "INTEGER NOT NULL DEFAULT 0"),
    # 2026-09-11 追加: 「終了」タブ再設計 (確定終了/監視範囲外の区別)。
    # db/schema.sql の CHECK制約付き定義と同じ意味を持つ列。
    # 詳細はそちらのコメント参照。
    # 注意: SQLiteのALTER TABLE ADD COLUMNはCHECK制約を追加できない
    # ため、この列に対する値の妥当性チェックはアプリケーション層
    # (repository/article_repository.py の各関数) で保証する。
    ("missing_kind", "TEXT"),
]

# 2026-09-08 追加: ng_categories.category_level のマイグレーション
# (NGカテゴリの階層区別。大カテゴリ/ジャンル/サブジャンルのどれとして
# 登録されたかを記録する。理由は上記と同様)。
_NG_CATEGORIES_MIGRATION_COLUMNS = [
    ("category_level", "TEXT NOT NULL DEFAULT 'leaf'"),
]

# 2026-09-15 追加: discord_notification_settings へのアプリ内トースト・
# ブラウザ通知トグルのマイグレーション (理由は上記と同様、既存DBには
# schema.sql の列追加が反映されないため)。デフォルトは両方とも無効
# (0) とし、既存ユーザーが何もしなくても通知が急に増えることがない
# ようにしている。
_DISCORD_NOTIFICATION_SETTINGS_MIGRATION_COLUMNS = [
    ("in_app_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("browser_enabled", "INTEGER NOT NULL DEFAULT 0"),
]


def _migrate_scan_state_columns(conn: sqlite3.Connection) -> None:
    for column, ddl in _SCAN_STATE_MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE scan_state ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError as e:
            # "duplicate column name" は既に列が存在する場合の想定内エラー。
            # それ以外の OperationalError (テーブル自体が無い等) は
            # 呼び出し元 (get_connection) が schema.sql を先に流すため
            # 通常発生しないが、念のため文言を確認して未知のエラーのみ再送出する。
            if "duplicate column name" not in str(e):
                raise


def _migrate_active_articles_columns(conn: sqlite3.Connection) -> None:
    for column, ddl in _ACTIVE_ARTICLES_MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE active_articles ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise


def _migrate_ng_categories_columns(conn: sqlite3.Connection) -> None:
    for column, ddl in _NG_CATEGORIES_MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE ng_categories ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise


def _migrate_discord_notification_settings_columns(conn: sqlite3.Connection) -> None:
    for column, ddl in _DISCORD_NOTIFICATION_SETTINGS_MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE discord_notification_settings ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    DB接続を取得し、スキーマが未作成なら作成する。

    Args:
        db_path: SQLiteファイルパス。":memory:" もテスト用に使用可能。

    2026-09-10変更: journal_modeをWAL (Write-Ahead Logging) にした。
    自動更新 (サーバー側定期実行) の追加により、スキャン処理 (長時間の
    書き込みトランザクション) と設定変更等の他の書き込みが同時に
    走る場面が増えたため。WALモードでは読み取りと書き込みが競合
    しにくくなり、"database is locked" エラーの発生頻度を大幅に
    下げられる (完全に無くなるわけではないため、scheduler/job.py 側の
    トランザクション分割と合わせて対策する)。

    ":memory:" はプロセス内でのみ有効な一時DBであり、複数接続で
    共有されない (テストでのみ使用) ため、WAL化の対象外とする
    (sqlite3はそもそも:memory:のWAL化を認めない)。

    busy_timeoutも合わせて延長する。デフォルトは5秒だが、スキャン
    処理の1回のトランザクションがそれより長くなる場合があるため、
    他接続からの書き込みがすぐ失敗しないよう余裕を持たせる。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    _migrate_scan_state_columns(conn)
    _migrate_active_articles_columns(conn)
    _migrate_ng_categories_columns(conn)
    _migrate_discord_notification_settings_columns(conn)
    conn.commit()

    return conn


@dataclass
class UpsertResult:
    """
    一覧ページ由来のデータをDBに反映した結果。

    フロー⑧「DB照合（article_idの新規／既存判定）」の結果を表す。
    is_new=True の場合、呼び出し元は続けてフロー⑨⑩(個別ページ取得)を
    行う必要がある。
    """

    article_id: str
    is_new: bool
    price_changed: bool
    old_price: int | None = None
    new_price: int | None = None
    # 2026-09-07 追加: タイトル変更の反映 (履歴は持たず、最新値への
    # 上書きのみ。ユーザーとの合意事項)。
    title_changed: bool = False
    old_title: str | None = None
    new_title: str | None = None


def upsert_from_list_article(
    conn: sqlite3.Connection, article: ListArticle, display_order: int | None = None
) -> UpsertResult:
    """
    一覧ページのパース結果 (ListArticle) をDBに反映する (フロー②〜⑧)。

    - 新規投稿 (article_idが未登録): active_articles に一覧由来の情報のみで
      新規行を作成する。is_new=True を返すので、呼び出し元は個別ページ取得
      (フロー⑨⑩) に進み、upsert_from_detail_article() で情報を追加すること。
    - 既存投稿: 価格変化・タイトル変化を確認する。
        - 価格変化があれば price_history に記録した上で active_articles の
          price を更新する (仕様書フロー⑧の通り)。
        - タイトル変化があれば list_title を最新値に上書きする。
          2026-09-07 変更 (ユーザーとの合意事項): ジモティーの運用上、
          既存投稿のタイトルが「引取が決まりました！○○」「最終値下げ！
          ○○」のように後から書き換えられることがある。価格ほど重要
          ではないため変遷の履歴 (price_historyのようなテーブル) は
          持たず、単純に最新のタイトル文字列へ上書きするに留める
          (個別ページへの再アクセスは発生させない。一覧のタイトル
          文字列同士を比較するだけ)。変更があったこと自体は
          title_changed_at に記録し、UIで軽い変更表示に使えるようにする
          (旧: 2026-08-23合意で「タイトル等は更新しない」としていたが、
          今回の方針変更によりタイトルのみ更新対象に追加した。他の
          一覧由来フィールド (area等) は引き続き更新しない)。
        article_status が 'missing' だった場合は 'active' に復帰させ、
        article_status_history にも記録する (一覧に再出現＝生存確認のため)。

    Args:
        display_order: 直近の巡回で一覧に出現した順番 (2026-08-24 新設)。
            「公式サイトと同じ並び順で見たい」というユーザー要望に対応する
            ためのフィールド。呼び出し元 (scheduler.job.run_scan) が
            一覧のenumerate順を渡す想定。新規・既存どちらの場合も
            直近の巡回結果で上書きする (常に「最新の巡回での並び順」を
            反映するため)。
    """
    cursor = conn.execute(
        "SELECT price, list_title, article_status FROM active_articles WHERE article_id = ?",
        (article.article_id,),
    )
    existing = cursor.fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO active_articles (
                article_id, url, list_title, price, prefecture,
                area_id, area_name, station_id, station_name,
                category_id, category_name, tags, description_short,
                updated_date_raw, created_date_raw, favorite_count,
                thumbnail_url, is_pr_slot, article_status,
                first_seen_at, last_seen_at, display_order
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'active', datetime('now'), datetime('now'), ?
            )
            """,
            (
                article.article_id, article.url, article.list_title, article.price,
                article.prefecture, article.area_id, article.area_name,
                article.station_id, article.station_name, article.category_id,
                article.category_name, json.dumps(article.tags, ensure_ascii=False),
                article.description_short, article.updated_date_raw,
                article.created_date_raw, article.favorite_count,
                article.thumbnail_url, int(article.is_pr_slot), display_order,
            ),
        )
        return UpsertResult(article_id=article.article_id, is_new=True, price_changed=False)

    old_price = existing["price"]
    price_changed = old_price != article.price

    if price_changed:
        conn.execute(
            "INSERT INTO price_history (article_id, old_price, new_price) VALUES (?, ?, ?)",
            (article.article_id, old_price, article.price),
        )

    old_title = existing["list_title"]
    title_changed = old_title != article.list_title

    was_missing = existing["article_status"] == "missing"

    # 2026-09-10変更: 価格変化があった回のみ price_change_count を+1する。
    # 以前はtitle_changed/price_changedの組み合わせで4パターンの
    # UPDATE文に分岐していたが、SQLのCASE式で1本にまとめた方が
    # 見通しが良いため整理した。title_changed_atは変わらない場合、
    # SQLite上「既存の値で自分自身に代入する」形になり実質的な
    # 変化はない (COALESCE等を使わず既存値をそのまま再設定するだけ)。
    conn.execute(
        """
        UPDATE active_articles
        SET price = ?,
            list_title = ?,
            title_changed_at = CASE WHEN ? THEN datetime('now') ELSE title_changed_at END,
            price_change_count = price_change_count + CASE WHEN ? THEN 1 ELSE 0 END,
            article_status = 'active',
            last_seen_at = datetime('now'),
            display_order = ?
        WHERE article_id = ?
        """,
        (
            article.price, article.list_title,
            title_changed, price_changed,
            display_order, article.article_id,
        ),
    )

    if was_missing:
        _record_status_change(conn, article.article_id, "missing", "active", "restored_still_active")

    return UpsertResult(
        article_id=article.article_id,
        is_new=False,
        price_changed=price_changed,
        old_price=old_price,
        new_price=article.price,
        title_changed=title_changed,
        old_title=old_title,
        new_title=article.list_title,
    )


def upsert_from_detail_article(
    conn: sqlite3.Connection,
    detail: DetailArticle,
    seller_id: str | None,
    *,
    article_id: str | None = None,
) -> None:
    """
    個別ページのパース結果 (DetailArticle) を、既存の active_articles 行に
    追記する (フロー⑨⑩)。upsert_from_list_article() で作成済みの行が
    存在することを前提とする。

    2026-09-08 バグ修正: 従来はcategory_id/category_name (詳細カテゴリ)
    をこの関数で更新しておらず、一覧ページ由来の値のまま固定されて
    いた。一覧ページはカテゴリ・ジャンル・サブジャンルを区別せず
    「一つのカテゴリ」としてしか取得できないため、精度の面で詳細
    ページ (BreadcrumbList由来、2026-09-08修正済み) の値の方が
    優れている。詳細ページ取得後はcategory_id/category_nameも
    detail側の値で上書きするようにした。

    重要: seller_id は sellers テーブルへの外部キー制約を持つため、
    この関数を呼ぶ前に repository.seller_repository.upsert_seller() で
    出品者を先に登録しておくこと。呼び出し順序:
        1. seller_repository.upsert_seller(conn, detail.seller)
        2. article_repository.upsert_from_detail_article(conn, detail, detail.seller.seller_id)

    Args:
        article_id: UPDATE対象の行を決めるためのID。省略時は
            detail.article_id (個別ページ側のパース結果) を使う。
            2026-09-06新設: 呼び出し元 (scheduler.job._fetch_and_store_detail)
            が一覧ページ側で既に確定させているarticle_idをこちらで
            明示的に渡せるようにした。個別ページ側のパースが何らかの
            理由でずれた場合でも、一覧側の正しいIDで確実に該当行を
            更新できるようにするための安全策。両者が食い違う場合の
            検知・ログ出力は呼び出し元の責務とする。
    """
    target_id = article_id if article_id is not None else detail.article_id
    if target_id is None:
        raise ValueError(
            "更新対象のarticle_idを特定できないため保存できません "
            "(引数article_id・DetailArticle.article_idのいずれもNone)"
        )

    created_dt = detail.history_datetimes.get("作成")
    updated_dt = detail.history_datetimes.get("更新")

    cursor = conn.execute(
        """
        UPDATE active_articles
        SET full_title = ?, description_full = ?, category_id = ?, category_name = ?,
            category_mid_id = ?, category_mid_name = ?,
            category_parent_id = ?, category_parent_name = ?,
            city = ?, ward = ?, town = ?, railway_line = ?, is_closed = ?,
            created_datetime = ?, updated_datetime = ?, seller_id = ?,
            detail_fetched_at = datetime('now')
        WHERE article_id = ?
        """,
        (
            detail.full_title, detail.description_full, detail.category_id, detail.category_name,
            detail.category_mid_id, detail.category_mid_name,
            detail.category_parent_id, detail.category_parent_name,
            detail.city, detail.ward, detail.town, detail.railway_line, int(detail.is_closed),
            created_dt.isoformat() if created_dt else None,
            updated_dt.isoformat() if updated_dt else None,
            seller_id, target_id,
        ),
    )

    # 2026-09-07新設 (重要な診断ログ): SQLiteのUPDATE文は、WHERE条件に
    # 一致する行が0件でも例外を投げない。「取得・パースは成功したのに
    # DBには反映されていない」という不具合の調査で、この「静かな
    # 0件更新」が疑われたため、rowcountを確認してログに残すように
    # した。0件だった場合、target_id (呼び出し元が指定したarticle_id)
    # が active_articles に実在しないことを意味し、原因は
    # upsert_from_list_article() 側でのarticle_id不一致や、
    # 呼び出し順序の問題に絞り込める。
    if cursor.rowcount == 0:
        logger.warning(
            "upsert_from_detail_article: UPDATE対象の行が見つかりませんでした "
            "(article_id=%s)。upsert_from_list_article()が先に実行され、"
            "同じarticle_idで行が作成されているか確認してください。",
            target_id,
        )


def mark_missing_articles(
    conn: sqlite3.Connection,
    seen_article_ids: set[str],
    *,
    max_seen_display_order: int | None = None,
) -> list[str]:
    """
    今回の巡回で一覧に出現しなかった投稿を 'missing' 状態にする。

    2026-08-23 の設計合意により、これは削除ではなく状態遷移に留める。

    2026-09-11 変更 (「終了」タブ再設計):
    以前は一律 missing 状態にするだけだったが、これには「本当に終了した
    投稿」と「取得範囲 (ページ数/日数設定) からたまたま押し出されただけの
    投稿」が区別なく混ざってしまう問題があった。max_seen_display_order
    (今回の巡回全体で実際に見えた投稿のdisplay_orderの最大値) を渡すと、
    消えた投稿を以下のように分類し missing_kind に記録する:

      - 消えた投稿の旧display_orderが max_seen_display_order 以下
        (=本来なら今回の巡回でも見えるはずの順位にいたのに見えなく
        なった) → missing_kind='confirmed_closed' (「終了(確定)」候補)。
        呼び出し元 (scheduler.job.run_scan_with_range) はこれらに対し、
        個別ページへの再アクセスによる確定判定を行う責務を持つ
        (この関数自体はネットワークアクセスを行わない)。
      - それ以外 (旧display_orderが max_seen_display_order より大きい、
        またはmax_seen_display_order自体がNone=今回の巡回で1件も
        投稿を取得できなかった場合) → missing_kind='range_uncertain'
        (「監視範囲外」。取得範囲の外に押し出されただけの可能性がある
        ため、自動での個別ページ再アクセスは行わない)。
      - 旧display_orderがNULL (display_order導入前の古いデータ等)
        → 安全側に倒し 'range_uncertain' として扱う。

    max_seen_display_order を渡さない (None のまま呼ぶ) 場合は、
    全件 'range_uncertain' として扱う (後方互換・テスト用)。

    Args:
        seen_article_ids: 今回の巡回で一覧に存在した article_id の集合
        max_seen_display_order: 今回の巡回で実際に見えた投稿の
            display_orderの最大値。scheduler.job.run_scan_with_range()
            がページ横断で集計した値を渡す。

    Returns:
        新たに missing 状態になった article_id のリスト
        (missing_kindの種類は問わない。呼び出し元が別途
        get_confirmed_closed_candidates() 等で絞り込むこと)
    """
    cursor = conn.execute(
        "SELECT article_id, display_order FROM active_articles WHERE article_status = 'active'"
    )
    currently_active = {row["article_id"]: row["display_order"] for row in cursor.fetchall()}

    newly_missing_ids = set(currently_active.keys()) - seen_article_ids
    if not newly_missing_ids:
        return []

    for aid in newly_missing_ids:
        old_display_order = currently_active[aid]
        if (
            old_display_order is not None
            and max_seen_display_order is not None
            and old_display_order <= max_seen_display_order
        ):
            kind = "confirmed_closed"
        else:
            kind = "range_uncertain"

        conn.execute(
            """
            UPDATE active_articles
            SET article_status = 'missing', missing_since = datetime('now'), missing_kind = ?
            WHERE article_id = ?
            """,
            (kind, aid),
        )

    newly_missing = list(newly_missing_ids)
    for aid in newly_missing:
        _record_status_change(conn, aid, "active", "missing", "list_not_found")

    return newly_missing


def get_missing_articles(
    conn: sqlite3.Connection, *, missing_kind: str | None = None
) -> list[sqlite3.Row]:
    """
    'missing' 状態の投稿を取得する。

    Args:
        missing_kind: 指定すると 'confirmed_closed' または
            'range_uncertain' のいずれかで絞り込む。None (既定) なら
            未判定分も含めた全件を返す (後方互換)。

    2026-09-11 変更: 「終了」タブ再設計に伴い missing_kind 引数を
    追加した。scheduler.job.run_scan_with_range() は
    missing_kind='confirmed_closed' (自動確認の対象) だけを取得する
    想定。UIの「終了」タブは絞り込みなしの全件 (confirmed_closed +
    range_uncertain) を表示する。
    """
    if missing_kind is not None:
        cursor = conn.execute(
            "SELECT * FROM active_articles WHERE article_status = 'missing' AND missing_kind = ?",
            (missing_kind,),
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM active_articles WHERE article_status = 'missing'"
        )
    return cursor.fetchall()


def confirm_missing_article(
    conn: sqlite3.Connection, article_id: str, *, still_exists: bool, is_closed: bool
) -> str:
    """
    'missing' 状態の投稿を、個別ページへの直接アクセス結果を踏まえて確定させる。

    Args:
        article_id: 対象の投稿ID
        still_exists: 個別ページに正常にアクセスできたか (404等でなければTrue)
        is_closed: DetailArticle.is_closed の値
            (「お問い合わせの受付は終了いたしました。」の検出結果)

    Returns:
        確定後の状態を表す文字列: "closed" | "restored"

    判定ロジック:
        - ページが存在しない (still_exists=False、投稿者による削除と推定)
          → 終了確定
        - ページは存在するが is_closed=True (取引成立と推定)
          → 終了確定
        - ページが存在し、まだ受付中 (単に一覧の固定件数から
          押し出されていただけ)
          → active に復帰

    2026-09-11 変更 (「終了」タブ再設計、ユーザーとの合意事項):
    以前は「終了確定」の場合 active_articles から物理削除していたが
    (戻り値も"deleted")、この変更で削除せず missing_kind=
    'confirmed_closed' のまま残すようにした (戻り値も"closed"に変更)。
    「いつまで一覧に残すか」は削除ではなく、別途
    repository.article_retention_repository の保存期間削除機能
    (ユーザーが日数を設定でき、article_status='missing'の投稿は
    missing_since基準で判定する) に委譲する。
    """
    if not still_exists or is_closed:
        reason = "detail_404" if not still_exists else "detail_confirmed_closed"
        conn.execute(
            """
            UPDATE active_articles
            SET missing_kind = 'confirmed_closed'
            WHERE article_id = ?
            """,
            (article_id,),
        )
        _record_status_change(conn, article_id, "missing", "missing", reason)
        return "closed"

    conn.execute(
        """
        UPDATE active_articles
        SET article_status = 'active', missing_since = NULL, missing_kind = NULL,
            last_seen_at = datetime('now')
        WHERE article_id = ?
        """,
        (article_id,),
    )
    _record_status_change(conn, article_id, "missing", "active", "restored_after_detail_check")
    return "restored"


def update_filter_flags(
    conn: sqlite3.Connection,
    article_id: str,
    *,
    is_hidden_by_keyword: bool,
    is_hidden_by_category: bool,
    is_hidden_by_seller_rule: bool,
    matched_ng_keywords: list[str] | None = None,
) -> None:
    """
    フロー⑦⑪の判定結果 (filters/keyword_filter.py, category_filter.py,
    repository/seller_repository.get_seller_rule() の結果) を
    active_articles に反映する。

    仕様書5-4の原則により、これらのフラグは表示層のフィルタとしてのみ
    使うこと。この関数はフラグを立てるだけで、行の削除やデータの
    欠落は一切発生しない。
    """
    conn.execute(
        """
        UPDATE active_articles
        SET is_hidden_by_keyword = ?,
            is_hidden_by_category = ?,
            is_hidden_by_seller_rule = ?,
            matched_ng_keywords = ?
        WHERE article_id = ?
        """,
        (
            int(is_hidden_by_keyword),
            int(is_hidden_by_category),
            int(is_hidden_by_seller_rule),
            json.dumps(matched_ng_keywords or [], ensure_ascii=False),
            article_id,
        ),
    )


def mark_notified(conn: sqlite3.Connection, article_id: str) -> None:
    """
    フロー⑬の通知判定後、通知済みであることを記録する
    (同じ投稿への重複トースト通知を防ぐため)。
    """
    conn.execute(
        "UPDATE active_articles SET last_notified_at = datetime('now') WHERE article_id = ?",
        (article_id,),
    )


def purge_expired_articles(conn: sqlite3.Connection, retention_days: int) -> int:
    """
    保存期間を過ぎた投稿を削除する (2026-09-11新設。旧
    purge_expired_missing_articlesを置き換え、対象をmissingだけでなく
    activeも含む全ステータスに拡張した)。

    設計思想・経緯 (ユーザーとの合意事項):
        以前は「'missing'になってから21日固定」で削除する仕組み
        だったが、これを以下のように一本化した:
          - 保存期間 (日数) はユーザーが自由に設定できる
            (repository.scan_settings_repository の
            retention_enabled/retention_days参照。呼び出し元
            (scheduler.job.run_scan_with_range) がこれを読んで
            この関数に渡す)。
          - active (受付中) の投稿にも一律適用し、一覧が際限なく
            溜まり続けるのを防ぐクリーンアップとして機能させる。
          - 判定基準はarticle_statusに応じて自動的に使い分ける:
              article_status='active'  : last_seen_at
                  (最後に一覧で存在を確認できた日時) 基準。
                  巡回を継続している限りactiveな投稿は毎回
                  last_seen_atが更新され続けるため、実質
                  「最後に確認できてから○日、一覧に出現しなかったら
                  削除」という安全側の挙動になる
                  (投稿自体の値下げ・タイトル変更の有無では判定
                  しない。詳細はこの関数のユーザー合意メモ参照:
                  updated_datetimeは新規登録時にしか書き込まれず
                  値下げ等で更新されないため、「投稿の更新日」を
                  正確に表す列として使うにはデータ設計の変更が
                  別途必要と判断し、今回はlast_seen_atを採用した)。
              article_status='missing' : missing_since
                  (一覧から消えた巡回時刻) 基準。旧ルールと同じ。

    2026-09-13変更 (監視中の投稿を削除対象から除外、ユーザーとの
    合意事項):
        以前はwatched_articles (投稿単位の☆監視) やseller_rules
        (rule_type='watch'、出品者単位の監視) に登録されている投稿でも
        無条件に削除対象になっていた。これはdb/schema.sqlの
        watched_articlesテーブルのコメントが明記する設計思想
        「物理削除された投稿を後で見返すニーズより、ウォッチ解除の
        意思決定はユーザー自身が行うべき」と矛盾していた
        (watched_articles.article_idの行自体は削除後も残る設計だが、
        参照先のactive_articlesが消えると「監視」タブに一切
        表示されなくなり、実質的に見返せなくなっていたため)。

        このため、以下のいずれかに該当する投稿は保存期間を過ぎても
        削除しないようにした:
          - watched_articles に登録されている (投稿単位の監視)
          - 投稿のseller_idが、is_active=1のseller_rules
            (rule_type='watch') に登録されている (出品者単位の監視)

        監視を解除すれば、次回以降の巡回で通常通り保存期間削除の
        対象に戻る (ユーザーが意思を持って解除した時点で初めて
        削除対象になる、という自然な振る舞いになる)。

    2026-09-14変更 (削除履歴の記録、ユーザーとの合意事項):
        削除される投稿のタイトル・価格等をdeleted_articles_logへ
        コピーしてから削除するようにした。「保存期間内に消えた投稿を
        少しの間だけ見返したい」という要望に対応するもので、
        article_status_history (article_idしか持たず、投稿本体が
        消えた後は中身が分からない) とは別に、一覧表示に必要な情報を
        スナップショットとして保持する。

        このログ自体もdeleted_at基準でretention_daysを過ぎたら
        あわせて削除する (「自分が消したわけではない投稿の履歴に
        強い興味はない。データ肥大化も避けたい」というユーザーの
        方針により、無期限には保持しない)。

    呼び出しタイミング: scheduler.job.run_scan_with_range() の一環と
    して毎回チェックする想定 (削除自体はHTTPアクセスを伴わない)。

    Args:
        retention_days: 保存期間 (日数)。この日数より基準日が
            古い投稿を削除する。deleted_articles_logの掃除にも
            同じ日数を使う。

    Returns:
        削除した件数 (active_articles からの削除件数。
        deleted_articles_log の掃除件数は含まない)。
    """
    rows = conn.execute(
        """
        SELECT a.article_id, a.article_status, a.url, a.list_title, a.price,
               a.prefecture, a.area_name, a.category_name, a.thumbnail_url,
               a.first_seen_at, a.last_seen_at
        FROM active_articles a
        WHERE (
            (a.article_status = 'active' AND a.last_seen_at IS NOT NULL
                   AND a.last_seen_at <= datetime('now', ?))
               OR (a.article_status = 'missing' AND a.missing_since IS NOT NULL
                   AND a.missing_since <= datetime('now', ?))
        )
        AND a.article_id NOT IN (SELECT article_id FROM watched_articles)
        AND (
            a.seller_id IS NULL
            OR a.seller_id NOT IN (
                SELECT seller_id FROM seller_rules
                WHERE rule_type = 'watch' AND is_active = 1
            )
        )
        """,
        (f"-{retention_days} days", f"-{retention_days} days"),
    ).fetchall()

    for row in rows:
        conn.execute(
            """
            INSERT INTO deleted_articles_log (
                article_id, url, list_title, price, prefecture, area_name,
                category_name, thumbnail_url, article_status,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["article_id"], row["url"], row["list_title"], row["price"],
                row["prefecture"], row["area_name"], row["category_name"],
                row["thumbnail_url"], row["article_status"],
                row["first_seen_at"], row["last_seen_at"],
            ),
        )
        conn.execute("DELETE FROM active_articles WHERE article_id = ?", (row["article_id"],))
        _record_status_change(
            conn, row["article_id"], row["article_status"], "deleted", "retention_period_expired"
        )

    # 2026-09-14追加: 削除履歴自体もretention_days基準で古いものを
    # 掃除する (deleted_at基準)。「自分が消したわけではない投稿の
    # 履歴に強い興味はない」というユーザーの方針により、
    # active_articles本体と同じ日数だけ保持すれば十分と判断した。
    conn.execute(
        "DELETE FROM deleted_articles_log WHERE deleted_at <= datetime('now', ?)",
        (f"-{retention_days} days",),
    )

    return len(rows)


def _record_status_change(
    conn: sqlite3.Connection, article_id: str, from_status: str | None, to_status: str, reason: str
) -> None:
    """article_status_history に1件記録する (内部ヘルパー)。"""
    conn.execute(
        """
        INSERT INTO article_status_history (article_id, from_status, to_status, reason)
        VALUES (?, ?, ?, ?)
        """,
        (article_id, from_status, to_status, reason),
    )


def list_deleted_articles(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    """
    保存期間切れで削除された投稿のスナップショット一覧を、削除日時の
    新しい順に返す (2026-09-14新設)。

    deleted_articles_log自体もpurge_expired_articles()の実行時に
    古いものから削除されるため、ここで返るのは「まだ保存期間内に
    削除履歴として残っているもの」のみになる。

    Args:
        limit: 返す最大件数 (一覧が際限なく長くならないための上限。
            大量削除が発生した場合でも画面が重くならないようにする)。
    """
    return conn.execute(
        """
        SELECT * FROM deleted_articles_log
        ORDER BY deleted_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
