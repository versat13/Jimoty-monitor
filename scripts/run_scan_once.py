"""
scheduler/job.py を使った、巡回ジョブ本体のエンドツーエンド確認スクリプト。

scripts/manual_e2e_check.py がパーサー単体(fetch+parse)の確認だったのに
対し、このスクリプトは scheduler.job.run_scan() を通した「取得→フィルタ
判定→DB保存→通知判定」の一連の流れを、実際にSQLiteファイルへ書き込む形で
確認する。

このチャット環境では実際のjmty.jpへのHTTPアクセスができないため、
scheduler/job.py自体のロジックはモックデータ(実データのHTMLファイル)を
使ったユニットテスト (tests/test_scheduler_job.py) で検証済みだが、
本スクリプトを使った実アクセスでの動作確認はユーザーの実行環境で
行うことを想定している。

=== 実行方法 ===

    cd jimoty-monitor
    pip install -r requirements.txt
    python scripts/run_scan_once.py

実行すると、このスクリプトと同じディレクトリに jimoty_monitor.db という
SQLiteファイルが作成される (既に存在する場合は追記される)。中身は
DB Browser for SQLite 等のツールで確認できる。

=== 注意 ===

- 低頻度アクセスの原則に従い、このスクリプトを繰り返し実行する場合は
  手動で間隔を空けること。
- missing状態の投稿の確定判定 (run_missing_check) はこのスクリプトでは
  実行しない。1回の一覧巡回 (run_scan) のみを確認する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from repository.article_repository import get_connection
from scheduler.job import run_scan
from scraper.fetch import build_client, build_list_url

DB_PATH = str(Path(__file__).parent.parent / "jimoty_monitor.db")


def main() -> None:
    url = build_list_url(
        "fukuoka", "sale-all", category_id="all", area_id="731", area_name="kitakyushu"
    )
    print(f"巡回ジョブを実行します: {url}")
    print(f"DBファイル: {DB_PATH}")

    conn = get_connection(DB_PATH)

    with build_client() as client:
        result = run_scan(conn, client, url)

    print("\n=== 巡回結果 ===")
    print(f"一覧で確認した件数(広告除外後): {result.total_seen}")
    print(f"新規投稿: {result.new_articles}")
    print(f"価格変化を検知した投稿: {result.price_changed}")
    print(f"新たにmissingになった投稿: {result.newly_missing}")
    print(f"通知対象になった投稿: {len(result.notified)}")

    if result.notified:
        print("\n通知対象の投稿タイトル (先頭5件):")
        rows = conn.execute(
            "SELECT article_id, list_title, price FROM active_articles WHERE article_id IN ({})".format(
                ",".join("?" for _ in result.notified[:5])
            ),
            result.notified[:5],
        ).fetchall()
        for row in rows:
            print(f"  - {row['list_title'][:40]} ({row['price']}円)")

    total_in_db = conn.execute("SELECT COUNT(*) FROM active_articles").fetchone()[0]
    print(f"\nDB内の投稿総数(現時点): {total_in_db}")

    conn.close()
    print("\n完了。同じコマンドをもう一度実行すると、2回目以降は「新規投稿」が"
          "減り、既存投稿の価格変化のみが検知されるはずです。")


if __name__ == "__main__":
    main()
