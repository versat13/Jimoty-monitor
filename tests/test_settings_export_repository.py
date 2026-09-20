"""
repository/settings_export_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection
from repository.discord_notification_repository import update_discord_notification_settings
from repository.pickup_search_repository import update_pickup_search
from repository.scan_settings_repository import (
    update_auto_scan_interval,
    update_retention_settings,
    update_scan_range_settings,
)
from repository.settings_export_repository import (
    EXPORT_FORMAT_VERSION,
    SettingsImportError,
    export_all_settings,
    export_all_settings_json,
    import_all_settings,
    import_all_settings_json,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


def _insert_ng_keyword(conn, keyword, is_active=True):
    conn.execute(
        "INSERT INTO ng_keywords (keyword, is_active) VALUES (?, ?)", (keyword, int(is_active))
    )
    conn.commit()


def _insert_ng_category(conn, category_id, category_name=None, category_level="leaf"):
    conn.execute(
        "INSERT INTO ng_categories (category_id, category_name, category_level) VALUES (?, ?, ?)",
        (category_id, category_name, category_level),
    )
    conn.commit()


def _insert_seller_rule(conn, seller_id, rule_type, seller_name=None, memo=None):
    conn.execute(
        "INSERT INTO seller_rules (seller_id, seller_name, rule_type, memo) VALUES (?, ?, ?, ?)",
        (seller_id, seller_name, rule_type, memo),
    )
    conn.commit()


# ---------------------------------------------------------------------
# export_all_settings
# ---------------------------------------------------------------------


def test_export_empty_settings(conn):
    export = export_all_settings(conn)
    assert export.format_version == EXPORT_FORMAT_VERSION
    assert export.ng_keywords == []
    assert export.ng_categories == []
    assert export.seller_rules == []
    # scan_stateはget_connection時点でデフォルト値の1行が作られている
    # 可能性があるため、Noneまたはdictのどちらかであることだけ確認
    assert export.scan_state is None or isinstance(export.scan_state, dict)
    assert export.pickup_search is None


def test_export_includes_ng_keywords(conn):
    _insert_ng_keyword(conn, "ジャンク")
    _insert_ng_keyword(conn, "訳あり", is_active=False)

    export = export_all_settings(conn)
    assert len(export.ng_keywords) == 2
    keywords = {item["keyword"]: item["is_active"] for item in export.ng_keywords}
    assert keywords["ジャンク"] is True
    assert keywords["訳あり"] is False


def test_export_includes_ng_categories_with_level(conn):
    _insert_ng_category(conn, "fur", "家具", "parent")

    export = export_all_settings(conn)
    assert len(export.ng_categories) == 1
    assert export.ng_categories[0]["category_id"] == "fur"
    assert export.ng_categories[0]["category_level"] == "parent"


def test_export_includes_seller_rules(conn):
    _insert_seller_rule(conn, "seller1", "ng", seller_name="悪質業者")
    _insert_seller_rule(conn, "seller2", "watch", memo="お気に入り")

    export = export_all_settings(conn)
    assert len(export.seller_rules) == 2
    types = {item["seller_id"]: item["rule_type"] for item in export.seller_rules}
    assert types["seller1"] == "ng"
    assert types["seller2"] == "watch"


def test_export_includes_scan_state(conn):
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=7)
    update_auto_scan_interval(conn, auto_scan_interval_minutes=30)

    export = export_all_settings(conn)
    assert export.scan_state["scan_range_mode"] == "days"
    assert export.scan_state["scan_range_value"] == 7
    assert export.scan_state["auto_scan_interval_minutes"] == 30


def test_export_includes_pickup_search(conn):
    update_pickup_search(conn, search_expression="iPhone", include_words=["iPhone"])

    export = export_all_settings(conn)
    assert export.pickup_search["search_expression"] == "iPhone"


def test_export_json_is_valid_json(conn):
    _insert_ng_keyword(conn, "ジャンク")
    json_text = export_all_settings_json(conn)

    import json

    parsed = json.loads(json_text)
    assert parsed["format_version"] == EXPORT_FORMAT_VERSION
    assert parsed["ng_keywords"][0]["keyword"] == "ジャンク"


# ---------------------------------------------------------------------
# import_all_settings
# ---------------------------------------------------------------------


def test_import_ng_keywords(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [{"keyword": "ジャンク", "is_active": True}],
        "ng_categories": [],
        "seller_rules": [],
    }
    import_all_settings(conn, data)

    rows = conn.execute("SELECT keyword, is_active FROM ng_keywords").fetchall()
    assert len(rows) == 1
    assert rows[0]["keyword"] == "ジャンク"
    assert rows[0]["is_active"] == 1


def test_import_overwrites_existing_ng_keywords(conn):
    """
    インポートは既存の全設定を完全に置き換える (マージしない)。
    ユーザー方針:「すべての設定を含めたものだけでよい」。
    """
    _insert_ng_keyword(conn, "既存のワード")

    data = {
        "format_version": 1,
        "ng_keywords": [{"keyword": "新しいワード", "is_active": True}],
        "ng_categories": [],
        "seller_rules": [],
    }
    import_all_settings(conn, data)

    rows = conn.execute("SELECT keyword FROM ng_keywords").fetchall()
    assert len(rows) == 1
    assert rows[0]["keyword"] == "新しいワード"


def test_import_ng_categories_with_level(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [
            {"category_id": "fur", "category_name": "家具", "category_level": "parent"}
        ],
        "seller_rules": [],
    }
    import_all_settings(conn, data)

    row = conn.execute("SELECT category_id, category_level FROM ng_categories").fetchone()
    assert row["category_id"] == "fur"
    assert row["category_level"] == "parent"


def test_import_seller_rules(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [
            {"seller_id": "s1", "seller_name": "業者A", "rule_type": "ng", "memo": None},
            {"seller_id": "s2", "rule_type": "watch"},
        ],
    }
    import_all_settings(conn, data)

    rows = conn.execute("SELECT seller_id, rule_type FROM seller_rules ORDER BY seller_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["rule_type"] == "ng"
    assert rows[1]["rule_type"] == "watch"


def test_import_scan_state_creates_row_when_none(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "scan_state": {
            "prefecture": "fukuoka",
            "category_slug": "sale-all",
            "category_id": None,
            "area_id": "731",
            "area_name": "kitakyushu",
            "region_type": "prefecture_city",
            "area_portal_id": None,
            "distance_km": None,
            "scan_range_mode": "days",
            "scan_range_value": 14,
            "auto_scan_interval_minutes": 60,
        },
    }
    import_all_settings(conn, data)

    row = conn.execute(
        "SELECT scan_range_mode, scan_range_value, auto_scan_interval_minutes FROM scan_state"
    ).fetchone()
    assert row["scan_range_mode"] == "days"
    assert row["scan_range_value"] == 14
    assert row["auto_scan_interval_minutes"] == 60


def test_import_scan_state_updates_existing_row(conn):
    update_scan_range_settings(conn, scan_range_mode="pages", scan_range_value=1)

    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "scan_state": {
            "prefecture": "fukuoka",
            "category_slug": "sale-all",
            "category_id": None,
            "area_id": "731",
            "area_name": "kitakyushu",
            "region_type": "prefecture_city",
            "area_portal_id": None,
            "distance_km": None,
            "scan_range_mode": "days",
            "scan_range_value": 30,
            "auto_scan_interval_minutes": None,
        },
    }
    import_all_settings(conn, data)

    rows = conn.execute("SELECT COUNT(*) AS c FROM scan_state").fetchall()
    assert rows[0]["c"] == 1  # 行が増えていない (UPDATEされた)

    row = conn.execute("SELECT scan_range_mode, scan_range_value FROM scan_state").fetchone()
    assert row["scan_range_mode"] == "days"
    assert row["scan_range_value"] == 30


def test_import_pickup_search(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "pickup_search": {
            "search_expression": "(iPhone|iPad)",
            "include_words_json": '["iPhone", "iPad"]',
            "exclude_words_json": "[]",
            "is_builder_synced": 1,
        },
    }
    import_all_settings(conn, data)

    row = conn.execute("SELECT search_expression FROM pickup_search").fetchone()
    assert row["search_expression"] == "(iPhone|iPad)"


def test_import_full_round_trip(conn):
    """エクスポート→インポートで元の内容が再現されること。"""
    _insert_ng_keyword(conn, "ジャンク")
    _insert_ng_category(conn, "fur", "家具", "parent")
    _insert_seller_rule(conn, "s1", "ng")
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=7)
    update_pickup_search(conn, search_expression="iPhone")

    exported = export_all_settings(conn)

    conn2 = get_connection(":memory:")
    import_all_settings(
        conn2,
        {
            "format_version": exported.format_version,
            "ng_keywords": exported.ng_keywords,
            "ng_categories": exported.ng_categories,
            "seller_rules": exported.seller_rules,
            "scan_state": exported.scan_state,
            "pickup_search": exported.pickup_search,
        },
    )

    reexported = export_all_settings(conn2)
    assert reexported.ng_keywords == exported.ng_keywords
    assert reexported.ng_categories == exported.ng_categories
    assert reexported.seller_rules == exported.seller_rules
    assert reexported.scan_state["scan_range_mode"] == "days"
    assert reexported.pickup_search["search_expression"] == "iPhone"
    conn2.close()


# ---------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------


def test_import_rejects_non_dict():
    conn = get_connection(":memory:")
    with pytest.raises(SettingsImportError):
        import_all_settings(conn, ["not", "a", "dict"])
    conn.close()


def test_import_rejects_missing_format_version(conn):
    with pytest.raises(SettingsImportError):
        import_all_settings(conn, {"ng_keywords": []})


def test_import_rejects_non_list_ng_keywords(conn):
    with pytest.raises(SettingsImportError):
        import_all_settings(conn, {"format_version": 1, "ng_keywords": "not a list"})


def test_import_rejects_ng_keyword_missing_field(conn):
    with pytest.raises(SettingsImportError):
        import_all_settings(
            conn,
            {
                "format_version": 1,
                "ng_keywords": [{"is_active": True}],  # keywordが無い
                "ng_categories": [],
                "seller_rules": [],
            },
        )


def test_import_rejects_invalid_rule_type(conn):
    with pytest.raises(SettingsImportError):
        import_all_settings(
            conn,
            {
                "format_version": 1,
                "ng_keywords": [],
                "ng_categories": [],
                "seller_rules": [{"seller_id": "s1", "rule_type": "invalid"}],
            },
        )


def test_import_json_invalid_json_raises(conn):
    with pytest.raises(SettingsImportError):
        import_all_settings_json(conn, "{invalid json")


def test_import_json_valid_json(conn):
    import json

    json_text = json.dumps(
        {"format_version": 1, "ng_keywords": [], "ng_categories": [], "seller_rules": []}
    )
    import_all_settings_json(conn, json_text)  # 例外が出なければOK


def test_import_does_not_partially_commit_on_error(conn):
    """
    バリデーションエラー発生時、それ以前に処理した内容が中途半端に
    コミットされていないこと (全体がまとめて成功/失敗すべき)。
    """
    _insert_ng_keyword(conn, "既存のワード")

    data = {
        "format_version": 1,
        "ng_keywords": [{"keyword": "新しいワード", "is_active": True}],
        "ng_categories": [],
        "seller_rules": [{"seller_id": "s1", "rule_type": "invalid"}],  # ここでエラー
    }
    with pytest.raises(SettingsImportError):
        import_all_settings(conn, data)

    conn.rollback()
    rows = conn.execute("SELECT keyword FROM ng_keywords").fetchall()
    assert len(rows) == 1
    assert rows[0]["keyword"] == "既存のワード"


# ---------------------------------------------------------------------
# discord_notification / retention のエクスポート・インポート
# (2026-09-14新設、ユーザー報告への対応: 以前はエクスポート対象から
# 漏れていた)
# ---------------------------------------------------------------------


def test_export_includes_discord_notification(conn):
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )

    export = export_all_settings(conn)
    assert export.discord_notification["webhook_url"] == "https://discord.com/api/webhooks/1/abc"
    assert export.discord_notification["enabled"] is True


def test_export_includes_retention_settings(conn):
    update_retention_settings(conn, enabled=False, retention_days=14)

    export = export_all_settings(conn)
    assert export.scan_state["retention_enabled"] == 0
    assert export.scan_state["retention_days"] == 14


def test_import_discord_notification_creates_row_when_none(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "discord_notification": {
            "webhook_url": "https://discord.com/api/webhooks/1/abc",
            "enabled": True,
        },
    }
    import_all_settings(conn, data)

    row = conn.execute(
        "SELECT webhook_url, enabled FROM discord_notification_settings ORDER BY id LIMIT 1"
    ).fetchone()
    assert row["webhook_url"] == "https://discord.com/api/webhooks/1/abc"
    assert bool(row["enabled"]) is True


def test_import_discord_notification_updates_existing_row(conn):
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/old/x", enabled=False
    )

    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "discord_notification": {
            "webhook_url": "https://discord.com/api/webhooks/new/y",
            "enabled": True,
        },
    }
    import_all_settings(conn, data)

    row = conn.execute(
        "SELECT webhook_url, enabled FROM discord_notification_settings ORDER BY id LIMIT 1"
    ).fetchone()
    assert row["webhook_url"] == "https://discord.com/api/webhooks/new/y"
    assert bool(row["enabled"]) is True

    # 常に1件のみ保持されること
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM discord_notification_settings"
    ).fetchone()["c"]
    assert count == 1


def test_import_retention_settings(conn):
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "scan_state": {
            "prefecture": "fukuoka", "category_slug": "sale-all",
            "retention_enabled": 0, "retention_days": 30,
        },
    }
    import_all_settings(conn, data)

    row = conn.execute(
        "SELECT retention_enabled, retention_days FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    assert row["retention_enabled"] == 0
    assert row["retention_days"] == 30


def test_import_old_format_without_discord_or_retention_keys_does_not_fail(conn):
    """
    2026-09-14新設。discord_notification・retention関連のキーを含まない
    旧バージョンのエクスポートファイルをインポートしても、NOT NULL
    制約違反等で失敗しないこと (後方互換性の確認)。
    """
    old_format_data = {
        "format_version": 1,
        "ng_keywords": [{"keyword": "test", "is_active": True}],
        "ng_categories": [],
        "seller_rules": [],
        "scan_state": {
            "prefecture": "fukuoka", "category_slug": "sale-all", "category_id": "all",
            "area_id": "731", "area_name": "kitakyushu",
            "scan_range_mode": "pages", "scan_range_value": 1,
            "auto_scan_interval_minutes": 30,
            # region_type, retention_enabled, retention_days,
            # discord_notification キー自体を含まない (旧形式)
        },
        "pickup_search": None,
    }

    import_all_settings(conn, old_format_data)  # 例外が起きないことがこのテストの主眼

    row = conn.execute(
        "SELECT region_type, retention_enabled, retention_days FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    assert row["region_type"] == "prefecture_city"
    assert row["retention_enabled"] == 1
    assert row["retention_days"] == 7


def test_import_scan_state_without_prefecture_raises(conn):
    """
    scan_stateにprefecture/category_slugが無い (壊れたデータ) 場合は
    SettingsImportErrorを送出すること。
    """
    data = {
        "format_version": 1,
        "ng_keywords": [],
        "ng_categories": [],
        "seller_rules": [],
        "scan_state": {},
    }
    with pytest.raises(SettingsImportError):
        import_all_settings(conn, data)


def test_export_import_round_trip_with_discord_and_retention(conn):
    """
    discord_notification・retention設定を含めたエクスポート→インポートの
    往復で値が保たれること。
    """
    update_discord_notification_settings(
        conn, webhook_url="https://discord.com/api/webhooks/1/abc", enabled=True
    )
    update_retention_settings(conn, enabled=False, retention_days=21)
    update_scan_range_settings(conn, scan_range_mode="days", scan_range_value=7)

    export = export_all_settings(conn)

    # 別のまっさらなconnにインポートして復元できることを確認
    conn2 = get_connection(":memory:")
    import_all_settings(
        conn2,
        {
            "format_version": export.format_version,
            "ng_keywords": export.ng_keywords,
            "ng_categories": export.ng_categories,
            "seller_rules": export.seller_rules,
            "scan_state": export.scan_state,
            "pickup_search": export.pickup_search,
            "discord_notification": export.discord_notification,
        },
    )

    discord_row = conn2.execute(
        "SELECT webhook_url, enabled FROM discord_notification_settings ORDER BY id LIMIT 1"
    ).fetchone()
    assert discord_row["webhook_url"] == "https://discord.com/api/webhooks/1/abc"
    assert bool(discord_row["enabled"]) is True

    scan_row = conn2.execute(
        "SELECT retention_enabled, retention_days FROM scan_state ORDER BY id LIMIT 1"
    ).fetchone()
    assert scan_row["retention_enabled"] == 0
    assert scan_row["retention_days"] == 21

    conn2.close()
