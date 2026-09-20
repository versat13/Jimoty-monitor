"""
NGワード・NGカテゴリ・NGユーザー(seller_rules)のいずれかが変更された
直後に、DB内の全active_articlesに対してフィルタフラグ
(is_hidden_by_keyword/is_hidden_by_category/is_hidden_by_seller_rule)を
即座に再計算するための処理 (2026-09-05新設)。

=== 背景 ===

これらのフラグは、従来 scheduler/job.py の run_scan() (巡回処理) の
中でしか更新されていなかった。このため、NGワード・NGカテゴリ・
NGユーザーを新規登録しても、次に「今すぐ更新」を押すまでの間、
既存の投稿一覧には反映されない (ユーザー報告により発覚: 「NG」タブと
「監視」タブが同じ表示になったように見えたのは、NGユーザー登録した
直後にNG判定がまだ反映されておらず、その投稿が「フィルタ」タブに
残ったままだったため)。

この関数は、NGルールの登録・削除APIから呼び出され、巡回を待たずに
DB内の全投稿のフラグを再計算する。ネットワークアクセスは一切
発生しないため、低頻度アクセスの原則には抵触しない
(あくまでDB内で完結する再計算処理)。

=== 設計判断: なぜ都度全件再計算なのか ===

NGワード判定はタイトル・説明文に対する文字列マッチであり、
「そのNGワードにマッチする投稿だけ」をSQLで直接抽出するのは
正規化処理 (scraper.normalize.normalize_text_for_matching) を
SQL側で再現する必要があり非効率。件数が数千件規模になるまでは
全件スキャンで十分高速なため、シンプルさを優先してこの設計とした。
"""

import json
import sqlite3

from filters.category_filter import NgCategoryRule, check_ng_category
from filters.keyword_filter import NgKeywordRule, check_ng_keywords


def _load_active_rules(conn: sqlite3.Connection) -> tuple[list[NgKeywordRule], list[NgCategoryRule]]:
    """
    永続テーブルから有効なNGワード・NGカテゴリルールを読み込む。

    scheduler/job.py の同名関数と同じロジック。両方から使う共通処理
    だが、循環import (scheduler/job.py はこのモジュールを将来import
    しうる) を避けるため、あえてこちらに複製している。
    """
    keyword_rows = conn.execute(
        "SELECT keyword, is_active FROM ng_keywords WHERE is_active = 1"
    ).fetchall()
    ng_keywords = [
        NgKeywordRule(keyword=r["keyword"], is_active=bool(r["is_active"])) for r in keyword_rows
    ]

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


def recompute_all_filter_flags(conn: sqlite3.Connection) -> int:
    """
    active_articles全件のフィルタフラグを再計算し、DBに反映する。

    NGワード・NGカテゴリ・NGユーザー(seller_rules)のいずれかを
    登録・削除・有効無効切り替えした直後に呼び出すことを想定する。

    Returns:
        フラグが実際に変化した行数 (呼び出し元でのログ・レスポンス用)。
    """
    ng_keywords, ng_categories = _load_active_rules(conn)

    # seller_id -> rule_type の対応表を作っておき、行ごとに
    # get_seller_rule() を都度クエリするより高速にする。
    seller_ng_ids = {
        r["seller_id"]
        for r in conn.execute(
            "SELECT seller_id FROM seller_rules WHERE rule_type = 'ng' AND is_active = 1"
        ).fetchall()
    }

    rows = conn.execute(
        """
        SELECT article_id, list_title, description_short, category_id,
               category_mid_id, category_parent_id, seller_id,
               is_hidden_by_keyword, is_hidden_by_category, is_hidden_by_seller_rule
        FROM active_articles
        """
    ).fetchall()

    changed = 0
    for row in rows:
        keyword_result = check_ng_keywords(row["list_title"], row["description_short"], ng_keywords)
        category_result = check_ng_category(
            row["category_id"],
            ng_categories,
            category_mid_id=row["category_mid_id"],
            category_parent_id=row["category_parent_id"],
        )
        seller_rule_hidden = row["seller_id"] is not None and row["seller_id"] in seller_ng_ids

        if (
            bool(row["is_hidden_by_keyword"]) == keyword_result.matched
            and bool(row["is_hidden_by_category"]) == category_result.matched
            and bool(row["is_hidden_by_seller_rule"]) == seller_rule_hidden
        ):
            continue  # 変化なし。無駄な UPDATE を避ける

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
                int(keyword_result.matched),
                int(category_result.matched),
                int(seller_rule_hidden),
                json.dumps(keyword_result.matched_keywords, ensure_ascii=False),
                row["article_id"],
            ),
        )
        changed += 1

    conn.commit()
    return changed
