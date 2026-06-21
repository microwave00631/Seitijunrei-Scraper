"""note 取得の一発診断スクリプト。

Mac のターミナルでプロジェクト直下から実行:

    source .venv/bin/activate
    python scripts/diagnose_note.py らき☆すた

出力をそのまま貼ってもらえれば、403 の正体(Chromium 未導入 / WAF チャレンジ /
スキーマズレ)を確定して修正できます。
"""

from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを import パスに追加。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources import NoteSource  # noqa: E402


def main() -> None:
    item = sys.argv[1] if len(sys.argv) > 1 else "らき☆すた"
    query = f"{item} 聖地巡礼"
    src = NoteSource(use_browser=False)
    url = src._api_url(query, 5)
    print(f"# query = {query!r}")
    print(f"# url   = {url}")

    print("\n== [1] Playwright / Chromium 確認 ==")
    pw_ok = False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        print("OK: Playwright + Chromium 使用可")
        pw_ok = True
    except Exception as e:  # noqa: BLE001
        print(f"NG: {type(e).__name__}: {e}")
        print("   -> `python -m playwright install chromium` が必要かもしれません")

    print("\n== [2] httpx 直叩き(WAF をそのまま観察) ==")
    import httpx

    headers = {
        "User-Agent": src.ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://note.com/search",
    }
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as c:
            home = c.get(src.HOME_URL)
            print(f"home: HTTP {home.status_code}")
            r = c.get(url)
            print(f"api : HTTP {r.status_code}")
            print("api body head:", r.text[:300].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print(f"ERR: {type(e).__name__}: {e}")

    if pw_ok:
        print("\n== [3] 実ブラウザ経由(本命) ==")
        src_b = NoteSource(use_browser=True)
        try:
            data = src_b._fetch_browser(url)
            posts = src_b._parse(data)
            print(f"OK: top-level keys = {list(data)[:6]}")
            print(f"OK: parsed posts = {len(posts)}")
            for p in posts[:3]:
                print(f"   - {p.title[:30]} | {p.url}")
            if not posts:
                print("   ※ 取得は成功したが parse 0 件 → スキーマズレの可能性")
        except Exception as e:  # noqa: BLE001
            print(f"ERR: {e}")

    print("\n== 判定の見方 ==")
    print(" - [3]がOKで posts>0 → アプリでも動く(NOTE_USE_BROWSER=1)")
    print(" - [3]が HTTP 403 + body に 'challenge'/'Just a moment' → headless検出")
    print(" - [3]がOKだが parsed 0 → JSON構造が変わった(貼ってくれれば直す)")
    print(" - [1]がNG → chromium 未導入")


if __name__ == "__main__":
    main()
