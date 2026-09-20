"""
巡回ジョブ本体 (後方互換のための再エクスポート層)。

=== 分割の経緯 (2026-09-13) ===

以前はこのファイル1つに巡回ジョブの全ロジックが同居していたが、
960行を超えて見通しが悪くなっていたため、以下へ分割した。

    - scheduler/scan_types.py   : ScanResult等のデータクラス
    - scheduler/scan_helpers.py : 日付計算・NGルール読み込み等の
                                  小さなヘルパー関数
    - scheduler/scan_runner.py : _scan_one_page・run_scan・
                                  run_scan_with_range・
                                  _fetch_and_store_detail・
                                  confirm_single_missing_article・
                                  fetch_seller_profile_on_demand
                                  (巡回処理の本体)

このファイルは、既存の `from scheduler.job import run_scan` のような
import文が分割後も動作し続けるよう、実体である scheduler.scan_runner
から主要な関数・定数を再エクスポートするだけの薄い窓口として残す。

新規コードは scheduler.scan_runner を直接importすることを推奨する。
テスト (tests/test_scheduler_job.py 等) が
`patch("scheduler.job.fetch_html")` のような形でこのモジュール上の
名前を直接書き換えている場合、実体である scheduler.scan_runner 側の
名前をpatchするよう修正済み (patch対象は呼び出しが実際に行われる
モジュールでなければ効果がないため)。
"""

from scheduler.scan_runner import (
    ARTICLES_PER_PAGE,
    MAX_PAGES_SAFETY_LIMIT,
    _fetch_and_store_detail,
    _scan_one_page,
    confirm_single_missing_article,
    fetch_seller_profile_on_demand,
    run_scan,
    run_scan_with_range,
)
from scheduler.scan_types import MissingCheckResult, PageScanResult, ScanResult

__all__ = [
    "ARTICLES_PER_PAGE",
    "MAX_PAGES_SAFETY_LIMIT",
    "ScanResult",
    "MissingCheckResult",
    "PageScanResult",
    "run_scan",
    "run_scan_with_range",
    "confirm_single_missing_article",
    "fetch_seller_profile_on_demand",
    "_fetch_and_store_detail",
    "_scan_one_page",
]
