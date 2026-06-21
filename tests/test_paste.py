"""貼り付けテキスト解析(座標/URL抽出・aggregate_from_text)のテスト。"""

import pytest

from app.aggregate import AggregateConfig, aggregate_from_text
from app.extract import extract_coords, extract_urls, strip_html
from app.geocode import GeoResult


class FakeGeocoder:
    def __init__(self, table):
        self.table = table

    def search(self, query, limit=1, countrycodes=None):
        if query in self.table:
            lat, lon = self.table[query]
            return [GeoResult(lat, lon, query, "node", 1, 0.5)]
        return []

    def close(self):
        pass


def test_extract_urls():
    t = "記事はこちら https://note.com/taro/n/abc123 です。(末尾)"
    assert extract_urls(t) == ["https://note.com/taro/n/abc123"]


def test_extract_coords_google_at():
    t = "https://www.google.com/maps/@35.123456,139.654321,17z"
    assert extract_coords(t) == [(35.123456, 139.654321)]


def test_extract_coords_3d4d_and_q():
    assert (35.0, 135.0) in extract_coords("...!3d35.0!4d135.0...")
    assert (34.5, 135.5) in extract_coords("https://maps.google.com/?q=34.5,135.5")


def test_extract_coords_bare_japan_only():
    # 日本域は採用、域外(裸)は不採用。
    assert extract_coords("36.1234, 139.5678") == [(36.1234, 139.5678)]
    assert extract_coords("12.3456, 200.7890") == []


def test_strip_html():
    assert "鷲宮神社" in strip_html("<p>鷲宮神社</p>")


def test_aggregate_from_text_direct_coords_no_geocoder():
    text = "鷲宮神社 https://note.com/a https://www.google.com/maps/@36.10,139.65,17z"
    store, meta = aggregate_from_text("らき☆すた", text, geocoder=None)
    assert meta["mode"] if "mode" in meta else True  # mode は main 側で付与
    assert meta["direct_coords"] == 1
    assert len(store.seiti) == 1
    s = store.seiti[0]
    assert abs(s.coordinate.lat - 36.10) < 1e-6
    assert s.name == "鷲宮神社"
    assert "https://note.com/a" in s.mentions


def test_aggregate_from_text_geocodes_places():
    text = "大洗磯前神社に行った https://note.com/x"
    geo = FakeGeocoder({"大洗磯前神社": (36.31, 140.58)})
    store, meta = aggregate_from_text("ガルパン", text, geocoder=geo)
    assert meta["geocoded"] == 1
    assert len(store.seiti) == 1
    assert store.seiti[0].name == "大洗磯前神社"


def test_aggregate_from_text_dedup_direct_and_geocoded():
    # 直接座標と地名ジオコーディングがほぼ同一点 → 統合される。
    text = (
        "鷲宮神社 https://note.com/a https://www.google.com/maps/@36.100000,139.650000,17z\n\n"
        "鷲宮神社 また行った https://note.com/b"
    )
    geo = FakeGeocoder({"鷲宮神社": (36.1000005, 139.650000)})
    store, meta = aggregate_from_text("らき☆すた", text, geocoder=geo)
    assert len(store.seiti) == 1
    # 直接座標分＋地名分の出典がまとまる。
    assert len(store.seiti[0].mentions) >= 2


def test_aggregate_from_text_empty_rejected():
    with pytest.raises(ValueError):
        aggregate_from_text("x", "   ", geocoder=None)


def test_no_geocoder_records_note():
    store, meta = aggregate_from_text("x", "鷲宮神社に行った", geocoder=None)
    assert store.seiti == []
    assert any("geocoder" in e for e in meta["errors"])
