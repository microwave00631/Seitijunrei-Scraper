"""コアデータモデル: Coordinate / Seiti / SeitiStore。

- Seiti クラスは (座標, 検索ソース, スクリーンショット) の3つ組を保持する。
- SeitiStore は複数の Seiti を管理し、座標が一定距離(既定 1m)以内のものを
  「同一の聖地」とみなして 1 つに統合する。統合で消える側は候補(candidate)
  として退避し、候補は最大 80 件まで保持する(古いものから破棄)。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# 同一聖地とみなす距離のしきい値(メートル)。仕様: 1m 以下なら同一。
DEFAULT_DEDUP_RADIUS_M = 1.0
# 候補として保持できる最大件数。仕様: 80 個まで。
MAX_CANDIDATES = 80

EARTH_RADIUS_M = 6_371_008.8  # 平均地球半径(メートル, IUGG)


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2 つの緯度経度間の大圏距離をメートルで返す。

    1m 前後の近接判定が目的なので、球面近似(haversine)で十分な精度がある。
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


@dataclass(frozen=True)
class Coordinate:
    """緯度経度。Google Map のピン/座標に相当する。"""

    lat: float
    lon: float

    def distance_to(self, other: "Coordinate") -> float:
        return haversine_distance_m(self.lat, self.lon, other.lat, other.lon)

    def __post_init__(self) -> None:
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"lat out of range: {self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"lon out of range: {self.lon}")


@dataclass
class Seiti:
    """聖地 1 件分の情報。

    Attributes:
        coordinate: Google Map ピン相当の座標。
        source: 検索ソース(由来の URL / クエリ / OSM の参照など)。
        screenshot_path: スクリーンショット画像へのパス(取得できない場合 None)。
        name: 表示名(任意)。
        query: この聖地を見つけた検索クエリ(任意)。
        mentions: この地点に言及した出典 URL のリスト(note 記事など)。
        excerpt: 出典本文からの抜粋(任意)。
        found_at: 作成時刻(エポック秒)。候補の破棄順序に使う。
    """

    coordinate: Coordinate
    source: str
    screenshot_path: Optional[str] = None
    name: str = ""
    query: str = ""
    mentions: list[str] = field(default_factory=list)
    excerpt: str = ""
    found_at: float = field(default_factory=time.time)

    def is_same_place(self, other: "Seiti", radius_m: float = DEFAULT_DEDUP_RADIUS_M) -> bool:
        """座標が radius_m 以内なら同一の聖地とみなす。"""
        return self.coordinate.distance_to(other.coordinate) <= radius_m

    def merge_mentions_from(self, other: "Seiti") -> None:
        """別 Seiti の出典をこの Seiti に取り込む(重複 URL は除外)。"""
        seen = set(self.mentions)
        for url in other.mentions:
            if url not in seen:
                self.mentions.append(url)
                seen.add(url)
        if not self.excerpt and other.excerpt:
            self.excerpt = other.excerpt

    def completeness(self) -> int:
        """情報量の簡易スコア。統合時にどちらを残すか決めるのに使う。"""
        score = 0
        if self.screenshot_path:
            score += 2
        if self.name:
            score += 1
        if self.source:
            score += 1
        score += min(len(self.mentions), 5)  # 言及が多い方を優先。
        return score

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["coordinate"] = {"lat": self.coordinate.lat, "lon": self.coordinate.lon}
        return d


class SeitiStore:
    """複数の Seiti を保持し、近接重複を統合するストア。

    - add() で追加。既存に 1m 以内のものがあれば統合し、情報量の少ない方
      (= 消える側)を候補に退避する。
    - 候補は最大 MAX_CANDIDATES 件。超過時は古いものから破棄する。
    """

    def __init__(
        self,
        dedup_radius_m: float = DEFAULT_DEDUP_RADIUS_M,
        max_candidates: int = MAX_CANDIDATES,
    ) -> None:
        self.dedup_radius_m = dedup_radius_m
        self.max_candidates = max_candidates
        self.seiti: list[Seiti] = []
        self.candidates: list[Seiti] = []

    def _find_duplicate_index(self, item: Seiti) -> Optional[int]:
        for i, existing in enumerate(self.seiti):
            if existing.is_same_place(item, self.dedup_radius_m):
                return i
        return None

    def _push_candidate(self, item: Seiti) -> None:
        """候補へ退避。上限超過なら最古を破棄する。"""
        self.candidates.append(item)
        if len(self.candidates) > self.max_candidates:
            # found_at が最も古いものを 1 件落とす。
            oldest = min(
                range(len(self.candidates)),
                key=lambda i: self.candidates[i].found_at,
            )
            self.candidates.pop(oldest)

    def add(self, item: Seiti) -> bool:
        """Seiti を追加する。

        Returns:
            新規に primary として採用されたら True、
            既存との重複として候補に退避されたら False。
        """
        idx = self._find_duplicate_index(item)
        if idx is None:
            self.seiti.append(item)
            return True

        existing = self.seiti[idx]
        # 情報量が多い方を残す。同点なら先に登録された既存を優先(消える側=新規)。
        # どちらを残す場合でも、出典(言及)は survivor に集約する(=まとめ直し)。
        if item.completeness() > existing.completeness():
            item.merge_mentions_from(existing)
            self.seiti[idx] = item       # 新規を採用
            self._push_candidate(existing)  # 既存が消える側 → 候補へ
        else:
            existing.merge_mentions_from(item)
            self._push_candidate(item)   # 新規が消える側 → 候補へ
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "seiti": [s.to_dict() for s in self.seiti],
            "candidates": [c.to_dict() for c in self.candidates],
            "dedup_radius_m": self.dedup_radius_m,
            "max_candidates": self.max_candidates,
        }
