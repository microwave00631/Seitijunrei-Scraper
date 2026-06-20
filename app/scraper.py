"""聖地巡礼スクレイパ本体。

入力された項目(作品名など)に「聖地」「聖地巡礼」等のキーワードを付けて
Nominatim を検索し、ヒットした地点を Seiti として SeitiStore に投入する。
1 サイト(=1 検索)から複数の Seiti が得られる場合は全て投入し、座標が 1m
以内のものは SeitiStore 側で同一視・統合される。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .geocode import GeoResult, NominatimClient
from .models import Coordinate, Seiti, SeitiStore
from .screenshot import capture_map

# 「項目 + ○○」で投げる聖地系キーワード。
DEFAULT_KEYWORDS = ["聖地", "聖地巡礼", "舞台", "ロケ地"]


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w぀-ヿ一-鿿]+", "_", text.strip())
    return s.strip("_")[:60] or "seiti"


@dataclass
class ScrapeConfig:
    keywords: list[str] = None  # type: ignore[assignment]
    limit_per_query: int = 5
    take_screenshots: bool = True
    screenshot_dir: str = "screenshots"
    dedup_radius_m: float = 1.0
    max_candidates: int = 80

    def __post_init__(self) -> None:
        if self.keywords is None:
            self.keywords = list(DEFAULT_KEYWORDS)


def build_queries(item: str, keywords: list[str]) -> list[str]:
    """項目とキーワードから検索クエリ群を作る。"""
    item = item.strip()
    return [f"{item} {kw}".strip() for kw in keywords]


def _geo_to_seiti(
    item: str,
    query: str,
    geo: GeoResult,
    cfg: ScrapeConfig,
) -> Seiti:
    screenshot_path: Optional[str] = None
    if cfg.take_screenshots:
        fname = f"{_slugify(item)}_{geo.osm_type}_{geo.osm_id}.png"
        out = str(Path(cfg.screenshot_dir) / fname)
        screenshot_path = capture_map(geo.lat, geo.lon, out)
    return Seiti(
        coordinate=Coordinate(lat=geo.lat, lon=geo.lon),
        source=geo.source_url,
        screenshot_path=screenshot_path,
        name=geo.display_name,
        query=query,
    )


def scrape(
    item: str,
    cfg: Optional[ScrapeConfig] = None,
    client: Optional[NominatimClient] = None,
) -> SeitiStore:
    """項目から聖地を収集して SeitiStore を返す。

    Args:
        item: 検索の起点となる項目(作品名など)。
        cfg: スクレイプ設定。
        client: ジオコーディングクライアント(テスト時に差し替え可能)。
    """
    if not item or not item.strip():
        raise ValueError("item must be a non-empty string")
    cfg = cfg or ScrapeConfig()
    store = SeitiStore(
        dedup_radius_m=cfg.dedup_radius_m,
        max_candidates=cfg.max_candidates,
    )

    own_client = client is None
    client = client or NominatimClient()
    try:
        for query in build_queries(item, cfg.keywords):
            try:
                results = client.search(query, limit=cfg.limit_per_query)
            except Exception:
                # 1 クエリの失敗で全体を止めない。
                continue
            for geo in results:
                store.add(_geo_to_seiti(item, query, geo, cfg))
    finally:
        if own_client:
            client.close()
    return store
