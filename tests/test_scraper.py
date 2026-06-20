"""scraper の orchestration テスト(Nominatim はモックで差し替え)。"""

import pytest

from app.geocode import GeoResult
from app.scraper import ScrapeConfig, build_queries, scrape


class FakeClient:
    """検索結果を固定で返すダミークライアント。"""

    def __init__(self, results_by_query=None, default=None):
        self.results_by_query = results_by_query or {}
        self.default = default or []
        self.calls = []
        self.closed = False

    def search(self, query, limit=5):
        self.calls.append(query)
        return self.results_by_query.get(query, self.default)

    def close(self):
        self.closed = True


def geo(lat, lon, osm_id=1, osm_type="node", name="place"):
    return GeoResult(
        lat=lat, lon=lon, display_name=name,
        osm_type=osm_type, osm_id=osm_id, importance=0.5,
    )


def test_build_queries_default_keywords():
    qs = build_queries("らき☆すた", ["聖地", "聖地巡礼"])
    assert qs == ["らき☆すた 聖地", "らき☆すた 聖地巡礼"]


def test_scrape_rejects_empty_item():
    with pytest.raises(ValueError):
        scrape("   ", ScrapeConfig(take_screenshots=False))


def test_scrape_collects_multiple_seiti():
    cfg = ScrapeConfig(keywords=["聖地"], take_screenshots=False)
    client = FakeClient(default=[
        geo(35.0, 135.0, osm_id=1),
        geo(36.0, 136.0, osm_id=2),
    ])
    store = scrape("テスト作品", cfg, client=client)
    assert len(store.seiti) == 2
    assert client.calls == ["テスト作品 聖地"]
    # 外部から渡したクライアントは close されない。
    assert client.closed is False


def test_scrape_merges_close_points_across_queries():
    cfg = ScrapeConfig(keywords=["聖地", "聖地巡礼"], take_screenshots=False)
    client = FakeClient(results_by_query={
        "作品 聖地": [geo(35.0, 135.0, osm_id=1)],
        # 1m 以内(約0.5m)→ 別クエリでも同一聖地として統合される。
        "作品 聖地巡礼": [geo(35.0000005, 135.0, osm_id=2)],
    })
    store = scrape("作品", cfg, client=client)
    assert len(store.seiti) == 1
    assert len(store.candidates) == 1


def test_scrape_continues_when_one_query_fails():
    cfg = ScrapeConfig(keywords=["聖地", "聖地巡礼"], take_screenshots=False)

    class FlakyClient(FakeClient):
        def search(self, query, limit=5):
            if query.endswith("聖地"):
                raise RuntimeError("boom")
            return [geo(35.0, 135.0, osm_id=9)]

    store = scrape("作品", cfg, client=FlakyClient())
    # 片方が例外でも、もう片方の結果は収集される。
    assert len(store.seiti) == 1
