"""
取得範囲設定 (ページ数 or 過去n日) の読み書きを担当するモジュール。
2026-09-07 新設。

=== 設計メモ ===

db/schema.sql の scan_state テーブルは本来「監視対象 (都道府県+
カテゴリ+市区町村の組み合わせ) ごとに1レコード」という設計だが、
2026-09-07時点ではまだ「複数の監視対象を登録・切り替える」UI自体が
存在せず、フロントエンドは常に単一の監視対象 (福岡県・北九州市) を
決め打ちで巡回している。

このため、取得範囲設定 (scan_range_mode / scan_range_value) も
現段階では「アプリ全体で共有する単一の設定」として扱う。
scan_state に行が1つも無ければデフォルト値 (pages, 1) を返し、
初回の設定変更時に1行だけ作成する。

将来、監視対象を複数持てるようになった際は、この単一設定を
「監視対象ごとの設定」に自然に展開できるよう、scan_state の
列構成自体は当初からレコード単位の設定として定義してある
(db/schema.sql 参照)。
"""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_SCAN_RANGE_MODE = "pages"
DEFAULT_SCAN_RANGE_VALUE = 1
# 2026-09-13追加: 自動更新間隔のデフォルト値 (ユーザーとの合意事項)。
# 新規インストール時、何も設定しなくても30分間隔で自動更新される
# ようにする。db/schema.sql側のDEFAULT 30とこの値は揃えてあるが、
# 下記の通りINSERT文がこのカラムに明示的に値を渡す構造になっている
# ため、SQLite側のDEFAULT句だけでは効かない (INSERT文で明示的に
# 値を渡すとカラムのDEFAULT句は無視されるため)。このためこの定数を
# 直接INSERT文に使う。
DEFAULT_AUTO_SCAN_INTERVAL_MINUTES = 30

# 2026-09-07時点でアプリが決め打ちで使っている唯一の監視対象。
# 複数監視対象UIができるまでの暫定値 (trigger_scanのデフォルト値と揃える)。
_DEFAULT_PREFECTURE = "fukuoka"
_DEFAULT_CATEGORY_SLUG = "sale-all"
# 2026-09-10追加: area_id/area_nameのデフォルト値 (北九州市)。
# get_monitored_target() と同じ値。以前は update_scan_range_settings() /
# update_scan_range_only() / update_auto_scan_interval() がそれぞれ
# 個別にINSERT文を持っており、area_id/area_nameを指定し忘れていたため、
# 設定タブを最初に保存したタイミング次第でscan_stateの初期行が
# area指定なし (=福岡県全域) で作られてしまう不具合があった
# (2026-09-10発覚。詳細は _ensure_scan_state_row() docstring参照)。
_DEFAULT_AREA_ID = "731"
_DEFAULT_AREA_NAME = "kitakyushu"


def _ensure_scan_state_row(conn) -> int:
    """
    scan_state に行が無ければ、北九州市をデフォルトとした1行を作成し、
    その行のidを返す。既に行があれば何もせず既存の最初の行のidを返す。

    2026-09-10新設: 以前は get_monitored_target() /
    update_scan_range_settings() / update_scan_range_only() /
    update_auto_scan_interval() の4箇所がそれぞれ個別に「行が無ければ
    INSERTする」ロジックを持っていた。このうち後者3つはarea_id/
    area_nameをINSERT文に含めておらず、結果としてscan_state初期行が
    area指定なし (=市区町村を絞らない福岡県全域) で作られてしまう
    不具合があった。ユーザーが「取得範囲」や「自動更新」タブを一番
    最初に開いて保存すると、この不具合のある行が先に作られてしまい、
    以後ずっと福岡県全域を巡回し続けることになっていた。

    初回行作成のロジックをこの関数1箇所に統一することで、今後
    同様の項目 (region_type等) が増えてもこの手の不整合が起きない
    ようにする。
    """
    row = conn.execute("SELECT id FROM scan_state ORDER BY id LIMIT 1").fetchone()
    if row is not None:
        return row["id"]

    cursor = conn.execute(
        """
        INSERT INTO scan_state (
            prefecture, category_slug, category_id, area_id, area_name,
            scan_range_mode, scan_range_value, auto_scan_interval_minutes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _DEFAULT_PREFECTURE, _DEFAULT_CATEGORY_SLUG, "all",
            _DEFAULT_AREA_ID, _DEFAULT_AREA_NAME,
            DEFAULT_SCAN_RANGE_MODE, DEFAULT_SCAN_RANGE_VALUE, DEFAULT_AUTO_SCAN_INTERVAL_MINUTES,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def ensure_scan_state_row(conn) -> int:
    """
    _ensure_scan_state_row() の公開版 (2026-09-10新設)。

    scheduler.job.run_scan_with_range() が、巡回進捗
    (scan_progress_* 列) を書き込む前に「scan_state に行が確実に
    存在する」ことを保証するために呼ぶ。設定タブを一度も開かずに
    「今すぐ更新」を押した場合でも進捗の書き込み先が無い、という
    状態を防ぐ。
    """
    return _ensure_scan_state_row(conn)


@dataclass
class ScanRangeSettings:
    scan_range_mode: str  # "pages" | "days"
    scan_range_value: int
    # 2026-09-09に自動更新機能 (scheduler/auto_refresh.py) の実装が
    # 完了し、この値を使ってスケジューラが実際に定期実行するように
    # なった。2026-09-13: デフォルト値を30分に変更 (DEFAULT_AUTO_
    # SCAN_INTERVAL_MINUTES参照)。Noneは「自動実行は無効・手動巡回
    # のみ」を意味する (ユーザーが設定画面で空欄にして保存すれば
    # いつでもこの状態にできる)。
    auto_scan_interval_minutes: int | None


@dataclass
class MonitoredTarget:
    """
    監視対象 (地域+カテゴリの組み合わせ) を表す (2026-09-09新設)。

    自動更新のサーバー側定期実行を追加するにあたり、それまで
    api/main.py の trigger_scan() エンドポイントの引数デフォルト値
    (prefecture="fukuoka" 等) にハードコードされていた監視対象を、
    scan_state テーブルから読み込めるようにするために追加した。

    このモジュールの冒頭の設計メモにある通り、scan_state は将来
    「監視対象ごとに複数レコード」を持てる設計になっているが、
    2026-09-09時点でもまだ複数監視対象UIは存在しないため、ここでも
    従来通り「アプリ全体で共有する単一の監視対象」として扱う
    (=常に最初の1行のみを見る)。地域変更UIは将来の対応とし、今は
    設定の置き場所 (DB) だけを用意しておく (ユーザーとの合意事項)。
    """

    prefecture: str
    category_slug: str
    category_id: str | None
    area_id: str | None
    area_name: str | None


def get_monitored_target(conn) -> MonitoredTarget:
    """
    現在の監視対象 (地域+カテゴリ) を返す。

    scan_state にまだ行が無ければ、trigger_scan() の従来のデフォルト
    値と揃えた暫定値 (福岡県北九州市・全カテゴリ) で1行作成してから
    返す。

    2026-09-09: 「行が無ければ作成する」動作にした理由は、
    scheduler.job.run_scan_with_range() が巡回完了後に
    scan_state.last_scanned_at を更新する際、対象の行が存在しないと
    更新が効かず (UPDATE文のWHERE句のサブクエリがNULLになるため)、
    自動更新 (サーバー側定期実行) の「前回いつ実行したか」判定が
    永久にできなくなってしまうため。trigger_scan() は必ずこの関数を
    呼んでから巡回するため、これで行の存在を保証できる。
    """
    _ensure_scan_state_row(conn)

    row = conn.execute(
        "SELECT prefecture, category_slug, category_id, area_id, area_name "
        "FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()

    return MonitoredTarget(
        prefecture=row["prefecture"] or _DEFAULT_PREFECTURE,
        category_slug=row["category_slug"] or _DEFAULT_CATEGORY_SLUG,
        category_id=row["category_id"],
        area_id=row["area_id"],
        area_name=row["area_name"],
    )


def update_monitored_target(
    conn,
    *,
    prefecture: str,
    area_id: str | None,
    area_name: str | None,
) -> MonitoredTarget:
    """
    監視対象の地域 (都道府県・市区町村) のみを更新する (2026-09-10新設)。

    取得範囲・自動更新間隔には一切触れない (update_scan_range_only() /
    update_auto_scan_interval() と同じ設計方針: 各設定タブが互いの値を
    意図せず上書きしないよう、更新対象の列ごとに専用関数を分ける)。

    area_id/area_nameの両方をNoneにすると「都道府県のみ監視 (市区町村を
    絞らない)」になる。scraper.fetch.build_list_url() は元々
    area_id/area_nameが両方Noneのときは都道府県のみのURLを組み立てる
    設計だったため、この関数もそれに合わせてarea_id/area_nameの
    有無だけで判定する。region_type列には、将来の拡張 (my_area等) の
    ための記録として、現状の指定方式 ('prefecture' or 'prefecture_city')
    を保存しておく。

    Args:
        prefecture: 都道府県スラッグ (例: "fukuoka")。空文字は不可。
        area_id: 市区町村ID (例: "731")。都道府県全域なら None。
        area_name: 市区町村名ローマ字 (例: "kitakyushu")。
            都道府県全域なら None。

    Raises:
        ValueError: prefectureが空、または area_id/area_name の
            どちらか一方だけが指定された場合 (両方指定するか、
            両方Noneにするかのどちらか)。
    """
    if not prefecture:
        raise ValueError("prefectureは必須です")
    if (area_id is None) != (area_name is None):
        raise ValueError("area_idとarea_nameは両方指定するか、両方省略してください")

    region_type = "prefecture" if area_id is None else "prefecture_city"

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        """
        UPDATE scan_state
        SET prefecture = ?, area_id = ?, area_name = ?, region_type = ?
        WHERE id = ?
        """,
        (prefecture, area_id, area_name, region_type, row_id),
    )

    conn.commit()
    return get_monitored_target(conn)


def get_scan_range_settings(conn) -> ScanRangeSettings:
    """
    現在の取得範囲設定を返す。scan_state にまだ行が無ければ
    デフォルト値 (ページ数指定・1ページ) を返す。
    """
    row = conn.execute(
        "SELECT scan_range_mode, scan_range_value, auto_scan_interval_minutes "
        "FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()

    if row is None:
        return ScanRangeSettings(
            scan_range_mode=DEFAULT_SCAN_RANGE_MODE,
            scan_range_value=DEFAULT_SCAN_RANGE_VALUE,
            auto_scan_interval_minutes=DEFAULT_AUTO_SCAN_INTERVAL_MINUTES,
        )

    return ScanRangeSettings(
        scan_range_mode=row["scan_range_mode"],
        scan_range_value=row["scan_range_value"],
        auto_scan_interval_minutes=row["auto_scan_interval_minutes"],
    )


def update_scan_range_settings(
    conn,
    *,
    scan_range_mode: str,
    scan_range_value: int,
    auto_scan_interval_minutes: int | None = None,
) -> ScanRangeSettings:
    """
    取得範囲設定を更新する。scan_state に行が無ければ、暫定の
    デフォルト監視対象 (福岡県・カテゴリ指定なし) で1行作成する。

    Raises:
        ValueError: scan_range_mode が pages/days 以外、または
            scan_range_value が1未満の場合。

    Note (2026-09-08):
        この関数は auto_scan_interval_minutes も一緒に上書きする。
        「自動更新」設定だけを変更したい場合は
        update_auto_scan_interval() を使うこと。取得範囲・自動更新を
        別々のタブ (別々のブラウザ/端末) から同時に編集した場合に
        片方の変更がもう片方の保存によって意図せず上書きされる事故を
        避けるため、2026-09-08にAPIを分割した (旧: 単一エンドポイント
        で両方をまとめて保存していた)。

        重要: この関数は auto_scan_interval_minutes を省略すると
        デフォルト値のNoneで上書きしてしまう (=既存の自動更新間隔が
        消える)。取得範囲のみを更新したい呼び出し元
        (update_scan_range_settings_endpoint 等) は、
        update_scan_range_only() を使うこと。
    """
    if scan_range_mode not in ("pages", "days"):
        raise ValueError(f"scan_range_modeはpagesまたはdaysである必要があります: {scan_range_mode}")
    if scan_range_value < 1:
        raise ValueError(f"scan_range_valueは1以上である必要があります: {scan_range_value}")

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        """
        UPDATE scan_state
        SET scan_range_mode = ?, scan_range_value = ?, auto_scan_interval_minutes = ?
        WHERE id = ?
        """,
        (scan_range_mode, scan_range_value, auto_scan_interval_minutes, row_id),
    )

    conn.commit()
    return get_scan_range_settings(conn)


def update_scan_range_only(
    conn,
    *,
    scan_range_mode: str,
    scan_range_value: int,
) -> ScanRangeSettings:
    """
    取得範囲 (scan_range_mode / scan_range_value) のみを更新する
    (2026-09-08新設)。auto_scan_interval_minutes には一切触れない
    (既存行が無ければNoneのまま1行作成するが、既存値は保持したまま
    UPDATEするため、update_scan_range_settings() のように
    auto_scan_interval_minutes をNoneで上書きしてしまう心配がない)。

    「取得範囲」設定タブを「自動更新」タブから独立させ、別々に保存
    しても互いの値を上書きしないようにするための専用関数。
    update_auto_scan_interval() の対になる関数。
    """
    if scan_range_mode not in ("pages", "days"):
        raise ValueError(f"scan_range_modeはpagesまたはdaysである必要があります: {scan_range_mode}")
    if scan_range_value < 1:
        raise ValueError(f"scan_range_valueは1以上である必要があります: {scan_range_value}")

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET scan_range_mode = ?, scan_range_value = ? WHERE id = ?",
        (scan_range_mode, scan_range_value, row_id),
    )

    conn.commit()
    return get_scan_range_settings(conn)


def update_auto_scan_interval(
    conn,
    *,
    auto_scan_interval_minutes: int | None,
) -> ScanRangeSettings:
    """
    自動更新間隔 (auto_scan_interval_minutes) のみを更新する
    (2026-09-08新設)。

    取得範囲 (scan_range_mode / scan_range_value) には一切触れない。
    「自動更新」設定タブを「取得範囲」タブから独立させ、別々に保存
    しても互いの値を上書きしないようにするための専用関数。

    scan_state にまだ行が無ければ、update_scan_range_settings() と
    同様に、既定の監視対象・デフォルトの取得範囲でまず1行作成する。

    Raises:
        ValueError: auto_scan_interval_minutes が0以下の場合
            (Noneは「未設定」として許可する)。
    """
    if auto_scan_interval_minutes is not None and auto_scan_interval_minutes < 1:
        raise ValueError(
            f"auto_scan_interval_minutesは1以上である必要があります: {auto_scan_interval_minutes}"
        )

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET auto_scan_interval_minutes = ? WHERE id = ?",
        (auto_scan_interval_minutes, row_id),
    )

    conn.commit()
    return get_scan_range_settings(conn)


@dataclass
class ScanProgress:
    """
    巡回中の進捗 (2026-09-10新設)。BottomNav付近の更新インジケーターが
    GET /api/scan-status 経由で参照する。

    current_page/seen_countは巡回中でなければNone (巡回中でない間は
    scheduler.job.run_scan_with_range() が進捗列をNULLにクリアする
    ため)。max_pageは取得範囲が'pages'モードのときのみ値を持つ
    ('days'モードは何ページで終わるか事前に分からないため常にNone)。
    """

    current_page: int | None
    max_page: int | None
    seen_count: int | None


def get_scan_progress(conn) -> ScanProgress:
    """現在の巡回進捗を返す (巡回中でなければ全項目None)。"""
    row = conn.execute(
        "SELECT scan_progress_current_page, scan_progress_max_page, "
        "scan_progress_seen_count FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return ScanProgress(current_page=None, max_page=None, seen_count=None)
    return ScanProgress(
        current_page=row["scan_progress_current_page"],
        max_page=row["scan_progress_max_page"],
        seen_count=row["scan_progress_seen_count"],
    )


def clear_scan_progress(conn) -> None:
    """
    巡回進捗をクリアする (2026-09-10新設)。

    scheduler.job.run_scan_with_range() 自体も正常系・緊急停止いずれの
    パスでも呼び出し後にクリアするが、ネットワークエラー等で関数が
    例外を投げて中断した場合はそのクリア処理まで到達しない。呼び出し元
    (api.main.trigger_scan / scheduler.auto_refresh._run_scan_sync) が
    finally節でこの関数を呼び、「更新中でないのに古い進捗が残っている」
    状態を防ぐ二重の安全策とする。scan_stateに行が無ければ何もしない。
    """
    conn.execute(
        "UPDATE scan_state SET scan_progress_current_page = NULL, "
        "scan_progress_max_page = NULL, scan_progress_seen_count = NULL "
        "WHERE id = (SELECT id FROM scan_state ORDER BY id LIMIT 1)"
    )
    conn.commit()


DEFAULT_RETENTION_ENABLED = True
DEFAULT_RETENTION_DAYS = 7


@dataclass
class RetentionSettings:
    """
    保存期間削除の設定 (2026-09-11新設)。

    以前は「missing状態になってから21日固定」で自動削除していたが、
    ユーザーが日数を自由に設定でき、かつactive(受付中)の投稿にも
    一律適用できる仕組みに一本化した。判定基準の使い分けの詳細は
    repository.article_repository.purge_expired_articles() 参照。
    """

    enabled: bool
    retention_days: int


def get_retention_settings(conn) -> RetentionSettings:
    """現在の保存期間削除設定を返す。scan_state にまだ行が無ければデフォルト値を返す。"""
    row = conn.execute(
        "SELECT retention_enabled, retention_days FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()

    if row is None:
        return RetentionSettings(enabled=DEFAULT_RETENTION_ENABLED, retention_days=DEFAULT_RETENTION_DAYS)

    return RetentionSettings(
        enabled=bool(row["retention_enabled"]),
        retention_days=row["retention_days"],
    )


def update_retention_settings(conn, *, enabled: bool, retention_days: int) -> RetentionSettings:
    """
    保存期間削除設定を更新する。scan_state に行が無ければ、
    _ensure_scan_state_row() で北九州デフォルトの1行を作成してから
    更新する (他の設定タブと同じ設計方針)。

    Raises:
        ValueError: retention_days が1未満の場合。
    """
    if retention_days < 1:
        raise ValueError(f"retention_daysは1以上である必要があります: {retention_days}")

    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET retention_enabled = ?, retention_days = ? WHERE id = ?",
        (int(enabled), retention_days, row_id),
    )

    conn.commit()
    return get_retention_settings(conn)


@dataclass
class LastNotifiedArticles:
    """
    直近の巡回で「検索」タブ (pickup_search) の条件にヒットした新規
    投稿の一覧 (2026-09-15新設)。トースト通知・ブラウザ通知向け。

    article_ids: article_idのリスト。巡回のたびに (対象0件でも) 洗い
        替えされる。まだ一度もこの機能を使った巡回が行われていなければ
        空リスト。
    notified_at: article_idsが保存された巡回の完了時刻
        (scan_state.last_scanned_atと同じタイミングで更新される)。
        フロント (ScanStatusContext) はこの値が前回ポーリング時から
        変化したかどうかで「新しい巡回結果か」を判定し、変化して
        いなければarticle_idsを再度通知対象として扱わない
        (同じ内容を毎回のポーリングで重複通知しないようにするため)。
    """

    article_ids: list[str]
    notified_at: str | None


def get_last_notified_articles(conn) -> LastNotifiedArticles:
    """
    直近の巡回でpickup_search条件にヒットした新規投稿のarticle_id一覧を
    返す (2026-09-15新設)。scan_stateにまだ行が無い、またはJSONの
    パースに失敗した場合は空リストを返す (通知機能が壊れても巡回本体・
    他のAPIレスポンスに影響させないための安全策)。
    """
    row = conn.execute(
        "SELECT last_notified_article_ids, last_notified_at FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()

    if row is None or row["last_notified_article_ids"] is None:
        return LastNotifiedArticles(article_ids=[], notified_at=None)

    try:
        article_ids = json.loads(row["last_notified_article_ids"])
        if not isinstance(article_ids, list):
            raise ValueError("JSON配列ではありません")
    except (json.JSONDecodeError, ValueError):
        logger.warning("last_notified_article_idsのパースに失敗しました。空リストとして扱います。")
        return LastNotifiedArticles(article_ids=[], notified_at=row["last_notified_at"])

    return LastNotifiedArticles(article_ids=article_ids, notified_at=row["last_notified_at"])


def update_last_notified_articles(conn, article_ids: list[str]) -> None:
    """
    直近の巡回のpickup_search条件マッチ結果をscan_stateに保存する
    (2026-09-15新設)。scheduler.scan_runner.run_scan_with_range() が
    巡回完了のたびに呼ぶ (対象が0件の巡回でも呼び、前回巡回分の
    article_idsが古いまま残り続けないようにする＝洗い替え)。

    notified_atはdatetime('now')で都度更新するため、対象が0件同士の
    巡回が連続しても「新しい巡回が完了した」こと自体はフロント側で
    検知できる (article_idsの中身の比較だけでなく、notified_atの
    変化も見て「新規通知対象があるか」を判定する設計。
    frontend/src/context/ScanStatusContext.jsx 参照)。

    scan_stateに行が無い場合は _ensure_scan_state_row() で作成してから
    更新する (他の設定と同じ設計方針)。
    """
    row_id = _ensure_scan_state_row(conn)
    conn.execute(
        "UPDATE scan_state SET last_notified_article_ids = ?, last_notified_at = datetime('now') "
        "WHERE id = ?",
        (json.dumps(article_ids, ensure_ascii=False), row_id),
    )
    conn.commit()
