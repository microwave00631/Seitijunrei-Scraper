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

    note の前段(Cloudflare 系 WAF)は素の HTTP クライアントを 403 で弾くため、
    既定では **Playwright の実ブラウザで note を開き、ページ内 fetch で API を
    叩く** 方式を使う(JS 判定・クッキーを実ブラウザとして通過できる)。
    ブラウザが使えない/失敗した場合は httpx にフォールバックする。

    注意: note の自動取得は規約上グレー。低頻度・私的利用を前提とすること。
    UA は環境変数 NOTE_USER_AGENT、ブラウザ利用可否は NOTE_USE_BROWSER で制御。
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
        timeout_s: float = 30.0,
        use_browser: Optional[bool] = None,
    ) -> None:
        self.ua = user_agent or os.environ.get("NOTE_USER_AGENT") or self.DEFAULT_UA
        self.timeout_s = timeout_s
        if use_browser is None:
            use_browser = os.environ.get("NOTE_USE_BROWSER", "1").lower() not in {
                "0", "false", "off", "no"
            }
        self.use_browser = use_browser

    # --- 取得 ---------------------------------------------------------------

    def _api_url(self, query: str, limit: int) -> str:
        from urllib.parse import urlencode
        qs = urlencode(
            {"context": "note", "q": query, "size": str(limit), "start": "0"}
        )
        return f"{self.SEARCH_URL}?{qs}"

    def _fetch_browser(self, url: str) -> dict:
        """実ブラウザで note を開き、ページ内 fetch で API を叩いて JSON を返す。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise SourceError("Playwright 未導入のためブラウザ取得不可") from e

        timeout_ms = int(self.timeout_s * 1000)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=self.ua, locale="ja-JP")
                page = ctx.new_page()
                # note を開いて WAF を通過(クッキー取得)。
                page.goto(self.HOME_URL, wait_until="domcontentloaded",
                          timeout=timeout_ms)
                page.wait_for_timeout(1500)
                # 同一オリジンから fetch すれば JS 判定・CORS を回避できる。
                raw = page.evaluate(
                    """async (u) => {
                        const r = await fetch(u, {
                            headers: {'X-Requested-With': 'XMLHttpRequest',
                                      'Accept': 'application/json'},
                            credentials: 'include'
                        });
                        return JSON.stringify({status: r.status, body: await r.text()});
                    }""",
                    url,
                )
            finally:
                browser.close()
        import json as _json
        envelope = _json.loads(raw)
        if envelope.get("status") != 200:
            body = (envelope.get("body") or "")[:160].replace("\n", " ")
            raise SourceError(
                f"note 取得失敗(browser): HTTP {envelope.get('status')} body={body!r}"
            )
        try:
            return _json.loads(envelope["body"])
        except ValueError as e:
            raise SourceError("note 応答が JSON でない(browser)") from e

    def _fetch_httpx(self, url: str) -> dict:
        headers = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://note.com/search",
        }
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True,
                              headers=headers) as client:
                client.get(self.HOME_URL)  # warmup(cookie)
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = "（note の WAF にブロック。NOTE_USE_BROWSER=1 で実ブラウザ取得を）" \
                if code == 403 else ""
            raise SourceError(f"note 取得失敗: HTTP {code}{hint}") from e
        except httpx.HTTPError as e:
            raise SourceError(f"note 取得失敗: {e}") from e
        except ValueError as e:
            raise SourceError(f"note 応答が JSON でない: {e}") from e

    def search(self, query: str, limit: int = 20) -> list[Post]:
        url = self._api_url(query, limit)
        if self.use_browser:
            try:
                data = self._fetch_browser(url)
            except SourceError as be:
                # フォールバックも失敗したら、両方の理由を残す(原因切り分け用)。
                try:
                    data = self._fetch_httpx(url)
                except SourceError as he:
                    raise SourceError(f"browser失敗[{be}] / httpx失敗[{he}]") from he
        else:
            data = self._fetch_httpx(url)
        return self._parse(data)

    # --- パース -------------------------------------------------------------

    def _parse(self, data: dict) -> list[Post]:
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
        pass


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
