"""投稿本文から日本語の地名・施設名を抽出するヒューリスティック。

完全な固有表現抽出ではなく、聖地巡礼でよく出る接尾辞(神社/駅/公園 等)の
直前の語をまとめて拾う簡易方式。誤検出はあり得るが、後段の Nominatim
ジオコーディングで座標化できないものは自然に落ちる。
"""

from __future__ import annotations

import re

# 聖地でよく登場する地名・施設の接尾辞。長いものを先に並べる。
SUFFIXES = [
    "神社", "神宮", "大社", "稲荷", "東照宮", "八幡宮",
    "寺院", "寺", "大師",
    "高等学校", "高校", "中学校", "小学校", "学園", "大学",
    "商店街", "展望台", "展望公園", "公園", "庭園",
    "海水浴場", "海岸", "砂浜", "海浜", "漁港", "港",
    "城跡", "城址", "城下町", "城",
    "大橋", "歩道橋", "橋",
    "踏切", "駅",
    "温泉", "灯台", "岬", "半島", "湖", "ダム", "滝",
    "タワー", "スタジアム", "ドーム",
    "鳥居", "参道", "石段", "坂",
]

# 接尾辞の直前に来る固有名部分。
# ひらがな(助詞「は」「を」等)を含めると "帰りは鷲宮駅" のように飲み込むため、
# 漢字・カタカナ・英数字と一部の連結文字(ー・々〆ヶ)に限定する。
_NAME = r"[一-鿿ァ-ヶー・々〆0-9A-Za-z]{1,14}"
_SUFFIX_RE = re.compile(rf"({_NAME}(?:{'|'.join(SUFFIXES)}))")

# 明らかに地名でない頻出語を弾く。
_STOPWORDS = {"この駅", "その駅", "次の駅", "最寄駅", "最寄り駅", "前の駅", "各駅"}


def extract_places(text: str, max_places: int = 30) -> list[str]:
    """本文から地名候補を出現順(重複除去)で返す。"""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _SUFFIX_RE.finditer(text):
        place = m.group(1)
        # 接尾辞だけ(=固有名部分が無い)を弾く。
        if any(place == s for s in SUFFIXES):
            continue
        if place in _STOPWORDS or place in seen:
            continue
        seen.add(place)
        out.append(place)
        if len(out) >= max_places:
            break
    return out


# --- 貼り付けテキスト用の抽出(座標 / URL / HTML除去) -----------------------

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """素朴に HTML タグを除去する(貼り付けが HTML でも本文を拾う)。"""
    import html as _html
    return _html.unescape(_TAG_RE.sub(" ", text or ""))


_URL_RE = re.compile(r"https?://[^\s\"'<>）)】」、，]+")


def extract_urls(text: str) -> list[str]:
    """テキスト中の URL を出現順(重複除去)で返す。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,)")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# 緯度経度の各種パターン。地図リンク由来は接頭辞があり曖昧でないので小数1桁以上で許可。
_COORD_PATTERNS = [
    re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),               # Google Maps @lat,lon
    re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)"),            # !3dLAT!4dLON
    re.compile(r"(?:[?&](?:q|ll|query|destination|center|sll)=)"
               r"(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),                # q=/ll=/center=
    re.compile(r"geo:(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),            # geo:lat,lon
]
# 裸の "lat, lon"(誤検出が多いので日本域のみ採用)。
_BARE_COORD_RE = re.compile(r"(?<![\d.])(\d{2}\.\d{3,}),\s*(\d{3}\.\d{3,})(?![\d.])")


def _valid_japan(lat: float, lon: float) -> bool:
    return 20.0 <= lat <= 46.0 and 122.0 <= lon <= 154.0


def extract_coords(text: str) -> list[tuple[float, float]]:
    """テキストから緯度経度ペアを抽出する(重複除去)。

    地図リンク由来のパターンを優先し、最後に裸のペア(日本域のみ)を拾う。
    """
    text = text or ""
    out: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()

    def _add(lat_s: str, lon_s: str, japan_only: bool) -> None:
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        if japan_only and not _valid_japan(lat, lon):
            return
        key = (round(lat, 6), round(lon, 6))
        if key not in seen:
            seen.add(key)
            out.append((lat, lon))

    for pat in _COORD_PATTERNS:
        for m in pat.finditer(text):
            _add(m.group(1), m.group(2), japan_only=False)
    for m in _BARE_COORD_RE.finditer(text):
        _add(m.group(1), m.group(2), japan_only=True)
    return out
