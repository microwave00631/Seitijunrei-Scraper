"""FastAPI Web アプリ。検索窓に項目を入れて聖地を収集・表示する。

起動:
    uvicorn app.main:app --reload

テンプレートは Jinja2 を直接使って描画する(Starlette のテンプレート層には
依存しない)。
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .auth import BasicAuthMiddleware
from .scraper import ScrapeConfig, scrape

BASE_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = BASE_DIR.parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Seitijunrei-Scraper")
# 簡易パスワード(Basic 認証)を全ルートに適用。設定は app/auth.py 参照。
app.add_middleware(BasicAuthMiddleware)
app.mount(
    "/screenshots",
    StaticFiles(directory=str(SCREENSHOT_DIR)),
    name="screenshots",
)

_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)


def render(**ctx) -> str:
    return _env.get_template("index.html").render(**ctx)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(render(item="", result=None, error=None))


def _run_scrape(item: str, take_screenshots: bool) -> dict:
    cfg = ScrapeConfig(
        take_screenshots=take_screenshots,
        screenshot_dir=str(SCREENSHOT_DIR),
    )
    store = scrape(item, cfg)
    return store.to_dict()


async def _scrape_async(item: str, take_screenshots: bool) -> dict:
    """同期 I/O(httpx/playwright)をスレッドプールで実行する。

    asyncio.to_thread は Python 3.9+ なので、3.8 でも動くよう
    run_in_executor を使う。
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(_run_scrape, item, take_screenshots)
    )


@app.post("/search", response_class=HTMLResponse)
async def search(
    item: str = Form(...),
    screenshots: bool = Form(False),
) -> HTMLResponse:
    error = None
    result = None
    try:
        result = await _scrape_async(item, screenshots)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    return HTMLResponse(render(item=item, result=result, error=error))


@app.get("/api/search")
async def api_search(item: str, screenshots: bool = False) -> JSONResponse:
    """JSON で結果を返す API。"""
    try:
        result = await _scrape_async(item, screenshots)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)
