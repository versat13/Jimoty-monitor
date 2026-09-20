"""
repository/area_options_repository.py のユニットテスト。
"""

import pytest

from repository.article_repository import get_connection
from repository.area_options_repository import (
    get_area_options,
    get_area_options_fetched_at,
    replace_area_options,
)
from scraper.area_list_parser import AreaOption


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def sample_options():
    return [
        AreaOption(area_id="730", area_name="fukuoka", display_name="福岡市"),
        AreaOption(area_id="731", area_name="kitakyushu", display_name="北九州市"),
        AreaOption(area_id="732", area_name="omuta", display_name="大牟田市"),
    ]


def test_get_area_options_empty_when_never_fetched(conn):
    assert get_area_options(conn, "fukuoka") == []


def test_replace_and_get_area_options(conn, sample_options):
    count = replace_area_options(conn, "fukuoka", sample_options)
    assert count == 3

    options = get_area_options(conn, "fukuoka")
    assert len(options) == 3
    assert options[0].area_id == "730"
    assert options[0].display_name == "福岡市"
    assert options[1].area_id == "731"
    assert options[1].area_name == "kitakyushu"


def test_get_area_options_preserves_order(conn, sample_options):
    replace_area_options(conn, "fukuoka", sample_options)

    options = get_area_options(conn, "fukuoka")
    assert [o.area_id for o in options] == ["730", "731", "732"]


def test_replace_area_options_overwrites_previous(conn, sample_options):
    """再取得すると、古い候補が消えて新しい一覧だけが残ること。"""
    replace_area_options(conn, "fukuoka", sample_options)

    new_options = [AreaOption(area_id="999", area_name="sample", display_name="サンプル市")]
    replace_area_options(conn, "fukuoka", new_options)

    options = get_area_options(conn, "fukuoka")
    assert len(options) == 1
    assert options[0].area_id == "999"


def test_area_options_independent_per_prefecture(conn, sample_options):
    """都道府県が違えばキャッシュも独立していること。"""
    replace_area_options(conn, "fukuoka", sample_options)
    replace_area_options(conn, "osaka", [AreaOption(area_id="1", area_name="osaka_city", display_name="大阪市")])

    fukuoka_options = get_area_options(conn, "fukuoka")
    osaka_options = get_area_options(conn, "osaka")

    assert len(fukuoka_options) == 3
    assert len(osaka_options) == 1
    assert osaka_options[0].display_name == "大阪市"


def test_get_area_options_fetched_at_none_when_never_fetched(conn):
    assert get_area_options_fetched_at(conn, "fukuoka") is None


def test_get_area_options_fetched_at_returns_timestamp(conn, sample_options):
    replace_area_options(conn, "fukuoka", sample_options)

    fetched_at = get_area_options_fetched_at(conn, "fukuoka")
    assert fetched_at is not None
