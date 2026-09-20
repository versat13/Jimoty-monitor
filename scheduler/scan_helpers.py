"""
巡回処理で使う小さなヘルパー関数群。

scheduler/job.py (旧・巡回ジョブ本体の単一ファイル) から分割
(2026-09-13)。ここに集めた関数は fetch_html・polite_sleep・
is_cancel_requested のいずれにも依存せず、テストからも直接
patch対象にされていないため、他の巡回ロジックと切り離して
安全に独立させられる。
"""

from datetime import date, datetime

from filters.category_filter import NgCategoryRule
from filters.keyword_filter import NgKeywordRule
from scraper.normalize import normalize_history_date


def load_active_rules(conn) -> tuple[list[NgKeywordRule], list[NgCategoryRule]]:
    """永続テーブルから有効なNGワード・NGカテゴリルールを読み込む。"""
    keyword_rows = conn.execute(
        "SELECT keyword, is_active FROM ng_keywords WHERE is_active = 1"
    ).fetchall()
    ng_keywords = [NgKeywordRule(keyword=r["keyword"], is_active=bool(r["is_active"])) for r in keyword_rows]

    category_rows = conn.execute(
        "SELECT category_id, category_level, is_active FROM ng_categories WHERE is_active = 1"
    ).fetchall()
    ng_categories = [
        NgCategoryRule(
            category_id=r["category_id"],
            category_level=r["category_level"],
            is_active=bool(r["is_active"]),
        )
        for r in category_rows
    ]

    return ng_keywords, ng_categories


def current_year_for_range() -> int:
    """
    一覧の月日のみ表記 (例: "8月22日") を実際の日付に変換するための
    基準年。年またぎの厳密な補正は既存の list_parser 側の
    current_year 引数と同じ制約を引き継ぐ (現時点では呼び出し時点の
    年を固定的に使う簡易実装。将来、年末年始をまたぐ巡回で問題に
    なった場合はここを見直す)。
    """
    return datetime.now().year


def current_date_for_range() -> date:
    return datetime.now().date()


def reference_date_for_range(article) -> "date | None":
    """
    取得範囲「過去n日」判定用の基準日を求める。
    「更新日があれば更新日、なければ作成日」を採用する
    (2026-09-07 ユーザーとの合意事項)。
    """
    if article.updated_date_raw:
        _, d = normalize_history_date(article.updated_date_raw, current_year=current_year_for_range())
        if d is not None:
            return d
    if article.created_date_raw:
        _, d = normalize_history_date(article.created_date_raw, current_year=current_year_for_range())
        if d is not None:
            return d
    return None
