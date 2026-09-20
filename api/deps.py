"""
各ルーターが共通で使うDB接続ヘルパー。

=== 分割の経緯 (2026-09-13) ===

以前は api/main.py に全エンドポイントが同居しており、DB_PATH・get_db()も
同ファイル内のモジュール変数/関数として定義されていた。api/routers/ 以下に
機能別へ分割するにあたり、この2つだけは共通モジュール (このファイル) に
残す。

tests/test_api.py が `monkeypatch.setattr(main_module, "DB_PATH", db_path)`
という形でテスト用DBパスに差し替える設計になっているため、DB_PATHの
「本籍地」は変更せず api.main のままとする。このモジュールの get_db() は
呼び出しの都度 `api.main.DB_PATH` を参照しにいく (importで値をコピーして
しまうと、テストの monkeypatch が効かなくなる)。
"""

import sqlite3

from repository.article_repository import get_connection


def get_db() -> sqlite3.Connection:
    """
    リクエストごとにDB接続を作る簡易実装。

    将来的にFastAPIのDependsによる接続プーリングに置き換える余地は
    あるが、ローカル常駐のシングルユーザーツールという性質上、
    現時点では毎回接続で十分と判断した。
    """
    # 循環importを避けるため、モジュールレベルではなく関数内でimportする
    # (api.main は起動時に各routerをimportするため、api.main側から
    # このモジュールをトップレベルでimportすると循環する)。
    import api.main as main_module

    return get_connection(main_module.DB_PATH)
