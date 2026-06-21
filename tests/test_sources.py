"""ソース(note 応答パース / Twitter トークン必須)のテスト。"""

import pytest

from app.sources import NoteSource, Post, SourceError, TwitterSource, _strip_html


def test_strip_html():
    assert _strip_html("<p>あ&amp;い</p>") == "あ&い"


def test_note_parses_v3_schema():
    sample = {
        "data": {
            "notes": {
                "contents": [
                    {
                        "key": "n123",
                        "name": "鷲宮神社へ聖地巡礼",
                        "body": "<p>とても良かった</p>",
                        "user": {"urlname": "taro", "nickname": "太郎"},
                    }
                ]
            }
        }
    }
    posts = NoteSource(use_browser=False)._parse(sample)
    assert len(posts) == 1
    p = posts[0]
    assert isinstance(p, Post)
    assert "鷲宮神社" in p.text
    assert p.url == "https://note.com/taro/n/n123"
    assert p.author == "太郎"


def test_note_parse_unknown_schema_returns_empty():
    assert NoteSource(use_browser=False)._parse({"unexpected": 1}) == []


def test_note_search_uses_browser_then_parses(monkeypatch):
    sample = {"data": {"notes": {"contents": [
        {"key": "k", "name": "大洗海岸", "body": "", "user": {"urlname": "u"}}
    ]}}}
    src = NoteSource(use_browser=True)
    monkeypatch.setattr(src, "_fetch_browser", lambda url: sample)
    posts = src.search("作品 聖地巡礼")
    assert posts[0].title == "大洗海岸"


def test_note_browser_failure_falls_back_to_httpx(monkeypatch):
    sample = {"data": {"notes": {"contents": []}}}
    src = NoteSource(use_browser=True)

    def browser_boom(url):
        raise SourceError("browser blew up")

    monkeypatch.setattr(src, "_fetch_browser", browser_boom)
    monkeypatch.setattr(src, "_fetch_httpx", lambda url: sample)
    assert src.search("x") == []


def test_note_http_error_raises_sourceerror(monkeypatch):
    import httpx
    src = NoteSource(use_browser=False)

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(SourceError):
        src.search("x")


def test_twitter_requires_token():
    src = TwitterSource(bearer_token=None)
    with pytest.raises(SourceError) as ei:
        src.search("作品 聖地巡礼")
    assert "トークン" in str(ei.value)
