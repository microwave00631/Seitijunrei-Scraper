"""Playwright による地図スクリーンショット取得。

指定座標を中心とした OpenStreetMap の地図ページを開いてピンを立て、
PNG を保存する。Playwright のブラウザが無い等で失敗した場合は None を返し、
呼び出し側は screenshot 無しの Seiti を作れるようにする(機能を止めない)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _osm_marker_url(lat: float, lon: float, zoom: int = 17) -> str:
    """ピン付き OSM 地図ページの URL。"""
    return (
        "https://www.openstreetmap.org/"
        f"?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"
    )


def capture_map(
    lat: float,
    lon: float,
    out_path: str,
    zoom: int = 17,
    width: int = 900,
    height: int = 700,
    timeout_ms: int = 20000,
) -> Optional[str]:
    """座標中心の地図スクショを out_path に保存し、そのパスを返す。

    取得に失敗した場合は None を返す(例外は投げない)。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    url = _osm_marker_url(lat, lon, zoom)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                # タイルの描画を少し待つ。
                page.wait_for_timeout(1500)
                page.screenshot(path=out_path)
            finally:
                browser.close()
    except Exception:
        # ブラウザ未インストール / ネットワーク不可 / タイムアウト等は握りつぶす。
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return None
    return out_path
