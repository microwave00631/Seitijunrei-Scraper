"""地名抽出ヒューリスティックのテスト。"""

from app.extract import extract_places


def test_extracts_shrine_and_station():
    text = "鷲宮神社に行ってきた。帰りは鷲宮駅から。とても良い聖地巡礼だった。"
    places = extract_places(text)
    assert "鷲宮神社" in places
    assert "鷲宮駅" in places


def test_dedup_and_order():
    text = "大洗磯前神社。大洗磯前神社。大洗海岸。"
    places = extract_places(text)
    assert places == ["大洗磯前神社", "大洗海岸"]


def test_bare_suffix_not_extracted():
    # 固有名のない「神社」「駅」単体は拾わない。
    assert extract_places("神社に行った。駅に着いた。") == []


def test_stopwords_filtered():
    assert "最寄駅" not in extract_places("最寄駅で降りる")


def test_empty():
    assert extract_places("") == []
    assert extract_places("ただの本文で地名なし") == []
