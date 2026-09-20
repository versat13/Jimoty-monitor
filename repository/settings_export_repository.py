"""
設定のエクスポート/インポート (2026-09-08 新設)。

対象はユーザーとの打ち合わせで合意した「すべての設定」:
  - NGワード (ng_keywords)
  - NGカテゴリ (ng_categories)
  - 監視/NGユーザー (seller_rules)
  - 取得範囲・監視対象地域・自動更新間隔 (scan_state)
  - 検索タブの保存条件 (pickup_search)

個別設定 (投稿ごとの監視☆や価格履歴など、投稿データそのもの) は
対象外。あくまで「このツールの動作を決める設定」のみを対象とする
(ユーザー方針: 「個別設定は考慮しなくて良い」)。

エクスポートは1つのJSON構造にまとめて返す。インポートは全項目を
まとめて上書きする単純な仕様とし、部分的なマージ (一部の項目だけ
反映する、既存データと統合する等) は行わない
(ユーザー方針: 「すべての設定を含めたものだけでよい」)。
"""

import json
from dataclasses import dataclass, field

# 現在のエクスポート形式のバージョン。将来フォーマットを変更する際に
# インポート側で判定できるようにしておく。
EXPORT_FORMAT_VERSION = 1


@dataclass
class SettingsExport:
    format_version: int
    ng_keywords: list[dict] = field(default_factory=list)
    ng_categories: list[dict] = field(default_factory=list)
    seller_rules: list[dict] = field(default_factory=list)
    scan_state: dict | None = None
    pickup_search: dict | None = None
    # 2026-09-14追加: Discord通知設定。以前はエクスポート対象から
    # 漏れていた (ユーザー報告)。webhook_urlをそのままエクスポート
    # する点に注意 (バックアップ目的のエクスポートのため許容するが、
    # 他人とエクスポートファイルを共有する場合は流出リスクがある
    # ことをフロントエンド側で案内する)。
    discord_notification: dict | None = None


def export_all_settings(conn) -> SettingsExport:
    """全設定をエクスポート用のデータ構造として組み立てる。"""
    ng_keywords = [
        {"keyword": r["keyword"], "is_active": bool(r["is_active"])}
        for r in conn.execute("SELECT keyword, is_active FROM ng_keywords").fetchall()
    ]

    ng_categories = [
        {
            "category_id": r["category_id"],
            "category_name": r["category_name"],
            "category_level": r["category_level"],
            "is_active": bool(r["is_active"]),
        }
        for r in conn.execute(
            "SELECT category_id, category_name, category_level, is_active FROM ng_categories"
        ).fetchall()
    ]

    seller_rules = [
        {
            "seller_id": r["seller_id"],
            "seller_name": r["seller_name"],
            "rule_type": r["rule_type"],
            "memo": r["memo"],
            "is_active": bool(r["is_active"]),
        }
        for r in conn.execute(
            "SELECT seller_id, seller_name, rule_type, memo, is_active FROM seller_rules"
        ).fetchall()
    ]

    scan_row = conn.execute(
        """
        SELECT prefecture, category_slug, category_id, area_id, area_name,
               region_type, area_portal_id, distance_km,
               scan_range_mode, scan_range_value, auto_scan_interval_minutes,
               retention_enabled, retention_days
        FROM scan_state ORDER BY id LIMIT 1
        """
    ).fetchone()
    scan_state = dict(scan_row) if scan_row is not None else None

    pickup_row = conn.execute(
        "SELECT search_expression, include_words_json, exclude_words_json, is_builder_synced "
        "FROM pickup_search ORDER BY id LIMIT 1"
    ).fetchone()
    pickup_search = dict(pickup_row) if pickup_row is not None else None

    # 2026-09-14追加: Discord通知設定 (以前はエクスポート対象から
    # 漏れていた)。
    discord_row = conn.execute(
        "SELECT webhook_url, enabled FROM discord_notification_settings ORDER BY id LIMIT 1"
    ).fetchone()
    discord_notification = (
        {"webhook_url": discord_row["webhook_url"], "enabled": bool(discord_row["enabled"])}
        if discord_row is not None
        else None
    )

    return SettingsExport(
        format_version=EXPORT_FORMAT_VERSION,
        ng_keywords=ng_keywords,
        ng_categories=ng_categories,
        seller_rules=seller_rules,
        scan_state=scan_state,
        pickup_search=pickup_search,
        discord_notification=discord_notification,
    )


def export_all_settings_json(conn) -> str:
    """export_all_settings() の結果をJSON文字列として返す。"""
    export = export_all_settings(conn)
    return json.dumps(
        {
            "format_version": export.format_version,
            "ng_keywords": export.ng_keywords,
            "ng_categories": export.ng_categories,
            "seller_rules": export.seller_rules,
            "scan_state": export.scan_state,
            "pickup_search": export.pickup_search,
            "discord_notification": export.discord_notification,
        },
        ensure_ascii=False,
        indent=2,
    )


class SettingsImportError(Exception):
    """インポートするデータの形式が不正な場合に送出する。"""


def _require_dict(data, name: str) -> dict:
    if not isinstance(data, dict):
        raise SettingsImportError(f"{name}はオブジェクト形式である必要があります")
    return data


def import_all_settings(conn, data: dict) -> None:
    """
    エクスポートされたJSON (辞書化済み) を読み込み、全設定を上書きする。

    「すべての設定をまとめて上書きする」単純な仕様のため、既存の
    ng_keywords/ng_categories/seller_rules/pickup_searchは一旦全件
    削除してからインポート内容で作り直す。scan_stateは1行のみの
    テーブルのため、既存行があればUPDATE、無ければINSERTする。

    Raises:
        SettingsImportError: 必須項目が無い・型が不正な場合。
            この場合、呼び出し元のトランザクションは呼び出し元の
            責務でロールバックすること (この関数はconn.commit()を
            呼ぶが、例外発生時はまだcommitしていない)。
    """
    _require_dict(data, "インポートデータ")

    if "format_version" not in data:
        raise SettingsImportError("format_versionがありません")

    ng_keywords = data.get("ng_keywords", [])
    ng_categories = data.get("ng_categories", [])
    seller_rules = data.get("seller_rules", [])
    scan_state = data.get("scan_state")
    pickup_search = data.get("pickup_search")
    discord_notification = data.get("discord_notification")

    if not isinstance(ng_keywords, list):
        raise SettingsImportError("ng_keywordsはリスト形式である必要があります")
    if not isinstance(ng_categories, list):
        raise SettingsImportError("ng_categoriesはリスト形式である必要があります")
    if not isinstance(seller_rules, list):
        raise SettingsImportError("seller_rulesはリスト形式である必要があります")

    # NGワード: 全件削除して作り直す。
    conn.execute("DELETE FROM ng_keywords")
    for item in ng_keywords:
        _require_dict(item, "ng_keywords の要素")
        if "keyword" not in item:
            raise SettingsImportError("ng_keywordsの要素にkeywordがありません")
        conn.execute(
            "INSERT INTO ng_keywords (keyword, is_active) VALUES (?, ?)",
            (item["keyword"], int(item.get("is_active", True))),
        )

    # NGカテゴリ: 全件削除して作り直す。
    conn.execute("DELETE FROM ng_categories")
    for item in ng_categories:
        _require_dict(item, "ng_categories の要素")
        if "category_id" not in item:
            raise SettingsImportError("ng_categoriesの要素にcategory_idがありません")
        conn.execute(
            "INSERT INTO ng_categories (category_id, category_name, category_level, is_active) "
            "VALUES (?, ?, ?, ?)",
            (
                item["category_id"],
                item.get("category_name"),
                item.get("category_level", "leaf"),
                int(item.get("is_active", True)),
            ),
        )

    # 監視/NGユーザー: 全件削除して作り直す。
    conn.execute("DELETE FROM seller_rules")
    for item in seller_rules:
        _require_dict(item, "seller_rules の要素")
        if "seller_id" not in item or "rule_type" not in item:
            raise SettingsImportError("seller_rulesの要素にseller_id/rule_typeがありません")
        if item["rule_type"] not in ("ng", "watch"):
            raise SettingsImportError(f"不正なrule_typeです: {item['rule_type']}")
        conn.execute(
            "INSERT INTO seller_rules (seller_id, seller_name, rule_type, memo, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item["seller_id"],
                item.get("seller_name"),
                item["rule_type"],
                item.get("memo"),
                int(item.get("is_active", True)),
            ),
        )

    # 取得範囲・自動更新間隔・保存期間: 1行のみのテーブルなので既存行が
    # あればUPDATE、無ければINSERTする (全件削除して作り直す方式に
    # すると、AUTOINCREMENTのidがズレて他テーブルとの参照関係が崩れる
    # 懸念は無いが、単一行テーブルの流儀としてUPSERTの方が自然なため)。
    #
    # 2026-09-14追加: NOT NULL制約がある列について、旧バージョンで
    # 作成されたエクスポートファイル (該当キーを含まない) を
    # インポートした際にscan_state.get(c)がNoneを返してINSERT/UPDATE
    # が失敗しないよう、db/schema.sqlのDEFAULT句と同じ値へフォール
    # バックする。
    #   - region_type: 旧バージョンではエクスポート対象外だった列
    #     (2026-09-14に発覚。マイエリア機能の追加時にエクスポート/
    #     インポートへの追加が漏れていた)。
    #   - retention_enabled/retention_days: 以前はエクスポート自体
    #     から漏れていた (今回追加)。
    if scan_state is not None:
        _require_dict(scan_state, "scan_state")
        if not scan_state.get("prefecture") or not scan_state.get("category_slug"):
            raise SettingsImportError(
                "scan_stateにはprefecture/category_slugが必須です"
            )
        row = conn.execute("SELECT id FROM scan_state ORDER BY id LIMIT 1").fetchone()
        columns = [
            "prefecture", "category_slug", "category_id", "area_id", "area_name",
            "region_type", "area_portal_id", "distance_km",
            "scan_range_mode", "scan_range_value", "auto_scan_interval_minutes",
            "retention_enabled", "retention_days",
        ]
        # NOT NULL制約がある列のみ、db/schema.sqlのDEFAULT句と同じ
        # 値をここに列挙する。ここに無い列はNULL許容、またはこの後の
        # DEFAULT_SCAN_RANGE_MODE等の別ロジックで扱う。
        not_null_defaults = {
            "region_type": "prefecture_city",
            "scan_range_mode": "pages",
            "scan_range_value": 1,
            "retention_enabled": 1,
            "retention_days": 7,
        }
        values = [
            scan_state.get(c) if scan_state.get(c) is not None else not_null_defaults.get(c)
            for c in columns
        ]
        if row is None:
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO scan_state ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        else:
            set_clause = ", ".join(f"{c} = ?" for c in columns)
            conn.execute(
                f"UPDATE scan_state SET {set_clause} WHERE id = ?",
                [*values, row["id"]],
            )

    # 検索タブの保存条件: scan_stateと同様、1行のみのテーブル。
    if pickup_search is not None:
        _require_dict(pickup_search, "pickup_search")
        row = conn.execute("SELECT id FROM pickup_search ORDER BY id LIMIT 1").fetchone()
        columns = [
            "search_expression", "include_words_json", "exclude_words_json", "is_builder_synced",
        ]
        values = [pickup_search.get(c) for c in columns]
        if row is None:
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO pickup_search ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        else:
            set_clause = ", ".join(f"{c} = ?" for c in columns)
            conn.execute(
                f"UPDATE pickup_search SET {set_clause} WHERE id = ?",
                [*values, row["id"]],
            )

    # 2026-09-14追加: Discord通知設定。scan_state・pickup_searchと
    # 同様、1行のみのテーブル。旧形式のエクスポートファイル (このキー
    # 自体が無い) の場合はNoneのままなのでスキップし、既存の設定
    # (未設定ならデフォルトの空文字・無効のまま) には触れない。
    if discord_notification is not None:
        _require_dict(discord_notification, "discord_notification")
        row = conn.execute(
            "SELECT id FROM discord_notification_settings ORDER BY id LIMIT 1"
        ).fetchone()
        webhook_url = discord_notification.get("webhook_url", "")
        enabled = int(discord_notification.get("enabled", False))
        if row is None:
            conn.execute(
                "INSERT INTO discord_notification_settings (webhook_url, enabled) VALUES (?, ?)",
                (webhook_url, enabled),
            )
        else:
            conn.execute(
                "UPDATE discord_notification_settings SET webhook_url = ?, enabled = ? WHERE id = ?",
                (webhook_url, enabled, row["id"]),
            )

    conn.commit()


def import_all_settings_json(conn, json_text: str) -> None:
    """import_all_settings() のJSON文字列版。"""
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, TypeError) as e:
        raise SettingsImportError(f"JSONとして解析できません: {e}")
    import_all_settings(conn, data)
