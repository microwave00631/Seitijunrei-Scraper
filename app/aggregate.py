"""検索結果を「まとめ直す」自動化の中核。

note(と任意で Twitter 公式 API)で「項目 + 聖地巡礼」を検索し、
各投稿の本文から地名を抽出 → Nominatim で座標化 → 同一地点を投稿横断で
集約(出典 URL・言及数をまとめる)→ Seiti 化 & 1m 重複統合する。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .extract import extract_places
from .geocode import NominatimClient
from .models import Coordinate, Seiti, SeitiStore
from .screenshot import capture_map
from .sources import Post, Source, SourceError

DEFAULT_KEYWORDS = ["聖地巡礼", "聖地"]


@dataclass
class AggregateConfig:
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    posts_per_query: int = 20
    max_places: int = 40          # ジオコーディング呼び出し数の上限(レート制御のため)
    take_screenshots: bool = False
    screenshot_dir: str = "screenshots"
    dedup_radius_m: float = 1.0
    max_candidates: int = 80
    countrycodes: Optional[str] = "jp"


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^\w一-鿿぀-ヿ]+", "_", text).strip("_")[:50] or "seiti"


def gather_posts(
    item: str, sources: list[Source], cfg: AggregateConfig
) -> tuple[list[Post], list[str]]:
    """全ソース×全キーワードで投稿を集める。失敗はエラー文字列で返す。"""
    posts: list[Post] = []
    errors: list[str] = []
    for src in sources:
        for kw in cfg.keywords:
            query = f"{item} {kw}".strip()
            try:
                posts.extend(src.search(query, limit=cfg.posts_per_query))
            except SourceError as e:
                errors.append(f"[{src.name}] {query}: {e}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"[{src.name}] {query}: 予期せぬエラー {e}")
    return posts, errors


def aggregate(
    item: str,
    sources: list[Source],
    geocoder: NominatimClient,
    cfg: Optional[AggregateConfig] = None,
) -> tuple[SeitiStore, dict]:
    """項目から聖地をまとめ直して SeitiStore と統計(meta)を返す。"""
    if not item or not item.strip():
        raise ValueError("item must be a non-empty string")
    cfg = cfg or AggregateConfig()

    posts, errors = gather_posts(item, sources, cfg)

    # 地名 → その地名に言及した投稿(URL集合) を作る。
    place_to_urls: dict[str, list[str]] = defaultdict(list)
    place_to_excerpt: dict[str, str] = {}
    for post in posts:
        for place in extract_places(post.text, max_places=cfg.max_places):
            if post.url and post.url not in place_to_urls[place]:
                place_to_urls[place].append(post.url)
            place_to_excerpt.setdefault(place, post.text[:140])

    # 言及数の多い地名から順にジオコーディング(上限まで)。
    ranked = sorted(place_to_urls.items(), key=lambda kv: len(kv[1]), reverse=True)

    store = SeitiStore(
        dedup_radius_m=cfg.dedup_radius_m, max_candidates=cfg.max_candidates
    )
    geocode_misses: list[str] = []
    geocoded = 0
    for place, urls in ranked:
        if geocoded >= cfg.max_places:
            break
        try:
            results = geocoder.search(place, limit=1, countrycodes=cfg.countrycodes)
        except Exception as e:  # noqa: BLE001
            errors.append(f"[geocode] {place}: {e}")
            continue
        geocoded += 1
        if not results:
            geocode_misses.append(place)
            continue
        g = results[0]
        shot = None
        if cfg.take_screenshots:
            out = str(Path(cfg.screenshot_dir) / f"{_slug(place)}.png")
            shot = capture_map(g.lat, g.lon, out)
        store.add(
            Seiti(
                coordinate=Coordinate(g.lat, g.lon),
                source=urls[0] if urls else g.source_url,
                screenshot_path=shot,
                name=place,
                query=item,
                mentions=list(urls),
                excerpt=place_to_excerpt.get(place, ""),
            )
        )

    # 言及の多い順に並べ替える(まとめとして見やすく)。
    store.seiti.sort(key=lambda s: len(s.mentions), reverse=True)

    meta = {
        "item": item,
        "posts_found": len(posts),
        "places_extracted": len(place_to_urls),
        "geocoded": geocoded,
        "geocode_misses": geocode_misses,
        "errors": errors,
    }
    return store, meta
