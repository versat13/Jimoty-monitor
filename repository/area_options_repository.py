"""
都道府県ごとの市区町村候補キャッシュ (area_options テーブル) の
読み書きを担当するモジュール。2026-09-12新設。

設定画面「地域」タブの「公式から市区町村を取得する」ボタンから、
scraper.area_list_parser で取得した市区町村候補をここに保存し、
プルダウンの選択肢として読み出す。
"""

from dataclasses import dataclass

from scraper.area_list_parser import AreaOption


@dataclass
class CachedAreaOption:
    """DBにキャッシュされた市区町村候補1件分。"""

    area_id: str
    area_name: str
    display_name: str


def replace_area_options(conn, prefecture: str, options: list[AreaOption]) -> int:
    """
    指定した都道府県の市区町村候補を、取得し直した内容で丸ごと
    置き換える (再取得のたびに古い候補は消し、新しい一覧だけを残す)。

    Args:
        prefecture: 都道府県スラッグ (例: "fukuoka")
        options: scraper.area_list_parser.parse_area_list_page() の結果

    Returns:
        保存した件数
    """
    conn.execute("DELETE FROM area_options WHERE prefecture = ?", (prefecture,))

    for i, option in enumerate(options):
        conn.execute(
            """
            INSERT INTO area_options (
                prefecture, area_id, area_name, display_name, display_order, fetched_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (prefecture, option.area_id, option.area_name, option.display_name, i),
        )

    conn.commit()
    return len(options)


def get_area_options(conn, prefecture: str) -> list[CachedAreaOption]:
    """
    指定した都道府県の市区町村候補一覧を、取得時の表示順で返す。
    まだ一度も取得していない都道府県なら空リストを返す。
    """
    rows = conn.execute(
        "SELECT area_id, area_name, display_name FROM area_options "
        "WHERE prefecture = ? ORDER BY display_order",
        (prefecture,),
    ).fetchall()

    return [
        CachedAreaOption(
            area_id=row["area_id"], area_name=row["area_name"], display_name=row["display_name"]
        )
        for row in rows
    ]


def get_area_options_fetched_at(conn, prefecture: str) -> str | None:
    """
    指定した都道府県の市区町村候補を最後に取得した日時を返す。
    まだ一度も取得していなければNone。
    """
    row = conn.execute(
        "SELECT fetched_at FROM area_options WHERE prefecture = ? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (prefecture,),
    ).fetchone()
    return row["fetched_at"] if row else None
