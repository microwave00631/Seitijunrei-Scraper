"""SeitiStore の重複統合・候補退避ロジックのテスト。"""

import pytest

from app.models import (
    Coordinate,
    Seiti,
    SeitiStore,
    haversine_distance_m,
    MAX_CANDIDATES,
)


def make_seiti(lat, lon, name="", screenshot=None, source="src"):
    return Seiti(
        coordinate=Coordinate(lat, lon),
        source=source,
        screenshot_path=screenshot,
        name=name,
    )


def test_haversine_known_distance():
    # 緯度 0.00001 度 ≒ 1.11m。
    d = haversine_distance_m(35.0, 135.0, 35.00001, 135.0)
    assert 1.0 < d < 1.2


def test_coordinate_validates_range():
    with pytest.raises(ValueError):
        Coordinate(91.0, 0.0)
    with pytest.raises(ValueError):
        Coordinate(0.0, 181.0)


def test_distinct_places_kept_separate():
    store = SeitiStore()
    assert store.add(make_seiti(35.0, 135.0)) is True
    # 約 111m 離れている → 別物。
    assert store.add(make_seiti(35.001, 135.0)) is True
    assert len(store.seiti) == 2
    assert len(store.candidates) == 0


def test_within_1m_merged_into_candidate():
    store = SeitiStore()
    store.add(make_seiti(35.0, 135.0, name="A"))
    # 約 0.55m → 1m 以内 → 同一視。
    added = store.add(make_seiti(35.000005, 135.0, name="B"))
    assert added is False
    assert len(store.seiti) == 1
    assert len(store.candidates) == 1


def test_more_complete_wins_primary():
    store = SeitiStore()
    store.add(make_seiti(35.0, 135.0, name="poor"))
    # スクショ付き(情報量多)の新規が primary を奪い、既存が候補へ。
    store.add(make_seiti(35.0000005, 135.0, name="rich", screenshot="x.png"))
    assert store.seiti[0].name == "rich"
    assert store.candidates[0].name == "poor"


def test_tie_keeps_existing_primary():
    store = SeitiStore()
    store.add(make_seiti(35.0, 135.0, name="first"))
    store.add(make_seiti(35.0000005, 135.0, name="second"))
    # 同点なら既存(first)が残り、新規(second)が候補へ。
    assert store.seiti[0].name == "first"
    assert store.candidates[0].name == "second"


def test_candidates_capped_at_max():
    store = SeitiStore(max_candidates=MAX_CANDIDATES)
    store.add(make_seiti(35.0, 135.0, name="primary"))
    # 同一地点の重複を上限+10 件投入。
    for i in range(MAX_CANDIDATES + 10):
        s = make_seiti(35.0000005, 135.0, name=f"dup{i}")
        s.found_at = 1000.0 + i  # 古い順を明示。
        store.add(s)
    assert len(store.candidates) == MAX_CANDIDATES
    # 最古(dup0..dup9)が破棄され、新しいものが残る。
    names = {c.name for c in store.candidates}
    assert "dup0" not in names
    assert f"dup{MAX_CANDIDATES + 9}" in names


def test_to_dict_shape():
    store = SeitiStore()
    store.add(make_seiti(35.0, 135.0, name="A"))
    d = store.to_dict()
    assert d["seiti"][0]["coordinate"] == {"lat": 35.0, "lon": 135.0}
    assert d["max_candidates"] == 80
    assert d["dedup_radius_m"] == 1.0
