"""検索結果を「まとめ直す」自動化の中核。

note(と任意で Twitter 公式 API)で「項目 + 聖地巡礼」を検索し、
各投稿の本文から地名を抽出 → Nominatim で座標化 → 同一地点を投稿横断で
集約(出典 URL・言及数をまとめる)→ Seiti 化 & 1m 重複統合する。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .extract import extract_coords, extract_places, extract_urls, strip_html
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


def _split_blocks(text: str) -> list[str]:
    """貼り付けテキストを「行/空行区切り」のブロックに分割する。

    検索結果は 1 件 = 数行であることが多いので、空行優先・なければ行単位。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [ln.strip() for ln in text.split("\n") if ln.strip()]
    return blocks


def aggregate_from_text(
    item: str,
    text: str,
    geocoder: Optional[NominatimClient] = None,
    cfg: Optional[AggregateConfig] = None,
) -> tuple[SeitiStore, dict]:
    """貼り付けた検索結果テキストを解析して Seiti にまとめる。

    1) 地図リンク/座標を直接抽出(あれば Nominatim 不要)
    2) 地名を抽出 → geocoder があれば座標化
    3) 同一ブロック内の URL を出典として紐付け、1m 重複統合
    """
    if not text or not text.strip():
        raise ValueError("text must be a non-empty string")
    cfg = cfg or AggregateConfig()
    store = SeitiStore(
        dedup_radius_m=cfg.dedup_radius_m, max_candidates=cfg.max_candidates
    )
    errors: list[str] = []

    blocks = _split_blocks(text)
    place_to_urls: dict[str, list[str]] = defaultdict(list)
    place_to_excerpt: dict[str, str] = {}
    direct_count = 0

    for block in blocks:
        clean = strip_html(block)
        urls = extract_urls(block)
        coords = extract_coords(block)
        # 近くにある地名(あれば名前として使う)。
        places = extract_places(clean, max_places=cfg.max_places)

        # (1) 座標が直接ある → その場で Seiti 化(geocode 不要)。
        for lat, lon in coords:
            store.add(
                Seiti(
                    coordinate=Coordinate(lat, lon),
                    source=urls[0] if urls else "pasted",
                    name=places[0] if places else f"{lat:.5f},{lon:.5f}",
                    query=item,
                    mentions=list(urls),
                    excerpt=clean[:140],
                )
            )
            direct_count += 1

        # (2) 地名 → 後段でまとめて geocode。URL が無くても地名は登録する。
        for place in places:
            bucket = place_to_urls[place]  # defaultdict が空リストを作る
            for u in urls:
                if u not in bucket:
                    bucket.append(u)
            place_to_excerpt.setdefault(place, clean[:140])

    # (2 続き) 地名を言及数順に geocode。
    geocoded = 0
    geocode_misses: list[str] = []
    if geocoder is not None:
        ranked = sorted(place_to_urls.items(), key=lambda kv: len(kv[1]), reverse=True)
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
    elif place_to_urls:
        errors.append(
            "座標を含まない地名がありますが geocoder 未指定のため座標化していません"
        )

    store.seiti.sort(key=lambda s: len(s.mentions), reverse=True)

    meta = {
        "item": item,
        "blocks": len(blocks),
        "direct_coords": direct_count,
        "places_extracted": len(place_to_urls),
        "geocoded": geocoded,
        "geocode_misses": geocode_misses,
        "errors": errors,
    }
    return store, meta
