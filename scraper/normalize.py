"""
一覧・詳細ページから取得した生テキストをDB保存用の値に正規化する。

根拠:
- 価格: HTML解析仕様確定版 5 (「240円」→ 240、表示文字列は保存しない)
- お気に入り数: HTML解析仕様確定版 15 (NULLと0を区別する。空欄はNULL)
- 日付(一覧): HTML解析仕様確定版 14 (日付精度のみ)
- 日時(詳細): 追補版 v1.1 追補2 (詳細ページ本文には分単位の時刻が付く場合がある)
"""

import re
import unicodedata
from datetime import date, datetime

_PRICE_PATTERN = re.compile(r"[\d,]+")


def normalize_text_for_matching(text: str) -> str:
    """
    NGワード等の文字列マッチングのために、表記ゆれを吸収した形へ正規化する。

    実データ検証 (list_real.html の投稿タイトル群) で確認した表記ゆれ:
        - 全角スペース(\u3000)と半角スペースの混在
        - 全角英数字と半角英数字の混在 (例: "ＳＳＤ" vs "SSD")
        - 大文字・小文字の混在 (英字ブランド名等)
    NFKC正規化 (全角/半角の統一、各種互換文字の統一) を行った上で、
    比較の頑健性を上げるため小文字化もあわせて行う。
    記号・絵文字 (★💳等) はNFKCでは変化しないため、これらを含んだ
    NGワード登録も可能 (意図的に除去しない)。
    """
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.lower()

# 「更新8月22日」「作成8月22日」のような表記から月日を抽出 (一覧ページ由来、日付精度のみ)
_HISTORY_DATE_PATTERN = re.compile(r"(更新|作成)(\d{1,2})月(\d{1,2})日")

# 「更新2026年8月18日 11:49」「作成2026年8月17日 23:39」のような表記
# (個別ページ本文由来、追補版 v1.1 追補2で確認された時刻付きパターン)
_HISTORY_DATETIME_PATTERN = re.compile(
    r"(更新|作成)(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{2}))?"
)


def normalize_price(raw: str) -> int | None:
    """
    「240円」→ 240 に変換する。

    広告の「時給1,060円」のような値も同じ関数を通せば1060になってしまうため、
    価格正規化は必ず ad_rules.is_ad() による広告除外の後に呼び出すこと
    (呼び出し順序の担保は list_parser.py 側の責務)。
    """
    if not raw:
        return None
    m = _PRICE_PATTERN.search(raw)
    if not m:
        return None
    digits = m.group(0).replace(",", "")
    return int(digits) if digits else None


def normalize_favorite_count(raw: str | None, current_year: int) -> int | None:
    """
    お気に入り数を正規化する。

    HTML解析仕様確定版 15 の推奨に従い、NULLと0を区別する。
        - 空文字列 / None / 空白のみ → None (HTML上に件数表示がなかった)
        - 数字が取れる → その整数値 (0件表記も0として扱う)
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped == "":
        return None
    m = re.search(r"\d+", stripped)
    if not m:
        return None
    return int(m.group(0))


def normalize_history_date(raw: str, current_year: int) -> tuple[str | None, date | None]:
    """
    「更新8月22日」「作成8月22日」を (種別, date) に変換する。

    v1では日付精度のみ (時刻は取得不可)。年はページ取得時点の年を採用する
    (HTML解析仕様確定版 14: サンプルには年表記が含まれないため)。
    """
    m = _HISTORY_DATE_PATTERN.search(raw)
    if not m:
        return None, None
    kind, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    try:
        d = date(current_year, month, day)
    except ValueError:
        return kind, None
    return kind, d


def normalize_history_datetime(raw: str) -> list[tuple[str, datetime]]:
    """
    個別ページ本文の日時表示を (種別, datetime) のリストに変換する。

    追補版 v1.1 追補2 で確認された通り、詳細ページ本文には
        「更新2026年8月18日 11:49」
        「作成2026年8月17日 23:39」
    のように年・時刻まで含む表記が存在する。一覧ページの
    normalize_history_date() (月日のみ、年は呼び出し元指定) とは
    取得元・精度が異なるため別関数として分離する。

    時刻部分が無い場合は 00:00 として扱う (精度の違いはDB側で
    別途フラグ管理するか、実装時に決定する。README/追補版参照)。

    1つのテキストに「更新」「作成」が両方含まれる場合があるため、
    リストで全マッチを返す。
    """
    results = []
    for m in _HISTORY_DATETIME_PATTERN.finditer(raw):
        kind, year, month, day, hour, minute = m.groups()
        try:
            dt = datetime(
                int(year), int(month), int(day),
                int(hour) if hour else 0,
                int(minute) if minute else 0,
            )
        except ValueError:
            continue
        results.append((kind, dt))
    return results
