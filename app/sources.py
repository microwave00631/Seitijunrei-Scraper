"""検索ソース: note(スクレイプ) / Twitter(公式APIのみ)。

各ソースは `search(query, limit)` で投稿(Post)のリストを返す。
ネットワークやパースに失敗した場合は SourceError を送出し、呼び出し側で
「エラーとして可視化」できるようにする(黙って 0 件にしない)。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import httpx


@dataclass
class Post:
    """1 件の投稿/記事。"""

    text: str           # 地名抽出に使う本文(タイトル+抜粋)
    url: str            # 出典 URL
    source_name: str    # "note" / "twitter" など
    title: str = ""
    author: str = ""


class SourceError(Exception):
    """ソース取得時のエラー(ネットワーク/規約/パース)。"""


class Source(Protocol):
    name: str

    def search(self, query: str, limit: int = 20) -> list[Post]: ...


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", s or "")).strip()


def _dig(data: Any, *paths: tuple[str, ...]) -> Any:
    """ネストした dict から最初に取れたパスの値を返す(スキーマ揺れ対策)。"""
    for path in paths:
        cur = data
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


class NoteSource:
    """note(note.com)の検索。内部の検索 JSON エンドポイントを利用する。

    注意: note の自動取得は規約上グレー。低頻度・私的利用を前提とし、
    User-Agent を明示する。
    """

    name = "note"
    SEARCH_URL = "https://note.com/api/v3/searches"

    def __init__(
        self,
        user_agent: str = "Seitijunrei-Scraper/0.1 (private use)",
        timeout_s: float = 15.0,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout_s,
        )

    def search(self, query: str, limit: int = 20) -> list[Post]:
        params = {"context": "note", "q": query, "size": str(limit), "start": "0"}
        try:
            resp = self._client.get(self.SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise SourceError(f"note 取得失敗: {e}") from e
        except ValueError as e:
            raise SourceError(f"note 応答が JSON でない: {e}") from e

        contents = _dig(
            data,
            ("data", "notes", "contents"),
            ("data", "contents"),
            ("notes", "contents"),
        )
        if not isinstance(contents, list):
            return []

        posts: list[Post] = []
        for c in contents:
            if not isinstance(c, dict):
                continue
            title = _strip_html(str(c.get("name", "")))
            body = _strip_html(str(c.get("body", "")))
            key = c.get("key", "")
            urlname = _dig(c, ("user", "urlname")) or c.get("urlname", "")
            url = c.get("noteUrl") or (
                f"https://note.com/{urlname}/n/{key}" if urlname and key else ""
            )
            author = _dig(c, ("user", "nickname")) or ""
            text = f"{title}。{body}".strip("。")
            posts.append(
                Post(text=text, url=url, source_name=self.name,
                     title=title, author=str(author))
            )
        return posts

    def close(self) -> None:
        self._client.close()


class TwitterSource:
    """Twitter/X の検索。**公式 API(Bearer Token)が必須**。

    スクレイプは規約違反・凍結リスクのため行わない。トークンが無い場合は
    SourceError を送出する。Recent search API を利用する。
    """

    name = "twitter"
    SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

    def __init__(self, bearer_token: Optional[str] = None, timeout_s: float = 15.0) -> None:
        self.bearer_token = bearer_token
        self._timeout_s = timeout_s

    def search(self, query: str, limit: int = 20) -> list[Post]:
        if not self.bearer_token:
            raise SourceError(
                "Twitter は公式 API トークンが必要です(環境変数 TWITTER_BEARER_TOKEN)。"
                "スクレイプは規約違反のため行いません。"
            )
        params = {
            "query": f"{query} -is:retweet lang:ja",
            "max_results": str(max(10, min(limit, 100))),
            "tweet.fields": "author_id,entities",
        }
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.get(self.SEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise SourceError(f"Twitter API 取得失敗: {e}") from e

        posts: list[Post] = []
        for t in data.get("data", []) or []:
            tid = t.get("id", "")
            posts.append(
                Post(
                    text=_strip_html(t.get("text", "")),
                    url=f"https://twitter.com/i/web/status/{tid}",
                    source_name=self.name,
                )
            )
        return posts
