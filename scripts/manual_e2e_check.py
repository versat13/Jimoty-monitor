"""
実HTTPアクセスを伴う、エンドツーエンドの動作確認スクリプト。

このスクリプトはユーザーの実行環境 (ローカルPC) で実行することを想定している。
Claude.aiのbash_tool環境からはjmty.jpへのアクセスがネットワーク設定で
ブロックされているため、このリポジトリの開発時点ではこのスクリプト自体の
実行確認ができていない (fetch.pyの個々の関数は実データを使ったユニット
テストで検証済みだが、実際のHTTP通信を伴う一連の流れの確認はまだ)。

=== 実行方法 ===

    cd jimoty-monitor
    pip install httpx beautifulsoup4 lxml
    python3 scripts/manual_e2e_check.py

正常に動けば、以下が標準出力に表示される:
    1. 一覧ページの取得件数・広告除外後の件数
    2. 先頭3件の投稿タイトル・価格
    3. 先頭1件について、個別ページを取得しパースした結果
       (出品者名・本文・受付終了フラグなど)

=== 注意 ===

- このスクリプトは1回だけ一覧ページと個別ページを1件ずつ取得する。
  ループでの巡回・定期実行はscheduler/job.py (未実装) の責務であり、
  ここでは行わない。
- 低頻度アクセスの原則に従い、このスクリプトを繰り返し実行する場合は
  手動で間隔を空けること。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows環境でファイルへリダイレクト(> result.txt)すると、標準出力の
# エンコーディングがcp932 (Shift-JIS系) になり、絵文字を含むタイトル
# (例: 🉐) でUnicodeEncodeErrorになることが実機検証で判明した (2026-08-23)。
# 画面に直接表示する場合はWindows Terminal側の対応でエラーにならないが、
# リダイレクト時は明示的にUTF-8へ切り替える必要がある。
if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper.detail_parser import parse_detail_page
from scraper.fetch import build_client, build_list_url, fetch_html
from scraper.list_parser import parse_list_page


def main() -> None:
    # 全カテゴリ一覧を使う (list_real.html の検証時と同じ条件)。
    #
    # 【経緯】以前のバージョンではパソコンカテゴリ限定
    # (sale-pcp/g-1199) をデフォルトにしていたが、これは意図的な選定では
    # なく、開発初期にweb_searchでたまたま最初にヒットしたURLを
    # 惰性で使い続けていたもの。
    #
    # 全カテゴリ一覧に変更した理由:
    #   1. tests/fixtures/list_real.html (ユニットテストの基準データ) も
    #      全カテゴリ一覧であり、条件を揃えた方が「テストで通った内容と
    #      同じものが実機でも動く」ことの確認になる。
    #   2. 追補仕様v1.1で発見した「受付終了」ブロックは、規模の大きい
    #      全カテゴリ一覧 (242,690件規模) でのみ確認できており、
    #      パソコンカテゴリ限定 (275件) のような小規模カテゴリでは
    #      出現しない可能性がある。受付終了ブロックの実物検証を
    #      進めるには、こちらの方が見つかる可能性が高い。
    #
    # 件数が非常に多いカテゴリのため、取得できるのは1ページ目の
    # 投稿のみ (ページネーションはこのスクリプトでは辿らない)。
    url = build_list_url(
        "fukuoka", "sale-all", category_id="all", area_id="731", area_name="kitakyushu"
    )
    print(f"[1] 一覧ページを取得します: {url}")

    with build_client() as client:
        list_html = fetch_html(client, url)
        print(f"    -> 取得成功 ({len(list_html)}文字)")

        articles = parse_list_page(list_html, current_year=2026)
        print(f"    -> パース結果: {len(articles)}件 (広告除外後)")

        print("\n[2] 先頭3件:")
        for a in articles[:3]:
            print(f"    - id={a.article_id} title={a.list_title[:30]!r} price={a.price}円")

        if not articles:
            print("\n投稿が0件だったため、個別ページの検証はスキップします。")
            return

        first = articles[0]
        print(f"\n[3] 先頭1件の個別ページを取得します: {first.url}")

        # 低頻度アクセスの原則に配慮し、一覧取得から少し間隔を空ける
        time.sleep(2)

        detail_html = fetch_html(client, first.url)
        print(f"    -> 取得成功 ({len(detail_html)}文字)")

        detail = parse_detail_page(detail_html)
        print("    -> パース結果:")
        print(f"       タイトル: {detail.full_title}")
        print(f"       価格: {detail.price}円")
        print(f"       カテゴリ: {detail.category_name}")
        print(f"       受付終了: {detail.is_closed}")
        print(f"       出品者: {detail.seller.seller_name if detail.seller else '取得失敗'}")
        print(f"       本文(先頭40字): {(detail.description_full or '')[:40]}")

    print("\n完了。一覧・個別ページとも取得・パースに成功しました。")


if __name__ == "__main__":
    main()
