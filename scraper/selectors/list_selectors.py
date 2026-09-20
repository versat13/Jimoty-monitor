"""
一覧ページのCSSセレクタ定義。

根拠: 仕様書 v1.0 4-4、HTML解析仕様確定版 3〜16

注意 (HTML解析仕様確定版 7):
    .p-item-supplementary-info は複数存在しうる要素で、
    かつ1つの要素内に「市区町村・駅・カテゴリ」が並列で入る場合がある。
    単純に `.p-item-supplementary-info a` を全部取ると
    市区町村/駅/カテゴリ/タグが区別なく混ざるため、
    URL構造 (a-, s-, g-) で用途別に判別する。
"""

LIST_ITEM = "li.p-articles-list-item"

TITLE_LINK = ".p-item-title a"
PRICE = ".p-item-most-important b"
PREFECTURE_LINK = ".p-item-secondary-important a"

# 市区町村・駅・カテゴリ・タグはすべてこの中に混在する。
# 個々のリンクをURL構造(a-/s-/g-)で仕分ける。
SUPPLEMENTARY_INFO_BLOCKS = ".p-item-supplementary-info"
SUPPLEMENTARY_INFO_LINKS = ".p-item-supplementary-info a"

DESCRIPTION_SHORT = ".p-item-detail"
HISTORY_DATES = ".p-item-history .u-color-gray"
FAVORITE_COUNT = ".js_fav_user_count"

# 実データ検証で判明 (2026-08-24): p-item-image は img タグ自身のクラス。
# div.p-item-image のような親要素は存在しない
# (親要素は div.p-item-image-component)。
# 当初 ".p-item-image img" (子孫セレクタ) としていたため、
# サムネイル画像が全件 None になっていた。
THUMBNAIL_IMG = "img.p-item-image"

# 広告判定用 (ad_rules.py から参照)
ALLIANCE_TAG = ".p-item-alliance-tag"

# 2026-09-14新設: 一覧ページ最下部の「全242690件中 1-50件表示」相当の
# 総件数表示。更新中の進捗バー (scan_range_mode="days" のときの概算
# 進捗表示) に使う。scraper/list_parser.py の extract_total_count()
# 参照。
PAGINATE_NAVI = ".c-paginate-navi"
