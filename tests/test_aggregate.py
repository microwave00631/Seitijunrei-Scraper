"""集約(まとめ直し)パイプラインのテスト。ソースとジオコーダはモック。"""

import pytest

from app.aggregate import AggregateConfig, aggregate, gather_posts
from app.geocode import GeoResult
from app.sources import Post, SourceError


class FakeSource:
    name = "fake"

    def __init__(self, posts, error=None):
        self._posts = posts
        self._error = error

    def search(self, query, limit=20):
        if self._error:
            raise SourceError(self._error)
        return list(self._posts)


class FakeGeocoder:
    """地名→固定座標の辞書。未知の地名は空(=ヒットなし)。"""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def search(self, query, limit=1, countrycodes=None):
        self.calls.append(query)
        if query in self.table:
            lat, lon = self.table[query]
            return [GeoResult(lat, lon, query, "node", 1, 0.5)]
        return []

    def close(self):
        pass


def _post(text, url):
    return Post(text=text, url=url, source_name="fake")


def test_aggregate_groups_mentions_across_posts():
    posts = [
        _post("鷲宮神社に行った", "https://note.com/a"),
        _post("鷲宮神社よかった", "https://note.com/b"),
        _post("大洗海岸も最高", "https://note.com/c"),
    ]
    geo = FakeGeocoder({"鷲宮神社": (36.1, 139.6), "大洗海岸": (36.3, 140.5)})
    cfg = AggregateConfig(keywords=["聖地巡礼"], take_screenshots=False)
    store, meta = aggregate("作品", [FakeSource(posts)], geo, cfg)

    assert meta["posts_found"] == 3
    names = {s.name: s for s in store.seiti}
    assert "鷲宮神社" in names and "大洗海岸" in names
    # 鷲宮神社は2投稿から言及 → mentions が2件に集約される。
    assert len(names["鷲宮神社"].mentions) == 2
    # 言及数の多い順に並ぶ。
    assert store.seiti[0].name == "鷲宮神社"


def test_geocode_miss_recorded():
    posts = [_post("聖地神社に行った", "https://note.com/x")]
    geo = FakeGeocoder({})  # 何も返さない
    store, meta = aggregate("作品", [FakeSource(posts)], geo,
                            AggregateConfig(keywords=["聖地"]))
    assert store.seiti == []
    assert "聖地神社" in meta["geocode_misses"]


def test_source_error_surfaced_not_swallowed():
    geo = FakeGeocoder({})
    posts_ok = [_post("鷲宮神社", "https://note.com/a")]
    sources = [FakeSource(posts_ok), FakeSource([], error="403 Forbidden")]
    geo = FakeGeocoder({"鷲宮神社": (36.1, 139.6)})
    store, meta = aggregate("作品", sources, geo,
                            AggregateConfig(keywords=["聖地巡礼"]))
    # 片方失敗してももう片方は集約され、エラーは meta に残る。
    assert len(store.seiti) == 1
    assert any("403" in e for e in meta["errors"])


def test_dedup_close_coords_merges_mentions():
    posts = [
        _post("A神社へ", "https://note.com/a"),
        _post("B神社へ", "https://note.com/b"),
    ]
    # 別名だがほぼ同一座標(約0.5m)→ 統合され mentions がまとまる。
    geo = FakeGeocoder({"A神社": (35.0, 135.0), "B神社": (35.0000005, 135.0)})
    store, meta = aggregate("作品", [FakeSource(posts)], geo,
                            AggregateConfig(keywords=["聖地"]))
    assert len(store.seiti) == 1
    assert len(store.candidates) == 1
    assert len(store.seiti[0].mentions) == 2  # 出典がマージされている


def test_empty_item_rejected():
    with pytest.raises(ValueError):
        aggregate("  ", [], FakeGeocoder({}))


def test_gather_posts_collects_all_keywords():
    posts = [_post("x神社", "u")]
    src = FakeSource(posts)
    got, errors = gather_posts("作品", [src],
                               AggregateConfig(keywords=["聖地", "聖地巡礼"]))
    assert len(got) == 2  # 2キーワード分
    assert errors == []
