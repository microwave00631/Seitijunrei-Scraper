"""検索ソース: note(スクレイプ) / Twitter(公式APIのみ)。

各ソースは `search(query, limit)` で投稿(Post)のリストを返す。
ネットワークやパースに失敗した場合は SourceError を送出し、呼び出し側で
「エラーとして可視化」できるようにする(黙って 0 件にしない)。
"""

from __future__ import annotations

import html
import os
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

    note の前段(WAF)は非ブラウザ UA を 403 で弾くため、ブラウザ相当のヘッダを
    送り、初回にトップページへアクセスしてクッキーを取得(ウォームアップ)する。

    注意: note の自動取得は規約上グレー。低頻度・私的利用を前提とすること。
    User-Agent は環境変数 NOTE_USER_AGENT で上書きできる。
    """

    name = "note"
    SEARCH_URL = "https://note.com/api/v3/searches"
    HOME_URL = "https://note.com/"
    DEFAULT_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout_s: float = 15.0,
    ) -> None:
        ua = user_agent or os.environ.get("NOTE_USER_AGENT") or self.DEFAULT_UA
        self._client = httpx.Client(
            headers={
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://note.com/search",
            },
            timeout=timeout_s,
            follow_redirects=True,
        )
        self._warmed = False

    def _warmup(self) -> None:
        """トップページに 1 回アクセスしてクッキーを取得する。"""
        if self._warmed:
            return
        try:
            self._client.get(self.HOME_URL)
        except httpx.HTTPError:
            pass  # 失敗しても本リクエストを試す。
        self._warmed = True

    def search(self, query: str, limit: int = 20) -> list[Post]:
        self._warmup()
        params = {"context": "note", "q": query, "size": str(limit), "start": "0"}
        try:
            resp = self._client.get(self.SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = ""
            if code == 403:
                hint = (
                    "（note の bot 対策でブロックされた可能性。NOTE_USER_AGENT を"
                    "実ブラウザの値に変える/頻度を下げる等を試してください）"
                )
            raise SourceError(f"note 取得失敗: HTTP {code}{hint}") from e
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
