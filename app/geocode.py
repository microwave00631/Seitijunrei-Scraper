"""Nominatim(OpenStreetMap)によるジオコーディングクライアント。

聖地名 / 「作品名 + 聖地」等のクエリから候補地点(緯度経度)を取得する。

重要(利用上の注意):
  Nominatim の公開サーバには利用規約がある。
  - 1 秒あたり最大 1 リクエスト(本クライアントは送出間隔を強制)。
  - 識別可能な User-Agent(連絡先)を必須とする。
  - 大量・常時の利用は自前 Nominatim か商用プロバイダを使うこと。
  詳細: https://operations.osmfoundation.org/policies/nominatim/
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# 規約に従い連絡先を含む User-Agent。実運用では自分の連絡先に差し替えること。
DEFAULT_USER_AGENT = (
    "Seitijunrei-Scraper/0.1 (+https://github.com/microwave00631/seitijunrei-scraper)"
)
MIN_INTERVAL_S = 1.1  # 1req/sec 制限を確実に守るための最小送出間隔。


@dataclass
class GeoResult:
    lat: float
    lon: float
    display_name: str
    osm_type: str
    osm_id: int
    importance: float

    @property
    def source_url(self) -> str:
        """この地点の OSM 上の参照 URL(検索ソースとして使う)。"""
        if self.osm_type and self.osm_id:
            return f"https://www.openstreetmap.org/{self.osm_type}/{self.osm_id}"
        return NOMINATIM_URL


class _RateLimiter:
    """プロセス内で送出間隔を直列に守る簡易レートリミッタ。"""

    def __init__(self, min_interval_s: float) -> None:
        self._min = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min:
                time.sleep(self._min - delta)
            self._last = time.monotonic()


class NominatimClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        base_url: str = NOMINATIM_URL,
        min_interval_s: float = MIN_INTERVAL_S,
        timeout_s: float = 15.0,
        accept_language: str = "ja",
    ) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.accept_language = accept_language
        self._limiter = _RateLimiter(min_interval_s)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
        )

    def search(self, query: str, limit: int = 5) -> list[GeoResult]:
        """クエリで地点を検索して GeoResult のリストを返す。"""
        self._limiter.wait()
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": str(limit),
            "accept-language": self.accept_language,
            "addressdetails": "0",
        }
        resp = self._client.get(self.base_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        results: list[GeoResult] = []
        for item in data:
            try:
                results.append(
                    GeoResult(
                        lat=float(item["lat"]),
                        lon=float(item["lon"]),
                        display_name=item.get("display_name", ""),
                        osm_type=item.get("osm_type", ""),
                        osm_id=int(item.get("osm_id", 0)),
                        importance=float(item.get("importance", 0.0)),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return results

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "NominatimClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
