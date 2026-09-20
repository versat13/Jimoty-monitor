"""
ジモティーのURL構造から各種IDを抽出する正規表現パターン集。

確定根拠:
- 仕様書 v1.0 4-2, 4-4
- HTML解析仕様確定版 3, 7, 8, 9, 16
- 実データ検証 (2026-08-22, web_fetch): 北九州市一覧・個別ページ

URL構造例:
    投稿詳細: https://jmty.jp/fukuoka/sale-pcp/article-1jntvx
    地域付き: https://jmty.jp/fukuoka/sale-pcp/g-1205/a-731-kitakyushu
    駅付き  : https://jmty.jp/fukuoka/sale-pcp/g-1205/s-1190607
    広告    : https://jmty.jp/fukuoka/rec-lig/alliance-rec_techouse_980712?ex=1
    PR枠    : https://jmty.jp/fukuoka/sale-ele/article-1r8jq4?from=pr  (仕様未確定、要検討)
"""

import re
from urllib.parse import urljoin

# 投稿ID: article-{id} 形式。英数字のみ (実データ例: 1jntvx, 1rbrbe)
ARTICLE_ID_PATTERN = re.compile(r"/article-([a-zA-Z0-9]+)")

# 広告判定: URLパス中に alliance- を含む
ALLIANCE_PATTERN = re.compile(r"/alliance-")

# 未確定: PR枠クエリパラメータ (from=pr)。alliance-ではないが表示上★マーク付き。
# v1では「広告」ではなく「通常投稿」として扱うが、フラグとして検出する。
PR_SLOT_PATTERN = re.compile(r"[?&]from=pr(&|$)")

# カテゴリID: g-{category_id} 形式 (g-all は「未指定」を意味するため除外)
CATEGORY_ID_PATTERN = re.compile(r"/g-(\d+)")

# カテゴリスラッグ: g-数字を持たない場合の代替表現。
# 実データ検証 (2026-08-22) で確認: 例 https://jmty.jp/all/sale-oth (その他)
#   https://jmty.jp/all/sale-food (食品) など。
# キーワードタグ (sale-kw-) とは別物なので、この正規表現では明示的に除外する。
#
# 実データ検証で追加判明 (2026-08-23):
#   同じ一覧ページ内で、あるリンクは絶対URL (https://jmty.jp/all/sale-oth)、
#   別のリンクは相対URL (/all/sale-oth) と、表記が投稿によって混在する
#   ことがある (ジモティー側のページ生成の揺れと推定)。
#   当初は絶対URLのみを想定していたため、相対URL形式の投稿12件で
#   カテゴリが一切取得できず、キーワードタグとしても拾えず消失する
#   不具合があった (ユーザー環境で発見、2026-08-23)。
#   このためプロトコル+ホスト部分は任意 (絶対URLでも相対URLでも一致する)
#   ものとして正規表現を組み直した。
CATEGORY_SLUG_PATTERN = re.compile(r"^(?:https?://jmty\.jp)?/all/sale-(?!kw-)([a-z]+)/?$")

# キーワードタグ: /all/sale-kw-{urlencoded_keyword} 形式。カテゴリではなく投稿のフリーワードタグ。
KEYWORD_TAG_PATTERN = re.compile(r"/all/sale-kw-(.+)$")

# エリアID: a-{area_id}-{area_name} 形式
AREA_ID_PATTERN = re.compile(r"/a-(\d+)-([a-zA-Z0-9\-]+)")

# 駅ID: s-{station_id} 形式
STATION_ID_PATTERN = re.compile(r"/s-(\d+)")

# 出品者ID: /profiles/{seller_id} 形式 (英数字混在)
SELLER_ID_PATTERN = re.compile(r"/profiles/([a-zA-Z0-9]+)")


def extract_article_id(url: str) -> str | None:
    m = ARTICLE_ID_PATTERN.search(url)
    return m.group(1) if m else None


def extract_category_id(url: str) -> str | None:
    m = CATEGORY_ID_PATTERN.search(url)
    return m.group(1) if m else None


def extract_area(url: str) -> tuple[str, str] | None:
    """(area_id, area_name) を返す。"""
    m = AREA_ID_PATTERN.search(url)
    return (m.group(1), m.group(2)) if m else None


def extract_station_id(url: str) -> str | None:
    m = STATION_ID_PATTERN.search(url)
    return m.group(1) if m else None


def extract_seller_id(url: str) -> str | None:
    m = SELLER_ID_PATTERN.search(url)
    return m.group(1) if m else None


def is_category_slug_url(url: str) -> bool:
    """
    g-数字を持たないカテゴリURLか判定する (例: /all/sale-oth)。
    sale-kw- (キーワードタグ) は明示的に除外している。
    """
    return bool(CATEGORY_SLUG_PATTERN.match(url.split("?")[0]))


def is_keyword_tag_url(url: str) -> bool:
    """フリーワードタグURLか判定する (例: /all/sale-kw-ELECOM)。"""
    return bool(KEYWORD_TAG_PATTERN.search(url))


def is_alliance_url(url: str) -> bool:
    return bool(ALLIANCE_PATTERN.search(url))


def is_pr_slot_url(url: str) -> bool:
    """from=pr を持つURLか判定する。広告判定には使わない（未確定仕様）。"""
    return bool(PR_SLOT_PATTERN.search(url))


def to_absolute_url(url: str | None, base: str = "https://jmty.jp") -> str | None:
    """
    相対URL・絶対URLどちらでも https://jmty.jp を基準にした絶対URLへ変換する。

    実データ検証で判明した通り (2026-08-23、一覧ページのカテゴリリンク、
    2026-08-27、個別ページの出品者プロフィールリンク)、ジモティーは
    同じ種類のリンクでも投稿によって絶対URL(https://jmty.jp/...)と
    相対URL(/profiles/...)を混在させることがある。フロントエンドで
    window.open() 等にそのまま渡すと、相対URLの場合は現在のオリジン
    (例: http://localhost:5173/profiles/...) に対して開こうとして
    失敗するため、保存前にこの関数で必ず絶対URL化する。
    """
    if url is None:
        return None
    return urljoin(base, url)
