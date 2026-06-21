"""ソース(note 応答パース / Twitter トークン必須)のテスト。"""

import pytest

from app.sources import NoteSource, Post, SourceError, TwitterSource, _strip_html


def test_strip_html():
    assert _strip_html("<p>あ&amp;い</p>") == "あ&い"


def test_note_parses_v3_schema(monkeypatch):
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

    src = NoteSource()

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return sample

    monkeypatch.setattr(src._client, "get", lambda *a, **k: FakeResp())
    posts = src.search("作品 聖地巡礼")
    assert len(posts) == 1
    p = posts[0]
    assert isinstance(p, Post)
    assert "鷲宮神社" in p.text
    assert p.url == "https://note.com/taro/n/n123"
    assert p.author == "太郎"


def test_note_http_error_raises_sourceerror(monkeypatch):
    import httpx
    src = NoteSource()

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(src._client, "get", boom)
    with pytest.raises(SourceError):
        src.search("x")


def test_twitter_requires_token():
    src = TwitterSource(bearer_token=None)
    with pytest.raises(SourceError) as ei:
        src.search("作品 聖地巡礼")
    assert "トークン" in str(ei.value)
