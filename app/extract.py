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
