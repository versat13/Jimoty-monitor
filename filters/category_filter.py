"""
NGカテゴリ判定 (フィルタリング処理フロー⑥に付随)。

根拠: 仕様書 v1.0 5-2, 6章
    ng_categories：NGカテゴリ（category_idベース、一覧段階で判定可能）
    ⑥ カテゴリ判定（一覧段階のURL構造から）

keyword_filter.py と同じ「取得漏れゼロ」の原則に従う。判定関数は
是非を返すのみで、実際にデータを除外・非表示にする処理はここには
含めない (repository層や表示APIの責務)。

=== category_id の形式について ===

実データ検証 (2026-08-22、list_parser.py 参照) で判明した通り、
category_id は必ずしも g-{数字} 形式の数値文字列とは限らない。
"その他"のようなカテゴリは g-数字を持たず、URLスラッグ (例: "oth") が
category_id として入る場合がある (scraper.selectors.url_patterns.
is_category_slug_url 参照)。このためcategory_idは文字列として
そのまま比較する設計とする (数値変換はしない)。

=== 階層構造とNG判定 (2026-09-08 拡張) ===

ジモティーのカテゴリは3階層ある (ユーザーとの打ち合わせで整理した仕様):

    大カテゴリ (category_parent_id): sale-XXX のURLスラッグ相当。
        個別ページのパンくずリストからのみ取得できる。
    ジャンル   (category_mid_id または category_id):
        大カテゴリ配下の最初の階層。投稿がサブジャンルまで指定して
        いない場合、ジャンルが category_id (詳細カテゴリ) に入る。
    サブジャンル (category_id):
        ジャンルのさらに配下。投稿によっては指定されない
        (この場合ジャンルまでで category_id が確定する)。

出品者はジャンル・サブジャンルを指定せずに投稿できるため、
「大カテゴリだけ確定していてジャンル以下は不明」という投稿もある
(この場合は大カテゴリだけでNG判定すれば十分、というユーザー方針)。

NGカテゴリは登録時に category_level ('parent'/'mid'/'leaf') を
持ち、以下のルールで判定する:

    - level='parent' で登録: 投稿の category_parent_id が一致すれば
      NG (ジャンル・サブジャンルを問わず、その大カテゴリ全体がNG)。
    - level='mid' で登録: 投稿の category_mid_id **または**
      category_id (サブジャンル無しでジャンルがそのまま category_id
      に入っているケースを拾うため) が一致すればNG。
    - level='leaf' で登録: 投稿の category_id (詳細カテゴリ/
      サブジャンル) が一致すればNG。

一覧段階では category_parent_id は取得できない (個別ページでのみ
判明する) ため、一覧のみの投稿に対しては 'parent' 登録はマッチ
しようがない。これは「取得漏れゼロ」の原則には反しない
(投稿自体は取得され、詳細ページ取得後に判定が確定するため)。
"""

from dataclasses import dataclass


@dataclass
class NgCategoryRule:
    """永続テーブル ng_categories 1件分に対応する設定値。"""

    category_id: str
    category_level: str = "leaf"  # 'parent' / 'mid' / 'leaf'
    is_active: bool = True


@dataclass
class CategoryMatchResult:
    """判定結果。is_hidden_by_rule相当のフラグとして呼び出し元が使う。"""

    matched: bool
    matched_category_id: str | None


def check_ng_category(
    category_id: str | None,
    ng_rules: list[NgCategoryRule],
    *,
    category_mid_id: str | None = None,
    category_parent_id: str | None = None,
) -> CategoryMatchResult:
    """
    投稿のカテゴリIDをNGカテゴリ一覧と照合する。

    Args:
        category_id: 一覧・詳細ページから取得した詳細カテゴリID
            (ListArticle.category_id または DetailArticle.category_id)。
            ジャンルのみでサブジャンルが無い投稿では、ジャンルの
            IDがそのままここに入る。
        ng_rules: 永続テーブル ng_categories から読み込んだルール一覧
        category_mid_id: 詳細ページでのみ取得できる中間カテゴリ
            (ジャンル) ID (DetailArticle.category_mid_id)。
            一覧段階では通常None。
        category_parent_id: 詳細ページでのみ取得できる大カテゴリID
            (DetailArticle.category_parent_id)。一覧段階では
            通常None (2026-09-08追加)。

    Returns:
        CategoryMatchResult。matched=Falseの場合でも呼び出し元は
        投稿データの取得・保存を行うこと (取得漏れゼロの原則)。
    """
    parent_ids = {r.category_id for r in ng_rules if r.is_active and r.category_level == "parent"}
    mid_ids = {r.category_id for r in ng_rules if r.is_active and r.category_level == "mid"}
    leaf_ids = {r.category_id for r in ng_rules if r.is_active and r.category_level == "leaf"}

    # 2026-09-08: 判定の優先順位は「詳細(leaf) > ジャンル(mid) >
    # 大カテゴリ(parent)」。旧仕様 (詳細カテゴリ優先) を踏襲しつつ、
    # 大カテゴリ・ジャンルはより広い範囲をカバーするため最後に見る。
    # 優先順位は matched_category_id の報告内容にのみ影響し、
    # 判定結果 (matched) 自体はどの順序で見ても変わらない。
    if category_id is not None and category_id in leaf_ids:
        return CategoryMatchResult(matched=True, matched_category_id=category_id)

    if category_mid_id is not None and category_mid_id in mid_ids:
        return CategoryMatchResult(matched=True, matched_category_id=category_mid_id)

    # ジャンルのみでサブジャンルが無い投稿は、ジャンルのIDが
    # category_id に入る。この場合も 'mid' 登録にヒットさせたい
    # (ユーザー方針: 「ジャンルを選べばそのジャンルと全てのサブジャンルが
    # NG」であり、サブジャンル未指定の投稿もジャンル一致とみなすべき)。
    if category_mid_id is None and category_id is not None and category_id in mid_ids:
        return CategoryMatchResult(matched=True, matched_category_id=category_id)

    if category_parent_id is not None and category_parent_id in parent_ids:
        return CategoryMatchResult(matched=True, matched_category_id=category_parent_id)

    if category_id is not None and category_id in leaf_ids:
        return CategoryMatchResult(matched=True, matched_category_id=category_id)

    return CategoryMatchResult(matched=False, matched_category_id=None)
